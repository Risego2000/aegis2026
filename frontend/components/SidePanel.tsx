"use client";

import type { AppConfig, Fence, Health, SourceStatus } from "@/lib/types";
import { CATEGORY_META, fmtNumber, timeAgo, esError } from "@/lib/format";

export type LayerCounts = {
  events: { total: number; last_24h?: number; by_category: Record<string, number> };
  aircraft: number;
  vessels: number;
  satellites: number;
  air: number;
  trains: number;
  cameras: { total: number; networks: Record<string, { label: string; country: string; count: number; online: number }> };
  places: number;
  fences: number;
};

type Props = {
  visible: Record<string, boolean>;
  setVisible: (v: Record<string, boolean>) => void;
  categoryCounts: Record<string, number>;
  activeCats: string[];
  toggleCat: (cat: string) => void;
  hours: number;
  setHours: (h: number) => void;
  fences: Fence[];
  aoiMode: boolean;
  setAoiMode: (v: boolean) => void;
  aoiRadiusKm: number;
  setAoiRadiusKm: (v: number) => void;
  deleteFence: (id: string) => void;
  hotspots: AppConfig["hotspots"];
  flyTo: (lat: number, lon: number, zoom?: number) => void;
  health: Health | null;
  onBreakdownSource: (src: SourceStatus) => void;
  onBreakdownCategory: (cat: string) => void;
  onBreakdownCameras: () => void;
  onBreakdownLayer: (key: string) => void;
  /** descarga los sucesos visibles en CSV o GeoJSON */
  onExport?: (fmt: "csv" | "geojson") => void;
  basemap: string;
  onBasemap: (id: string) => void;
  layerCounts: LayerCounts | null;
  open?: boolean;
  onClose?: () => void;
};

type LayerDef = {
  key: string;
  label: string;
  color: string;
  hint: string;
  count?: (c: LayerCounts | null) => number | null;
  breakdown?: string;
};

const LAYERS: LayerDef[] = [
  {
    key: "events", label: "Sucesos OSINT", color: "#35e0d0",
    hint: "Sismos, incendios, conflictos, protestas y demás sucesos consolidados de 8 fuentes abiertas.",
    count: (c) => c?.events.total ?? null, breakdown: "events",
  },
  {
    key: "aircraft", label: "Aeronaves (ADS-B)", color: "#a5e8ff",
    hint: "Aviones detectados por receptores ADS-B abiertos. Cada uno abre su ficha con ruta de origen y destino.",
    count: (c) => c?.aircraft ?? null, breakdown: "aircraft",
  },
  {
    key: "vessels", label: "Buques (AIS)", color: "#57d9c3",
    hint: "Barcos con señal AIS abierta. La ficha muestra tipo, rumbo, calado y puerto de destino.",
    count: (c) => c?.vessels ?? null, breakdown: "vessels",
  },
  {
    key: "satellites", label: "Satélites", color: "#7ee7ff",
    hint: "Satélites propagados con elementos orbitales públicos. Pulsa uno para ver órbita y huella.",
    count: (c) => c?.satellites ?? null, breakdown: "satellites",
  },
  {
    key: "trains", label: "Trenes (Renfe)", color: "#ffb454",
    hint: "Trenes de Renfe en vivo (Cercanías, AVE, Avlo, Alvia, MD) desde el GTFS-Realtime abierto. De madrugada el feed está vacío: no hay servicio.",
    count: (c) => c?.trains ?? null,
  },
  {
    key: "cameras", label: "Cámaras de tráfico", color: "#b388ff",
    hint: "Cámaras públicas con imagen abierta. No hay cámaras de calle en todos los países: mira la cobertura.",
    count: (c) => c?.cameras.total ?? null, breakdown: "cameras",
  },
  {
    key: "air", label: "Calidad del aire", color: "#a5d6a7",
    hint: "Sensores ciudadanos de aire (PM2.5, PM10).",
    count: (c) => c?.air ?? null, breakdown: "air",
  },
  {
    key: "places", label: "Núcleos urbanos", color: "#8fb4c9",
    hint: "7.342 ciudades y poblaciones de todo el mundo. Cada una se puede pulsar para abrir su ficha.",
    count: (c) => c?.places ?? null, breakdown: "places",
  },
  {
    key: "fences", label: "Zonas vigiladas", color: "#ffd166",
    hint: "Áreas que tú dibujas. Cuando algo entra o sale, se genera una alerta.",
    count: (c) => c?.fences ?? null,
  },
  { key: "graticule", label: "Retícula de coordenadas", color: "#2f5a70", hint: "Meridianos y paralelos para situar las coordenadas." },
];

const WINDOWS = [
  { h: 15 / 60, label: "AHORA", hint: "Últimos 15 minutos: lo que acaba de entrar" },
  { h: 1, label: "1 H", hint: "Solo la última hora" },
  { h: 6, label: "6 H", hint: "Últimas 6 horas" },
  { h: 24, label: "24 H", hint: "Último día" },
  { h: 72, label: "3 D", hint: "Últimos 3 días" },
  { h: 168, label: "7 D", hint: "Última semana" },
];

const BASEMAPS = [
  { id: "vectorial", label: "Operativo", hint: "Fondo oscuro detallado con etiquetas (recomendado)" },
  { id: "calles", label: "Calles", hint: "Calles y carreteras al estilo mapa urbano" },
  { id: "oscuro", label: "Oscuro", hint: "Gris oscuro sin etiquetas" },
  { id: "claro", label: "Claro", hint: "Fondo claro para imprimir o proyectar" },
  { id: "satelite", label: "Satélite", hint: "Imagen real de satélite" },
  {
    id: "transporte",
    label: "Red viaria y ferroviaria",
    hint: "Solo carreteras, autovías, ferrocarril y derrotas marítimas (superpuesto)",
  },
];

const FLAGS: Record<string, string> = {
  ES: "🇪🇸", GB: "🇬🇧", US: "🇺🇸", FI: "🇫🇮", DE: "🇩🇪", FR: "🇫🇷",
};

export default function SidePanel(p: Props) {
  const toggleLayer = (key: string) =>
    p.setVisible({ ...p.visible, [key]: p.visible[key] === false ? true : false });

  const networks = Object.entries(p.layerCounts?.cameras.networks ?? {}).sort(
    (a, b) => b[1].count - a[1].count
  );
  const countries = new Set(networks.map(([, n]) => n.country).filter(Boolean));

  return (
    <aside className={`panel left ${p.open ? "open" : ""}`}>
      <div className="panel-head">
        <span>Centro de control</span>
        <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span className="mono tiny faint" title="Motor de almacenamiento de eventos">
            {p.health?.storage.backend ?? "—"}
          </span>
          <button className="panel-close" onClick={() => p.onClose?.()} aria-label="Cerrar panel">✕</button>
        </span>
      </div>
      <div className="panel-body">
        {/* -------------------------------------------------- ventana temporal */}
        <div className="section">
          <div className="section-title">
            <span>Periodo de los sucesos</span>
            <span className="st-count">{p.hours >= 24 ? `${Math.round(p.hours / 24)} d` : `${p.hours} h`}</span>
          </div>
          <div className="chips">
            {WINDOWS.map((w) => (
              <button
                key={w.h}
                className={`chip ${p.hours === w.h ? "active" : ""}`}
                onClick={() => p.setHours(w.h)}
                title={w.hint}
                aria-pressed={p.hours === w.h}
              >
                {w.label}
              </button>
            ))}
          </div>
          <div className="cov-note">
            Filtra <b>solo los sucesos</b> (no el tráfico aéreo ni los barcos, que son siempre el último dato).
          </div>
        </div>

        {/* ----------------------------------------------------------- capas */}
        <div className="section">
          <div className="section-title">
            <span>Capas del mapa</span>
            <span className="st-count">
              {Object.values(p.visible).filter(Boolean).length}/{LAYERS.length} activas
            </span>
          </div>
          {LAYERS.map((layer) => {
            const count = layer.count ? layer.count(p.layerCounts) : null;
            const on = p.visible[layer.key] !== false;
            return (
              <div
                className={`layer-row ${on ? "" : "off"}`}
                key={layer.key}
                onClick={() => toggleLayer(layer.key)}
                title={layer.hint}
                role="button"
                aria-pressed={on}
              >
                <span className="layer-swatch" style={{ background: layer.color, color: layer.color }} />
                <span className="layer-name">{layer.label}</span>
                {count !== null && count !== undefined && (
                  layer.breakdown ? (
                    <button
                      className="layer-count num-link"
                      title={`Ver los ${fmtNumber(count)} elementos de «${layer.label}»`}
                      onClick={(e) => { e.stopPropagation(); p.onBreakdownLayer(layer.breakdown!); }}
                    >
                      {fmtNumber(count)}
                    </button>
                  ) : (
                    <span className="layer-count">{fmtNumber(count)}</span>
                  )
                )}
                <span className={`switch ${on ? "on" : ""}`} />
              </div>
            );
          })}
        </div>

        {/* ------------------------------------------------- exportar la vista */}
        {p.onExport && (
          <div className="section">
            <div className="section-title">
              <span>Descargar lo que se ve</span>
              <span className="st-count">mismos filtros que el mapa</span>
            </div>
            <div className="btn-row" style={{ flexWrap: "wrap" }}>
              <button className="btn" onClick={() => p.onExport!("csv")} title="CSV con separador ; y acentos, para Excel">
                ⬇ CSV
              </button>
              <button className="btn" onClick={() => p.onExport!("geojson")} title="GeoJSON para QGIS, kepler.gl o cualquier SIG">
                ⬇ GeoJSON
              </button>
            </div>
            <div className="cov-note">
              CSV abre directamente en Excel (separador «;» y codificación UTF-8); el GeoJSON conserva
              la geometría (puntos y áreas de los incendios y ciclones).
            </div>
          </div>
        )}

        {/* --------------------------------------------------- fondo de mapa */}
        <div className="section">
          <div className="section-title">
            <span>Fondo del mapa</span>
            <span className="st-count">{BASEMAPS.find((b) => b.id === p.basemap)?.label ?? "—"}</span>
          </div>
          <div className="chips">
            {BASEMAPS.map((b) => (
              <button
                key={b.id}
                className={`chip ${p.basemap === b.id ? "active" : ""}`}
                onClick={() => p.onBasemap(b.id)}
                title={b.hint}
              >
                {b.label}
              </button>
            ))}
          </div>
        </div>

        {/* ------------------------------------------------------ categorías */}
        <div className="section">
          <div className="section-title">
            <span>Categorías de sucesos</span>
            <span className="st-count">{p.activeCats.length}/{Object.keys(CATEGORY_META).length}</span>
          </div>
          <div className="section-hint">Pulsa una categoría para mostrarla u ocultarla. El número indica cuántos sucesos hay.</div>
          {Object.entries(CATEGORY_META).map(([cat, meta]) => {
            const count = p.categoryCounts[cat] ?? 0;
            const active = p.activeCats.includes(cat);
            return (
              <div className="layer-row" key={cat} onClick={() => p.toggleCat(cat)} title={`${meta.label}: ${count} sucesos en el periodo elegido`}>
                <span className="layer-swatch" style={{ background: meta.color, color: meta.color }} />
                <span className="layer-name" style={{ opacity: active ? 1 : 0.45 }}>{meta.label}</span>
                <button
                  className="layer-count num-link"
                  title={`Ver la lista de ${meta.label.toLowerCase()} (${count})`}
                  onClick={(e) => { e.stopPropagation(); p.onBreakdownCategory(cat); }}
                >
                  {fmtNumber(count)}
                </button>
                <span className={`switch ${active ? "on" : ""}`} />
              </div>
            );
          })}
        </div>

        {/* -------------------------------------------- cobertura de cámaras */}
        <div className="section">
          <div className="section-title">
            <span>Cobertura de cámaras</span>
            <span className="st-count">{networks.length} redes · {countries.size} países</span>
          </div>
          {networks.length === 0 && <div className="tiny faint">Cargando redes…</div>}
          {networks.map(([key, n]) => (
            <div className="layer-row" key={key} title={`${n.label}: ${n.count} cámaras públicas (${n.online} con imagen ahora mismo)`}>
              <span className="layer-swatch" style={{ background: "#b388ff", color: "#b388ff" }} />
              <span className="layer-name">
                {FLAGS[n.country] ? `${FLAGS[n.country]} ` : ""}{n.label}
              </span>
              <span className="layer-badge">{fmtNumber(n.count)}</span>
            </div>
          ))}
          <div className="cov-note">
            Solo se muestran redes con <b>imagen abierta y sin clave</b>. Fuera de estos países no hay cámaras de
            tráfico públicas accesibles: en Madrid, por ejemplo, la DGT no publica sus imágenes en abierto.
          </div>
        </div>

        {/* --------------------------------------------------- geovallas */}
        <div className="section">
          <div className="section-title">
            <span>Zonas vigiladas</span>
            <span className="st-count">{p.fences.length}</span>
          </div>
          <div className="btn-row" style={{ marginBottom: 9 }}>
            <button className={`btn ${p.aoiMode ? "primary" : ""}`} onClick={() => p.setAoiMode(!p.aoiMode)}>
              {p.aoiMode ? "◉ Toca el mapa…" : "＋ Dibujar zona"}
            </button>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 9, marginBottom: 10 }}>
            <span className="tiny faint mono">RADIO</span>
            <input
              type="range" min={25} max={800} step={25} value={p.aoiRadiusKm}
              onChange={(e) => p.setAoiRadiusKm(Number(e.target.value))}
              style={{ flex: 1, accentColor: "#38e0cd" }}
              aria-label="Radio de la zona vigilada en kilómetros"
            />
            <span className="mono tiny nowrap" style={{ width: 54, textAlign: "right" }}>{p.aoiRadiusKm} km</span>
          </div>
          {p.fences.length === 0 && (
            <div className="tiny faint">
              Sin zonas. Dibuja una y recibirás un aviso en cuanto algo entre o salga de ella.
            </div>
          )}
          {p.fences.map((f) => (
            <div className="layer-row" key={f.id}>
              <span className="layer-swatch" style={{ background: "#ffd166", color: "#ffd166" }} />
              <span
                className="layer-name"
                style={{ cursor: "pointer" }}
                onClick={() => f.lat && f.lon && p.flyTo(f.lat, f.lon, 4.5)}
                title="Ir a la zona"
              >
                {f.name}
                <span className="mono tiny faint"> · {Math.round((f.radius_m ?? 0) / 1000)} km</span>
              </span>
              <button className="faint tiny" onClick={() => p.deleteFence(f.id)} title="Eliminar la zona">✕</button>
            </div>
          ))}
        </div>

        {/* ---------------------------------------------- regiones ADS-B */}
        <div className="section">
          <div className="section-title">
            <span>Vistas rápidas</span>
            <span className="st-count">{Object.keys(p.hotspots).length}</span>
          </div>
          <div className="chips">
            {Object.entries(p.hotspots).map(([code, h]) => (
              <button key={code} className="chip" onClick={() => p.flyTo(h.lat, h.lon, 5)} title={`Centrar el mapa en ${code}`}>
                {code}
              </button>
            ))}
            <button className="chip" onClick={() => p.flyTo(0, 20, 1.6)} title="Ver el planeta entero">Mundo</button>
          </div>
        </div>

        {/* ------------------------------------------------------- fuentes */}
        <div className="section">
          <div className="section-title">
            <span>Fuentes de datos</span>
            <span className="st-count">{p.health?.ingest.uptime_s ? `${Math.round(p.health.ingest.uptime_s / 60)} min activo` : "—"}</span>
          </div>
          <div className="section-hint">Cada fuente indica cuántos elementos aporta. Pulsa el número para verlos.</div>
          {(p.health?.ingest.sources ?? []).map((s) => (
            <div className="source-row" key={s.name} title={esError(s.message)}>
              <span className={`status-dot ${s.ok ? "ok" : "err"}`} />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div className="source-name">{s.source ?? s.name}</div>
                <div className="source-msg">
                  <button
                    className="num-link"
                    title={`Ver los ${s.items} elementos de ${s.source ?? s.name}`}
                    onClick={() => p.onBreakdownSource(s)}
                  >
                    {fmtNumber(s.items)}
                  </button>{" "}
                  · {s.last_run ? `hace ${timeAgo(s.last_run)}` : "—"}
                </div>
              </div>
              <span className="source-meta" title="Cada cuánto se actualiza">{s.interval_s}s</span>
            </div>
          ))}
        </div>

        {/* --------------------------------------------------------- leyenda */}
        <div className="section">
          <div className="section-title"><span>Cómo leer el mapa</span></div>
          <div style={{ display: "flex", flexDirection: "column", gap: 7 }}>
            {LAYERS.filter((l) => l.key !== "graticule" && l.key !== "fences").map((l) => (
              <div className="legend-row" key={l.key} style={{ fontSize: 11 }}>
                <span className="legend-dot" style={{ background: l.color, color: l.color }} />
                <span className="dim">{l.hint}</span>
              </div>
            ))}
          </div>
          <div className="cov-note">
            El tamaño de cada punto crece con la magnitud del suceso. Pulsa cualquier elemento del mapa (o de una
            lista) y se abre su ficha completa con país, región, hora exacta y fuentes.
          </div>
        </div>
      </div>
    </aside>
  );
}
