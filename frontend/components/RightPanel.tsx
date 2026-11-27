"use client";

import { useEffect, useMemo, useState } from "react";
import type {
  ActorDetail, ActorKind, Alert, AppConfig, Briefing, EventFeature, Health, NearbyHit, SourceStatus,
} from "@/lib/types";
import ActorCard from "@/components/ActorCard";
import CameraView from "@/components/CameraView";
import PlacePanel, { type PlaceData } from "@/components/PlacePanel";
import {
  CATEGORY_DESC, categoryMeta, esError, fechaExacta, fmtDistance, fmtNumber, markdownToHtml,
  SEVERITY_COLOR as severityColor, sourceEs, timeAgo,
} from "@/lib/format";

export type Tab = "actor" | "camera" | "detail" | "place" | "briefing" | "threats" | "alerts" | "sources";

type Props = {
  open?: boolean;
  onClose?: () => void;
  tab: Tab;
  setTab: (t: Tab) => void;
  selected: EventFeature | null;
  onClearSelection: () => void;
  detail: { event: any; mentions: any[] } | null;
  detailLoading: boolean;
  nearby: { count: number; population_exposed: number; hits: NearbyHit[]; query: string } | null;
  nearbyLoading: boolean;
  nearbyRadiusKn: number;
  setNearbyRadiusKm: (v: number) => void;
  onGenerateBriefing: () => void;
  briefing: Briefing | null;
  briefingLoading: boolean;
  onSelectById: (id: string) => void;
  onDownloadBriefing: () => void;
  alerts: Alert[];
  alertsCount: number;
  health: Health | null;
  config: AppConfig | null;
  onTriggerSource: (name: string) => void;
  onBreakdownSource: (src: SourceStatus) => void;
  triggering: string | null;
  /* elemento móvil seleccionado */
  actorKind: ActorKind | null;
  actorDetail: ActorDetail | null;
  actorLoading: boolean;
  /* cámara pública seleccionada */
  cameraId: string | null;
  onClearCamera: () => void;
  onFlyTo: (lat: number, lon: number) => void;
  actorFollow: boolean;
  onToggleFollow: () => void;
  onRecenterActor: () => void;
  onClearActor: () => void;
  /* ficha del lugar pinchado */
  place: { lat: number; lon: number; name?: string } | null;
  placeData: PlaceData | null;
  placeLoading: boolean;
  placeRadiusKm: number;
  placeWindowH: number;
  onPlaceWindow: (h: number) => void;
  onPlaceRadius: (km: number) => void;
  onPlaceRefresh: () => void;
  onPlaceClean: () => void;
  onPlaceCenter: () => void;
  onPickPlaceEvent: (id: string) => void;
  onPickPlaceCamera: (id: string) => void;
  onPickPlaceActor: (kind: ActorKind, id: string) => void;
  onPickThreat: (id: string) => void;
  threatHours: number;
  onThreatWindow: (h: number) => void;
};

const TABS: { key: Tab; label: string; icon: string; hint: string }[] = [
  { key: "place", label: "Lugar", icon: "◎", hint: "Todo lo que hay alrededor del punto que has pulsado" },
  { key: "threats", label: "Amenazas", icon: "⚠", hint: "Sucesos que amenazan a la población o generan alarma, ordenados por prioridad" },
  { key: "detail", label: "Suceso", icon: "◆", hint: "Ficha completa del suceso seleccionado" },
  { key: "actor", label: "Elemento", icon: "✈", hint: "Avión, barco o satélite seleccionado" },
  { key: "camera", label: "Cámara", icon: "▣", hint: "Visor de la cámara pública seleccionada" },
  { key: "briefing", label: "Informe", icon: "▤", hint: "Informe redactado con los datos de la zona" },
  { key: "alerts", label: "Alertas", icon: "✦", hint: "Avisos de las zonas vigiladas" },
  { key: "sources", label: "Fuentes", icon: "⇄", hint: "Estado y detalle de las 25 fuentes abiertas" },
];

export default function RightPanel(p: Props) {
  const [onlyCritical, setOnlyCritical] = useState(false);

  const filteredAlerts = useMemo(
    () => (onlyCritical ? p.alerts.filter((a) => a.severity === "critical" || a.event_type === "rule") : p.alerts),
    [p.alerts, onlyCritical]
  );

  return (
    <aside className={`panel right ${p.open ? "open" : ""}`}>
      <button className="sheet-grip" onClick={() => p.onClose?.()} aria-label="Cerrar panel" />
      <div className="tabs">
        {TABS.map((t) => (
          <button
            key={t.key}
            className={`tab ${p.tab === t.key ? "active" : ""}`}
            onClick={() => p.setTab(t.key)}
            title={t.hint}
          >
            <span className="tab-ico" aria-hidden="true">{t.icon}</span>
            {t.label}
            {t.key === "alerts" && p.alertsCount > 0 && <span className="tab-badge">{p.alertsCount > 99 ? "99+" : p.alertsCount}</span>}
          </button>
        ))}
        <button className="panel-close" onClick={() => p.onClose?.()} aria-label="Cerrar" style={{ marginLeft: "auto" }}>✕</button>
      </div>

      <div className="panel-body">
        {p.tab === "actor" && (
          <ActorCard
            kind={p.actorKind ?? "aircraft"}
            detail={p.actorDetail}
            loading={p.actorLoading}
            follow={p.actorFollow}
            onToggleFollow={p.onToggleFollow}
            onRecenter={p.onRecenterActor}
            onClear={p.onClearActor}
          />
        )}

        {p.tab === "camera" && (
          p.cameraId
            ? <CameraView cameraId={p.cameraId} onClose={p.onClearCamera} onFly={p.onFlyTo} />
            : <div className="empty">
                <span className="empty-ico" aria-hidden="true">▣</span>
                <strong>Ninguna cámara seleccionada</strong>
                Pulsa un punto violeta del mapa (capa «Cámaras de tráfico») y aquí verás su imagen
                en directo, el nombre de la vía y la hora de la última instantánea.
                <div className="cov-note" style={{ textAlign: "left", marginTop: 12 }}>
                  Cobertura actual: País Vasco, Londres, California, Nueva York y Finlandia. Son las
                  redes que publican imagen sin clave; en España solo el Gobierno Vasco lo hace.
                </div>
              </div>
        )}

        {p.tab === "detail" && <EventDetail {...p} />}

        {p.tab === "place" && (
          <PlacePanel
            place={p.place}
            data={p.placeData}
            loading={p.placeLoading}
            radiusKm={p.placeRadiusKm}
            onRadius={p.onPlaceRadius}
            windowHours={p.placeWindowH}
            onWindow={p.onPlaceWindow}
            onRefresh={p.onPlaceRefresh}
            onClear={p.onPlaceClean}
            onCenter={p.onPlaceCenter}
            onPickEvent={p.onPickPlaceEvent}
            onPickCamera={p.onPickPlaceCamera}
            onPickActor={p.onPickPlaceActor}
          />
        )}

        {p.tab === "briefing" && (
          <div>
            <div className="section" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <div>
                <div className="section-title" style={{ marginBottom: 3 }}>Informe de situación</div>
                <div className="tiny faint">
                  {p.briefing
                    ? `${p.briefing.event_count} eventos · ${p.briefing.provider} · ${timeAgo(p.briefing.generated_at)}`
                    : "RAG sobre la ventana actual del mapa"}
                </div>
              </div>
              <div className="btn-row">
                <button className="btn primary" onClick={p.onGenerateBriefing} disabled={p.briefingLoading}>
                  {p.briefingLoading ? <span className="spinner" /> : "▶"} Generar
                </button>
                {p.briefing && (
                  <button className="btn" onClick={p.onDownloadBriefing} title="Exportar markdown">
                    ↓ .md
                  </button>
                )}
              </div>
            </div>

            {p.config?.ai && (
              <div className="section" style={{ paddingTop: 8, paddingBottom: 8 }}>
                <div className="source-row" style={{ padding: 0 }}>
                  <span className={`status-dot ${p.config.ai.available ? "ok" : "warn"}`} />
                  <span className="source-name mono tiny">{p.config.ai.provider} / {p.config.ai.model}</span>
                  <span className="source-meta">{p.config.ai.available ? "listo" : "fallback"}</span>
                </div>
                <div className="tiny faint" style={{ marginTop: 4 }}>{p.config.ai.detail}</div>
              </div>
            )}

            {!p.briefing && !p.briefingLoading && (
              <div className="empty">
                <span className="empty-ico" aria-hidden="true">▤</span>
                <strong>Aún no hay informe</strong>
                Pulsa «Generar» y se redactará un informe con los sucesos de la zona visible:
                resumen, hechos principales, patrón detectado y qué falta por vigilar. Cada frase
                lleva la referencia al suceso que la respalda.
              </div>
            )}

            {p.briefing && (
              <div
                className="briefing"
                onClick={(e) => {
                  const target = e.target as HTMLElement;
                  const ref = target.getAttribute?.("data-ref");
                  if (!ref) return;
                  const cite = p.briefing?.citations.find((c) => c.ref === ref);
                  if (cite) p.onSelectById(cite.id);
                }}
                dangerouslySetInnerHTML={{ __html: markdownToHtml(p.briefing.markdown) }}
              />
            )}

            {p.briefing && p.briefing.citations.length > 0 && (
              <div className="section" style={{ borderTop: "1px solid var(--border)" }}>
                <div className="section-title">Fuentes citadas</div>
                {p.briefing.citations.slice(0, 12).map((c) => (
                  <div className="event-row" key={c.id} onClick={() => p.onSelectById(c.id)}>
                    <span className="event-dot" style={{ background: categoryMeta(c.category).color }} />
                    <div className="event-main">
                      <div className="event-title">
                        <span className="mono tiny faint">[{c.ref}]</span> {c.title}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {p.tab === "threats" && <ThreatsPanel onPick={p.onPickThreat} hourWindow={p.threatHours} onWindow={p.onThreatWindow} />}

        {p.tab === "alerts" && (
          <div>
            <div className="section" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <div className="section-title" style={{ marginBottom: 0 }}>
                Avisos de zonas vigiladas
              </div>
              <button className={`chip ${onlyCritical ? "active" : ""}`} onClick={() => setOnlyCritical(!onlyCritical)}>
                solo críticas
              </button>
            </div>
            <div className="section" style={{ paddingTop: 8 }}>
              {filteredAlerts.length === 0 && (
                <div className="empty">
                  <span className="empty-ico" aria-hidden="true">✦</span>
                  <strong>Todavía no hay avisos</strong>
                  Dibuja una zona vigilada en el panel de capas: en cuanto una aeronave, un buque o
                  un suceso entre o salga de ella, aparecerá aquí al instante.
                </div>
              )}
              {filteredAlerts.map((a, i) => (
                <div
                  key={`${a.ts}-${a.actor_id}-${i}`}
                  className={`alert-row ${a.severity === "critical" ? "critical" : a.event_type}`}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                    <span className="alert-title">{a.title}</span>
                    <span className="alert-time">{timeAgo(a.ts)}</span>
                  </div>
                  <div className="alert-msg">{a.message}</div>
                  <div className="alert-msg" style={{ color: "var(--text-faint)" }}>
                    {a.fence_name || (a.fence_id ?? "global")} · {a.actor_type} · {a.event_type}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {p.tab === "sources" && (
          <div>
            <div className="section">
              <div className="section-title">Estado de los pipelines</div>
              {(p.health?.ingest.sources ?? []).map((s) => (
                <div key={s.name} style={{ padding: "8px 0", borderBottom: "1px solid var(--border)" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <span className={`status-dot ${s.ok ? "ok" : "err"}`} />
                    <span style={{ fontWeight: 600, fontSize: 12 }}>{s.source ?? s.name}</span>
                    <span className="mono tiny faint" style={{ marginLeft: "auto" }}>{s.interval_s}s</span>
                    <button
                      className="chip"
                      onClick={() => p.onTriggerSource(s.name)}
                      disabled={p.triggering === s.name}
                    >
                      {p.triggering === s.name ? <span className="spinner" /> : "ejecutar"}
                    </button>
                  </div>
                  <div className="tiny faint" style={{ marginTop: 3 }}>{s.description}</div>
                  <div className="source-msg" style={{ marginTop: 3 }}>
                    <button
                      className="num-link"
                      title={`Ver los ${s.items} elementos de ${s.source ?? s.name}`}
                      onClick={() => p.onBreakdownSource(s)}
                    >
                      {fmtNumber(s.items)} elem.
                    </button>{" "}
                    · {s.duration_ms} ms · {s.failures} fallos ·{" "}
                    {s.last_run ? `hace ${timeAgo(s.last_run)}` : "pendiente"}
                  </div>
                  <div className="source-msg" style={{ color: s.ok ? "var(--text-faint)" : "var(--danger)" }}>
                    {esError(s.message)}
                  </div>
                  {s.key_optional && (
                    <div className="tiny faint" style={{ marginTop: 3 }}>
                      sin clave: {s.mode ?? "csv-global"} · MAP_KEY opcional para recorte por área
                    </div>
                  )}
                </div>
              ))}
            </div>

            <div className="section">
              <div className="section-title">Motor y almacenamiento</div>
              <dl className="kv">
                <dt>Storage</dt><dd>{p.health?.storage.backend}</dd>
                <dt>Eventos</dt><dd>{fmtNumber(p.health?.storage.events)}</dd>
                <dt>24h</dt><dd>{fmtNumber(p.health?.storage.events_24h)}</dd>
                <dt>Menciones</dt><dd>{fmtNumber(p.health?.storage.mentions)}</dd>
                <dt>Multi-fuente</dt><dd>{fmtNumber(p.health?.storage.multi_source_events)}</dd>
                <dt>Infra</dt><dd>{fmtNumber(p.health?.storage.infrastructure)} puntos</dd>
                <dt>Zonas vigiladas</dt><dd>{p.health?.fence.engine} · {p.health?.fence.fences} activas</dd>
                <dt>Objetos</dt><dd>{fmtNumber(p.health?.fence.tracked_objects)} rastreados</dd>
                <dt>Uptime</dt><dd>{p.health ? `${Math.round(p.health.ingest.uptime_s / 60)} min` : "—"}</dd>
              </dl>
            </div>

            <div className="section">
              <div className="section-title">Alertas por tipo</div>
              <dl className="kv">
                {Object.entries(p.health?.fence.counters ?? {}).map(([k, v]) => (
                  <div key={k} style={{ display: "contents" }}>
                    <dt>{k}</dt><dd>{v}</dd>
                  </div>
                ))}
              </dl>
            </div>
          </div>
        )}
      </div>
    </aside>
  );
}

/* ------------------------------------------------------------------ detail */
/** `sources` puede llegar como array, como texto JSON o como lista separada. */
function toList(value: any, fallback?: string): string[] {
  if (Array.isArray(value)) return value.map(String);
  if (typeof value === "string" && value.trim()) {
    try {
      const parsed = JSON.parse(value);
      if (Array.isArray(parsed)) return parsed.map(String);
    } catch { /* no era JSON */ }
    return value.replace(/[\[\]"']/g, "").split(",").map((s) => s.trim()).filter(Boolean);
  }
  return fallback ? [fallback] : [];
}

function EventDetail(p: Props) {
  if (!p.selected) {
    return (
      <div className="empty">
        <span className="empty-ico" aria-hidden="true">◆</span>
        <strong>Ningún suceso seleccionado</strong>
        Pulsa un punto del mapa (o cualquier fila de una lista) y aquí aparecerá su ficha: qué ha
        pasado, dónde, cuándo, con qué gravedad y qué fuentes lo confirman.
      </div>
    );
  }
  const ev = p.detail?.event ?? p.selected.properties;
  const sourceList = toList(ev.sources, ev.source);
  const payload = (() => {
    const raw = ev.payload;
    if (!raw) return null;
    if (typeof raw === "string") {
      try { return JSON.parse(raw); } catch { return null; }
    }
    return typeof raw === "object" ? raw : null;
  })();
  const meta = categoryMeta(ev.category);
  const severityKey = String(ev.severity_label ?? "").toLowerCase();
  const severityColorHex = severityColor[severityKey] ?? meta.color;
  const severityText: string = ev.severity_text ?? ev.severity_label ?? "";
  const when = fechaExacta(ev.event_time);
  const country = ev.country_es ?? ev.country ?? "";

  return (
    <div>
      <div className="detail">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "start", gap: 8 }}>
          <div className="detail-meta" style={{ marginBottom: 6 }}>
            <span className="badge solid" style={{ background: meta.color }}>{meta.icon} {meta.label}</span>
            {severityText && (
              <span className="badge" style={{ color: severityColorHex, borderColor: severityColorHex }}>
                Gravedad {severityText}
              </span>
            )}
            <span className="badge">{sourceEs(ev.source)}</span>
          </div>
          <button className="faint detail-close" onClick={p.onClearSelection} title="Cerrar la ficha">✕</button>
        </div>

        <h2 className="detail-title">{ev.title}</h2>

        <div className="tiny faint" style={{ marginBottom: 11, lineHeight: 1.6 }}>
          {when.local} · hace {timeAgo(ev.event_time)}
          <br />
          {sourceList.length > 1
            ? `Confirmado por ${sourceList.length} fuentes`
            : "Una sola fuente"} · {ev.mentions ?? 1} menciones
        </div>

        <EventPhoto eventId={String(ev.id ?? "")} />

        {ev.summary && (
          <p style={{ fontSize: 12.5, lineHeight: 1.6, color: "var(--text-dim)", marginTop: 0, marginBottom: 13 }}>
            {ev.summary}
          </p>
        )}

        <div className="card">
          <div className="card-title"><span>Datos del suceso</span></div>
          <dl className="kv">
            <dt>País / región</dt><dd>{country || "sin datos"}</dd>
            <dt>Coordenadas</dt><dd>{Number(ev.lat).toFixed(4)}, {Number(ev.lon).toFixed(4)}</dd>
            <dt>Hora local</dt><dd>{when.local}</dd>
            <dt>Hora UTC</dt><dd>{when.utc}</dd>
            <dt>Categoría</dt><dd>{meta.label}{ev.subtype ? ` · ${ev.subtype}` : ""}</dd>
            {ev.severity != null && (
              <><dt>Valor de gravedad</dt><dd>{Number(ev.severity).toLocaleString("es-ES")}</dd></>
            )}
            {ev.depth_km != null && (
              <><dt>Profundidad</dt><dd>{Number(ev.depth_km).toLocaleString("es-ES", { maximumFractionDigits: 1 })} km</dd></>
            )}
            <dt>Confianza</dt><dd>{Math.round((ev.confidence ?? 0) * 100)} %</dd>
            <dt>Fuentes</dt><dd>{sourceList.map(sourceEs).join(" · ") || sourceEs(ev.source)}</dd>
            <dt>Identificador</dt><dd style={{ fontSize: 9.5 }}>{ev.id}</dd>
          </dl>
        </div>

        <div className="card">
          <div className="card-title"><span>Cómo interpretarlo</span></div>
          <p style={{ margin: 0, fontSize: 11.5, lineHeight: 1.6, color: "var(--text-dim)" }}>
            {CATEGORY_DESC[ev.category] ?? "Suceso consolidado a partir de varias fuentes abiertas."}
          </p>
          {severityText && (
            <p style={{ margin: "8px 0 0", fontSize: 11.5, lineHeight: 1.6, color: "var(--text-dim)" }}>
              <b style={{ color: severityColorHex }}>Gravedad {severityText}</b>: se calcula con la
              magnitud del fenómeno y el número de fuentes que lo confirman; «crítica» implica riesgo
              inmediato para la población.
            </p>
          )}
        </div>

        <div className="btn-row" style={{ marginBottom: 12 }}>
          <button className="btn primary" onClick={p.onGenerateBriefing} disabled={p.briefingLoading}>
            {p.briefingLoading ? <span className="spinner" /> : "◈"} Informe de la zona
          </button>
          {ev.url && (
            <a className="btn" href={ev.url} target="_blank" rel="noreferrer">↗ Abrir la fuente</a>
          )}
        </div>
      </div>

      {/* corroboración */}
      {p.detail?.mentions && p.detail.mentions.length > 0 && (
        <div className="section">
          <div className="section-title">
            <span>Menciones fusionadas</span>
            <span className="st-count">{p.detail.mentions.length}</span>
          </div>
          <div className="tiny faint" style={{ marginBottom: 7 }}>
            Noticias y avisos que se han unido en este único suceso (misma zona y misma hora).
          </div>
          {p.detail.mentions.slice(0, 8).map((m: any, i: number) => (
            <div key={i} style={{ padding: "5px 0", borderTop: i ? "1px solid var(--border-soft)" : "none" }}>
              <div style={{ fontSize: 11.5, lineHeight: 1.38 }}>{m.title}</div>
              <div className="mono tiny faint">
                {sourceEs(m.source)} · coincidencia {Math.round(Number(m.score) * 100)} % · hace {timeAgo(m.seen_at)}
                {m.url && <> · <a href={m.url} target="_blank" rel="noreferrer">abrir</a></>}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* proximidad */}
      <div className="section">
        <div className="section-title">
          <span>Población e infraestructura cerca</span>
          <span className="st-count">{p.nearbyRadiusKn} km</span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
          <span className="tiny faint mono">RADIO</span>
          <input
            type="range" min={10} max={1000} step={10} value={p.nearbyRadiusKn}
            onChange={(e) => p.setNearbyRadiusKm(Number(e.target.value))}
            style={{ flex: 1, accentColor: "#38e0cd" }}
            aria-label="Radio de búsqueda en kilómetros"
          />
          <span className="mono tiny nowrap" style={{ width: 54, textAlign: "right" }}>{p.nearbyRadiusKn} km</span>
        </div>
        {p.nearbyLoading && (
          <div className="tiny faint"><span className="spinner" /> buscando núcleos urbanos cercanos…</div>
        )}
        {p.nearby && !p.nearbyLoading && (
          <>
            <div className="tiny faint" style={{ marginBottom: 6 }}>
              <b style={{ color: "var(--text)" }}>{p.nearby.count}</b> núcleos ·{" "}
              <b style={{ color: "var(--text)" }}>{fmtNumber(p.nearby.population_exposed)}</b> habitantes en el radio
            </div>
            {p.nearby.hits.slice(0, 18).map((h) => (
              <div key={h.id} style={{ display: "flex", gap: 8, padding: "3.5px 0", fontSize: 11.5 }}>
                <span className="mono tiny faint" style={{ width: 64, flex: "0 0 auto" }}>{fmtDistance(h.distance_m)}</span>
                <span style={{ flex: 1 }}>{h.name}</span>
                <span className="mono tiny faint">{fmtNumber(h.population)}</span>
              </div>
            ))}
          </>
        )}
      </div>

      {payload && Object.keys(payload).length > 0 && (
        <div className="section">
          <div className="section-title"><span>Datos originales de la fuente</span></div>
          <pre
            className="mono code-block"
            style={{ fontSize: 9.5, maxHeight: 220, overflow: "auto" }}
          >
            {JSON.stringify(
              Object.fromEntries(Object.entries(payload).filter(([k]) => k !== "corroboration")),
              null,
              1
            )}
          </pre>
        </div>
      )}
    </div>
  );
}

/* ---------------------------------------------------------------------------
   Imagen real del suceso: la escena de satélite que vio el foco, la foto
   oficial de NASA/JRC o la imagen que publicó el medio que informó.
--------------------------------------------------------------------------- */
function EventPhoto({ eventId }: { eventId: string }) {
  const [photo, setPhoto] = useState<{ url: string; proxy?: string; credit: string; link: string; source: string; note?: string } | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!eventId) { setPhoto(null); return; }
    let alive = true;
    setLoading(true);
    fetch(`/api/events/${encodeURIComponent(eventId)}/photo`)
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => { if (alive) { setPhoto(d?.photo ?? null); setLoading(false); } })
      .catch(() => { if (alive) { setPhoto(null); setLoading(false); } });
    return () => { alive = false; };
  }, [eventId]);

  if (!photo) {
    return loading ? (
      <div className="tiny faint" style={{ marginBottom: 10 }}>buscando imagen del suceso…</div>
    ) : null;
  }
  return (
    <figure className="event-photo">
      <a href={photo.link || photo.url} target="_blank" rel="noreferrer">
        <img src={photo.proxy || photo.url} alt="Imagen del suceso" loading="lazy" referrerPolicy="no-referrer" />
      </a>
      <figcaption className="tiny faint">
        © {photo.credit}{photo.note ? ` · ${photo.note}` : ""}
      </figcaption>
    </figure>
  );
}

/* ---------------------------------------------------------------------------
   Amenazas: los sucesos que amenazan a la población o generan alarma social,
   ordenados por la puntuación que calcula el servidor (con su motivo).
   Se refresca sola cada 45 s: es una lista pensada para un centro de crisis.
--------------------------------------------------------------------------- */
type ThreatItem = {
  id: string;
  title: string;
  category: string;
  country?: string;
  summary?: string;
  event_time: string;
  sources_count?: number;
  priority: { score: number; level: string; reasons: string[]; population_threat: boolean };
};

function ThreatsPanel({ onPick, hourWindow, onWindow }: { onPick: (id: string) => void; hourWindow: number; onWindow: (h: number) => void }) {
  const [items, setItems] = useState<ThreatItem[]>([]);
  const [meta, setMeta] = useState<{ count: number; considered: number; levels: Record<string, number> } | null>(null);
  const [loading, setLoading] = useState(false);
  const [minScore, setMinScore] = useState(5.5);

  useEffect(() => {
    let alive = true;
    const cargar = () => {
      setLoading(true);
      fetch(`/api/events/priority?hours=${hourWindow}&min_score=${minScore}&limit=250`)
        .then((r) => (r.ok ? r.json() : null))
        .then((d) => {
          if (!alive || !d) return;
          setItems(d.events || []);
          setMeta({ count: d.count, considered: d.considered, levels: d.levels || {} });
          setLoading(false);
        })
        .catch(() => { if (alive) setLoading(false); });
    };
    cargar();
    const t = setInterval(cargar, 45000);
    return () => { alive = false; clearInterval(t); };
  }, [hourWindow, minScore]);

  const color = (s: number) => (s >= 7.5 ? "#ff3d71" : s >= 5.5 ? "#ff9f0a" : s >= 3.5 ? "#ffd60a" : "#8fa6c4");

  return (
    <div>
      <div className="section">
        <div className="section-title" style={{ marginBottom: 6 }}>
          Amenaza para la población {loading ? "· actualizando…" : ""}
        </div>
        <div className="tiny faint" style={{ lineHeight: 1.55, marginBottom: 8 }}>
          Sucesos con riesgo para las personas o de interés general, ordenados por prioridad.
          La puntuación combina categoría, gravedad, corroboración de fuentes y palabras de riesgo
          del propio titular, y se refresca cada 45 s.
        </div>
        <div className="place-window">
          <span className="tiny faint">Ventana</span>
          {[24, 168, 720].map((h) => (
            <button key={h} className={`chip ${hourWindow === h ? "active" : ""}`} onClick={() => onWindow(h)}>
              {h === 24 ? "24 h" : h === 168 ? "7 días" : "30 días"}
            </button>
          ))}
        </div>
        <div className="place-window">
          <span className="tiny faint">Desde</span>
          {[3.5, 5.5, 7.5].map((v) => (
            <button key={v} className={`chip ${minScore === v ? "active" : ""}`} onClick={() => setMinScore(v)}
              title={v === 7.5 ? "solo crítica" : v === 5.5 ? "alta o crítica" : "media o superior"}>
              {v === 7.5 ? "crítica" : v === 5.5 ? "alta" : "media"}
            </button>
          ))}
        </div>
        {meta && (
          <div className="tiny faint" style={{ marginTop: 8 }}>
            {meta.count} sucesos sobre {meta.considered} analizados · crítica {meta.levels["crítica"] ?? 0} · alta{" "}
            {meta.levels["alta"] ?? 0} · media {meta.levels["media"] ?? 0}
          </div>
        )}
      </div>
      <div className="section" style={{ paddingTop: 4 }}>
        {items.length === 0 && !loading && (
          <div className="empty">
            <span className="empty-ico" aria-hidden="true">⚠</span>
            <strong>Sin sucesos por encima de ese umbral</strong>
            Baja el nivel («media») o amplía la ventana temporal.
          </div>
        )}
        {items.map((it) => (
          <button
            key={it.id}
            className="threat-row"
            onClick={() => onPick(it.id)}
            title="Abrir la ficha del suceso"
          >
            <span className="threat-score" style={{ background: color(it.priority.score) }}>
              {it.priority.score.toFixed(1)}
            </span>
            <span className="threat-body">
              <span className="threat-title">{it.title}</span>
              <span className="threat-meta tiny faint">
                {it.priority.level} · {it.country || "sin país"} · {timeAgo(it.event_time)} ·{" "}
                {it.sources_count ?? 1} fuente{(it.sources_count ?? 1) > 1 ? "s" : ""}
                {it.priority.reasons?.length ? ` · ${it.priority.reasons.join(", ")}` : ""}
              </span>
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}
