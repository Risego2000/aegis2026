"use client";

/**
 * Ficha de lugar: todo lo que hay donde has pinchado.
 *
 * Se abre con cualquier clic sobre el mapa que no caiga en un elemento (o al
 * pinchar un núcleo urbano) y responde a «¿qué hay aquí?»: país, núcleo urbano
 * más cercano, coordenadas, y los elementos abiertos dentro del radio elegido
 * (eventos, cámaras, aeronaves, buques, satélites y sensores de aire). Cada fila
 * abre a su vez la ficha completa de ese elemento.
 *
 * Orden de lectura: lugar y cifras → ajustes → listas. Solo la primera lista
 * con datos se abre sola; las demás muestran su recuento y se despliegan.
 */

import { categoryMeta, timeAgo } from "@/lib/format";
import { Icon } from "@/components/Icon";
import { PanelHeader, PanelSection, SummaryStrip } from "@/components/PanelUI";
import type { ActorKind } from "@/lib/types";
import { eventSummary } from "@/lib/eventFacts";

export type PlaceData = {
  lat: number;
  lon: number;
  radius_km: number;
  country: { name: string; iso: string; continent: string } | null;
  place: {
    name: string; kind: string; population: number; lat: number; lon: number;
    distance_km: number; region?: string;
  } | null;
  counts: {
    events: number;
    aircraft: number;
    vessels: number;
    satellites: number;
    air: number;
    trains: number;
    traffic: number;
    cameras: number;
  };
  summary: string;
  events: PlaceRow[];
  aircraft: PlaceRow[];
  vessels: PlaceRow[];
  satellites: PlaceRow[];
  air: PlaceRow[];
  trains: PlaceRow[];
  traffic: PlaceRow[];
  cameras: PlaceRow[];
  window_hours: number;
  fetched_at: number;
};

export type PlaceRow = {
  id: string;
  title: string;
  sub?: string;
  lat?: number;
  lon?: number;
  kind?: string;
  category?: string;
  severity?: string;
  distance_km?: number;
  ts?: string;
  summary?: string;
};

type Props = {
  place: { lat: number; lon: number; name?: string } | null;
  data: PlaceData | null;
  loading: boolean;
  radiusKm: number;
  onRadius: (km: number) => void;
  windowHours: number;
  onWindow: (hours: number) => void;
  onPickEvent: (id: string) => void;
  onPickCamera: (id: string) => void;
  onPickActor: (kind: ActorKind, id: string) => void;
  onCenter: () => void;
  onClear: () => void;
  onRefresh: () => void;
  onExploreThreats?: () => void;
  onExploreSources?: () => void;
};

const RADII = [5, 25, 100, 250];

const SECTIONS: {
  key: keyof PlaceData["counts"];
  title: string;
  hint: string;
}[] = [
  { key: "events", title: "Sucesos", hint: "todo el almacén en el radio" },
  { key: "traffic", title: "Tráfico", hint: "incidencias DGT en vivo" },
  { key: "aircraft", title: "Aeronaves", hint: "ADS-B en este instante" },
  { key: "vessels", title: "Buques", hint: "AIS en este instante" },
  { key: "trains", title: "Trenes", hint: "Renfe, FGC y Amtrak en vivo" },
  { key: "cameras", title: "Cámaras públicas", hint: "imagen abierta en vivo" },
  { key: "air", title: "Calidad del aire", hint: "sensores ciudadanos" },
  { key: "satellites", title: "Satélites", hint: "posición propagada ahora" },
];

const SEVERIDAD_ES: Record<string, string> = {
  critical: "crítica",
  high: "alta",
  medium: "media",
  orange: "alta",
  low: "baja",
  info: "informativa",
  yellow: "media",
  green: "baja",
  red: "crítica",
};

/** Número con coma decimal, como se escribe en español. */
function km(v: number | string | undefined): string {
  if (v === undefined || v === null) return "";
  const n = typeof v === "string" ? Number(v) : v;
  if (!Number.isFinite(n)) return String(v);
  return n.toLocaleString("es-ES", { maximumFractionDigits: 1 });
}

function metaDe(key: keyof PlaceData["counts"], row: PlaceRow): string {
  if (key === "events" || key === "traffic") {
    return [
      categoryMeta(row.category ?? "").label,
      row.severity ? `gravedad ${SEVERIDAD_ES[row.severity] ?? row.severity}` : "",
      row.sub,
    ]
      .filter(Boolean)
      .join(" · ");
  }
  return [row.sub, row.distance_km !== undefined ? `${km(row.distance_km)} km` : ""].filter(Boolean).join(" · ");
}

function fmtCoord(v: number, kind: "lat" | "lon") {
  const hemi = kind === "lat" ? (v >= 0 ? "N" : "S") : v >= 0 ? "E" : "O";
  return `${Math.abs(v).toFixed(4)}° ${hemi}`;
}

export default function PlacePanel(p: Props) {
  const d = p.data;

  if (!p.place) {
    return (
      <div className="place-start">
        <div className="place-start-mark" aria-hidden="true"><Icon name="pin" size={25} /></div>
        <span className="place-start-eyebrow">Exploración territorial</span>
        <h2>Elige un lugar para empezar</h2>
        <p>Pulsa el mapa para ver los sucesos y elementos cercanos, con sus fuentes y coordenadas.</p>
        <div className="place-start-actions">
          <button className="btn primary" onClick={p.onExploreThreats}><Icon name="warning" size={15} /> Ver amenazas</button>
          <button className="btn" onClick={p.onExploreSources}><Icon name="sources" size={15} /> Revisar fuentes</button>
        </div>
        <div className="place-start-tip">También puedes buscar un país o una fuente en la barra superior.</div>
      </div>
    );
  }

  const rowsFor = (key: keyof PlaceData["counts"]): PlaceRow[] =>
    (d?.[key] as PlaceRow[] | undefined) ?? [];

  const pick = (key: keyof PlaceData["counts"], row: PlaceRow) => {
    if (key === "events" || key === "traffic") p.onPickEvent(row.id);
    else if (key === "cameras") p.onPickCamera(row.id);
    else p.onPickActor(key as ActorKind, row.id);
  };

  const title = p.place.name || d?.place?.name || "Punto del mapa";
  const subtitle = [
    d?.country?.name,
    d?.country?.continent,
    d?.place?.region,
    d?.place && d.place.distance_km > 0.6
      ? `${d.place.name} a ${km(d.place.distance_km)} km`
      : null,
  ]
    .filter(Boolean)
    .join(" · ") || "Localizando el entorno del punto…";
  const firstWithData = d ? SECTIONS.find((s) => (d.counts[s.key] ?? 0) > 0)?.key : undefined;
  const emptyLayers = d
    ? SECTIONS.filter((s) => s.key !== "cameras" && (d.counts[s.key] ?? 0) === 0).map((s) => s.title.toLowerCase())
    : [];
  const totalCount = d ? Object.values(d.counts).reduce((sum, n) => sum + (n ?? 0), 0) : 0;

  return (
    <div data-actualizado={d?.fetched_at ?? 0} data-radio={p.radiusKm}>
      <PanelHeader
        icon="pin"
        eyebrow="Ficha de lugar"
        title={title}
        subtitle={subtitle}
        meta={
          <>
            <span>{fmtCoord(p.place.lat, "lat")} · {fmtCoord(p.place.lon, "lon")}</span>
            <span className="mono">{p.place.lat.toFixed(3)}, {p.place.lon.toFixed(3)}</span>
            {d ? <span>actualizado hace {timeAgo(new Date(d.fetched_at).toISOString())}</span> : null}
          </>
        }
        actions={
          <button className="btn ghost" onClick={p.onClear} title="Cerrar la ficha del lugar" aria-label="Cerrar la ficha del lugar">
            <Icon name="close" size={15} />
          </button>
        }
      />

      {d ? (
        <SummaryStrip
          items={[
            { label: "Sucesos", value: d.counts.events, hint: `Sucesos guardados en ${p.radiusKm} km` },
            { label: "Tráfico", value: d.counts.traffic, tone: "var(--signal)", hint: "Incidencias DGT en vivo" },
            { label: "Aeronaves", value: d.counts.aircraft, hint: "Aeronaves ADS-B ahora" },
            { label: "Buques", value: d.counts.vessels, hint: "Buques AIS ahora" },
            { label: "Trenes", value: d.counts.trains, hint: "Trenes en vivo" },
            { label: "Cámaras", value: d.counts.cameras, hint: "Cámaras públicas con imagen" },
            { label: "Satélites", value: d.counts.satellites, hint: "Satélites propagados" },
            { label: "Aire", value: d.counts.air, hint: "Sensores de calidad del aire" },
          ]}
        />
      ) : null}

      <div className="pn-tools">
        <div className="pn-tool-row">
          <button className="btn primary" onClick={p.onCenter} title="Centrar el mapa en este punto">
            <Icon name="locate" size={15} /> Centrar aquí
          </button>
          <button className="btn" onClick={p.onRefresh} title="Volver a consultar ahora">
            {p.loading ? <span className="spinner" /> : <Icon name="refresh" size={15} />} Actualizar
          </button>
        </div>

        <div className="pn-tool-row" role="group" aria-label="Radio de búsqueda">
          <span className="tiny faint">Radio</span>
          {RADII.map((radius) => (
            <button
              key={radius}
              className={`chip ${p.radiusKm === radius ? "active" : ""}`}
              onClick={() => p.onRadius(radius)}
              title={`Buscar en ${radius} km a la redonda`}
            >
              {radius} km
            </button>
          ))}
        </div>

        <div className="pn-tool-row" role="group" aria-label="Ventana de tiempo de los eventos">
          <span className="tiny faint">Sucesos de</span>
          {[24, 168, 720].map((h) => (
            <button
              key={h}
              className={`chip ${p.windowHours === h ? "active" : ""}`}
              onClick={() => p.onWindow(h)}
              title={h === 24 ? "Últimas 24 horas" : h === 168 ? "Última semana (por defecto)" : "Últimos 30 días"}
            >
              {h === 24 ? "24 h" : h === 168 ? "7 días" : "30 días"}
            </button>
          ))}
        </div>
      </div>

      {d?.summary ? <p className="pn-lede">{d.summary}</p> : null}

      {d && totalCount === 0 && (
        <p className="pn-lede">
          No hay elementos de las capas activas en este radio. Amplía el radio o elige otro punto del mapa.
        </p>
      )}

      {p.loading && !d && (
        <div className="pn-tools">
          <div className="source-row" style={{ padding: 0 }}>
            <span className="spinner" />
            <span className="source-name tiny">Consultando el entorno del punto…</span>
          </div>
        </div>
      )}

      {d && totalCount > 0 &&
        SECTIONS.filter((s) => (d.counts[s.key] ?? 0) > 0 || s.key === "cameras").map((s) => {
          const rows = rowsFor(s.key);
          const n = d.counts[s.key];
          return (
            <PanelSection
              key={s.key}
              title={s.title}
              count={n}
              hint={s.hint}
              defaultOpen={s.key === firstWithData}
            >
              <div className="tiny faint" style={{ marginBottom: rows.length ? 6 : 0 }}>{s.hint}</div>
              {rows.length === 0 && s.key === "cameras" && (
                <div className="cov-note">
                  No hay cámaras públicas con imagen abierta en {p.radiusKm} km. Solo cinco redes
                  publican sin clave (País Vasco, Londres, California, Nueva York y Finlandia): fuera
                  de ellas no existen cámaras accesibles y no se simulan.
                </div>
              )}
              {rows.length === 0 && s.key !== "cameras" && (
                <div className="tiny faint">Nada de esta capa en {p.radiusKm} km a la redonda.</div>
              )}
              {rows.map((row) => (
                <div
                  className="event-row"
                  key={`${s.key}-${row.id}`}
                  onClick={() => pick(s.key, row)}
                  role="button"
                  tabIndex={0}
                  onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") pick(s.key, row); }}
                  title="Abrir la ficha completa"
                >
                  <span className={`place-dot place-dot-${s.key}`} />
                  <div className="event-main">
                    <div className="event-title">{row.title || row.id}</div>
                    {metaDe(s.key, row) && <div className="event-sub">{metaDe(s.key, row)}</div>}
                    {row.summary && s.key === "events" && (
                      <div className="event-summary">{eventSummary(row)}</div>
                    )}
                  </div>
                  <span className="tiny faint">›</span>
                </div>
              ))}
              {n > rows.length && (
                <div className="tiny faint" style={{ marginTop: 4 }}>
                  {n - rows.length} más sin listar: reduce el radio para verlos todos.
                </div>
              )}
            </PanelSection>
          );
        })}

      {d && totalCount > 0 && emptyLayers.length > 0 && (
        <div className="pn-note" style={{ padding: "10px 14px" }}>
          Sin datos en este radio: {emptyLayers.join(", ")}.
        </div>
      )}
    </div>
  );
}
