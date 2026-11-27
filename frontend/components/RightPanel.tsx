"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type {
  ActorDetail, ActorKind, Alert, AppConfig, Briefing, EventFeature, Health, NearbyHit, SourceStatus,
} from "@/lib/types";
import ActorCard from "@/components/ActorCard";
import AnalystPanel from "@/components/AnalystPanel";
import CameraView from "@/components/CameraView";
import PlacePanel, { type PlaceData } from "@/components/PlacePanel";
import { PanelHeader, PanelSection, SummaryStrip } from "@/components/PanelUI";
import { Icon, type IconName } from "@/components/Icon";
import {
  CATEGORY_DESC, categoryMeta, esError, fechaExacta, fmtDistance, fmtNumber, markdownToHtml,
  SEVERITY_COLOR as severityColor, sourceEs, timeAgo,
} from "@/lib/format";
import { apiUrl } from "@/lib/api";

export type Tab = "actor" | "camera" | "detail" | "place" | "briefing" | "threats" | "alerts" | "sources" | "analyst";

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

const TABS: { key: Tab; label: string; icon: IconName; hint: string }[] = [
  { key: "place", label: "Lugar", icon: "pin", hint: "Todo lo que hay alrededor del punto que has pulsado" },
  { key: "threats", label: "Amenazas", icon: "warning", hint: "Sucesos que amenazan a la población o generan alarma, ordenados por prioridad" },
  { key: "detail", label: "Suceso", icon: "event", hint: "Ficha completa del suceso seleccionado" },
  { key: "actor", label: "Elemento", icon: "plane", hint: "Avión, barco o satélite seleccionado" },
  { key: "camera", label: "Cámara", icon: "camera", hint: "Visor de la cámara pública seleccionada" },
  { key: "briefing", label: "Informe", icon: "report", hint: "Informe redactado con los datos de la zona" },
  { key: "alerts", label: "Alertas", icon: "bell", hint: "Avisos de las zonas vigiladas" },
  { key: "sources", label: "Fuentes", icon: "sources", hint: "Estado y detalle de las 25 fuentes abiertas" },
  { key: "analyst", label: "Analista", icon: "analyst", hint: "SITREP, patrones, casos con cadena de custodia, grafo y reproducción" },
];

export default function RightPanel(p: Props) {
  const [onlyCritical, setOnlyCritical] = useState(false);
  const tabsRef = useRef<HTMLDivElement | null>(null);

  // El rail muestra la etiqueta solo en la pestaña activa: si está al final,
  // hay que llevarla a la vista o aparece cortada («ANALIST»).
  useEffect(() => {
    const rail = tabsRef.current;
    const active = rail?.querySelector<HTMLElement>(".tab.active");
    if (!rail || !active) return;
    const left = active.offsetLeft;
    const right = left + active.offsetWidth;
    // desplazamiento instantáneo: una animación aquí pelea con el clic y con
    // el propio scroll táctil del rail
    if (left < rail.scrollLeft) rail.scrollLeft = left - 8;
    else if (right > rail.scrollLeft + rail.clientWidth) {
      rail.scrollLeft = right - rail.clientWidth + 8;
    }
  }, [p.tab]);

  const filteredAlerts = useMemo(
    () => (onlyCritical ? p.alerts.filter((a) => a.severity === "critical" || a.event_type === "rule") : p.alerts),
    [p.alerts, onlyCritical]
  );

  const criticalAlerts = p.alerts.filter((a) => a.severity === "critical").length;
  const ruleAlerts = p.alerts.filter((a) => a.event_type === "rule").length;

  const sourceList = p.health?.ingest.sources ?? [];
  const failingSources = sourceList.filter((s) => !s.ok);
  const healthySources = sourceList.filter((s) => s.ok);
  const sourceItems = sourceList.reduce((sum, s) => sum + (s.items ?? 0), 0);
  const sourceAvgMs = sourceList.length
    ? Math.round(sourceList.reduce((sum, s) => sum + (s.duration_ms ?? 0), 0) / sourceList.length)
    : 0;
  const sourceLatency = sourceAvgMs >= 1000 ? `${(sourceAvgMs / 1000).toFixed(1)} s` : `${sourceAvgMs} ms`;

  const renderSource = (s: SourceStatus) => (
    <div key={s.name} style={{ padding: "9px 0", borderBottom: "1px solid var(--line-soft)" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span className={`status-dot ${s.ok ? "ok" : "err"}`} />
        <span style={{ fontWeight: 600, fontSize: 12 }}>{s.source ?? s.name}</span>
        <span className="mono tiny faint" style={{ marginLeft: "auto" }}>{s.interval_s}s</span>
        <button
          className="chip"
          onClick={() => p.onTriggerSource(s.name)}
          disabled={p.triggering === s.name}
          title="Ejecutar esta fuente ahora"
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
  );

  return (
    <aside className={`panel right ${p.open ? "open" : ""}`}>
      <button className="sheet-grip" onClick={() => p.onClose?.()} aria-label="Cerrar panel" />
      <div className="tabs" ref={tabsRef}>
        {TABS.map((t) => (
          <button
            key={t.key}
            className={`tab ${p.tab === t.key ? "active" : ""}`}
            onClick={() => p.setTab(t.key)}
            title={`${t.label} · ${t.hint}`}
            aria-label={t.label}
            aria-current={p.tab === t.key ? "page" : undefined}
          >
            <span className="tab-ico" aria-hidden="true"><Icon name={t.icon} size={16} /></span>
            {/* rail de iconos: la etiqueta solo se despliega en la pestaña activa,
                así nueve secciones caben sin scroll en un panel de 404 px */}
            <span className="tab-label">{t.label}</span>
            {t.key === "alerts" && p.alertsCount > 0 && <span className="tab-badge">{p.alertsCount > 99 ? "99+" : p.alertsCount}</span>}
          </button>
        ))}
        <button className="panel-close" onClick={() => p.onClose?.()} aria-label="Cerrar" style={{ marginLeft: "auto" }}><Icon name="close" size={16} /></button>
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
                <span className="empty-ico" aria-hidden="true"><Icon name="camera" size={30} /></span>
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

        {p.tab === "analyst" && (
          <AnalystPanel
            selectedEventId={p.detail?.event?.id ?? p.selected?.properties?.id ?? null}
            selectedTitle={p.detail?.event?.title ?? p.selected?.properties?.title ?? null}
          />
        )}

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
            onExploreThreats={() => p.setTab("threats")}
            onExploreSources={() => p.setTab("sources")}
          />
        )}

        {p.tab === "briefing" && (
          <div>
            <PanelHeader
              icon="report"
              eyebrow="Informe"
              title="Informe de situación"
              subtitle="Resumen redactado con los sucesos de la zona visible y la referencia de cada frase."
              meta={
                <>
                  {p.briefing ? <span>{p.briefing.event_count} eventos</span> : <span>RAG sobre la ventana actual</span>}
                  {p.briefing ? <span>{timeAgo(p.briefing.generated_at)}</span> : null}
                </>
              }
              actions={
                <div className="btn-row">
                  <button className="btn primary" onClick={p.onGenerateBriefing} disabled={p.briefingLoading}>
                    {p.briefingLoading ? <span className="spinner" /> : "▶"} Generar
                  </button>
                  {p.briefing && (
                    <button className="btn" onClick={p.onDownloadBriefing} title="Exportar markdown">
                      <Icon name="download" size={15} /> .md
                    </button>
                  )}
                </div>
              }
            />

            {p.briefing && (
              <SummaryStrip
                items={[
                  { label: "Eventos", value: p.briefing.event_count, hint: "Sucesos incluidos en el informe" },
                  { label: "Fuentes citadas", value: p.briefing.citations.length, hint: "Referencias verificables" },
                  { label: "Proveedor", value: p.briefing.provider, hint: "Modelo que redactó el informe" },
                  { label: "Generado", value: timeAgo(p.briefing.generated_at), hint: "Hora de generación" },
                ]}
              />
            )}

            {p.config?.ai && (
              <PanelSection title="Modelo y proveedor" count={p.config.ai.available ? "listo" : "fallback"} hint={p.config.ai.provider}>
                <div className="source-row" style={{ padding: 0 }}>
                  <span className={`status-dot ${p.config.ai.available ? "ok" : "warn"}`} />
                  <span className="source-name mono tiny">{p.config.ai.provider} / {p.config.ai.model}</span>
                  <span className="source-meta">{p.config.ai.available ? "listo" : "fallback"}</span>
                </div>
                <div className="tiny faint" style={{ marginTop: 4 }}>{p.config.ai.detail}</div>
              </PanelSection>
            )}

            {!p.briefing && !p.briefingLoading && (
              <div className="empty">
                <span className="empty-ico" aria-hidden="true"><Icon name="report" size={30} /></span>
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
              <PanelSection
                title="Fuentes citadas"
                count={p.briefing.citations.length}
                hint="Cada referencia abre el suceso"
                defaultOpen
              >
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
              </PanelSection>
            )}
          </div>
        )}

        {p.tab === "threats" && <ThreatsPanel onPick={p.onPickThreat} hourWindow={p.threatHours} onWindow={p.onThreatWindow} />}

        {p.tab === "alerts" && (
          <div>
            <PanelHeader
              icon="bell"
              eyebrow="Zonas vigiladas"
              title="Avisos"
              subtitle="Entradas y salidas de aeronaves, buques o sucesos en las zonas que has dibujado."
              meta={<span>{p.alerts.length} avisos guardados</span>}
              actions={
                <button className={`chip ${onlyCritical ? "active" : ""}`} onClick={() => setOnlyCritical(!onlyCritical)}>
                  solo críticas
                </button>
              }
            />
            <SummaryStrip
              items={[
                { label: "Avisos", value: p.alerts.length, hint: "Total de avisos guardados" },
                { label: "Críticas", value: criticalAlerts, tone: criticalAlerts ? "var(--danger)" : undefined, hint: "Avisos de máxima prioridad" },
                { label: "Reglas", value: ruleAlerts, hint: "Avisos generados por una regla" },
                { label: "Visibles", value: filteredAlerts.length, hint: "Avisos visibles con el filtro actual" },
              ]}
            />
            <div className="pn-tools" style={{ paddingTop: 8, paddingBottom: 4 }}>
              {filteredAlerts.length === 0 && (
                <div className="empty">
                  <span className="empty-ico" aria-hidden="true"><Icon name="bell" size={30} /></span>
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
            <PanelHeader
              icon="sources"
              eyebrow="Fuentes abiertas"
              title="Estado de las fuentes"
              subtitle="Qué pipelines responden, cuánto tardan y qué aporta cada uno. Las que fallan se agrupan arriba."
              meta={
                <>
                  <span>{sourceList.length} fuentes</span>
                  {p.health ? <span>{Math.round(p.health.ingest.uptime_s / 60)} min activo</span> : null}
                </>
              }
            />

            <SummaryStrip
              items={[
                {
                  label: "Operativas",
                  value: `${healthySources.length}/${sourceList.length}`,
                  tone: failingSources.length ? "var(--warn)" : "var(--ok)",
                  hint: "Fuentes que responden ahora",
                },
                {
                  label: "Con error",
                  value: failingSources.length,
                  tone: failingSources.length ? "var(--danger)" : undefined,
                  hint: "Fuentes que necesitan revisión",
                },
                { label: "Elementos", value: fmtNumber(sourceItems), hint: "Elementos aportados en la última ingesta" },
                { label: "Tiempo", value: sourceLatency, hint: "Duración media de la última ingesta" },
              ]}
            />

            {failingSources.length > 0 && (
              <PanelSection
                title="Requieren atención"
                count={failingSources.length}
                hint="Errores de la última ingesta"
                defaultOpen
              >
                {failingSources.map(renderSource)}
              </PanelSection>
            )}

            <PanelSection
              title="Fuentes operativas"
              count={healthySources.length}
              hint="Responden con normalidad"
              defaultOpen={failingSources.length === 0}
            >
              {healthySources.map(renderSource)}
            </PanelSection>

            <PanelSection title="Motor y almacenamiento" hint="Infraestructura de datos">
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
            </PanelSection>

            <PanelSection title="Alertas por tipo" count={Object.keys(p.health?.fence.counters ?? {}).length} hint="Contadores de las zonas vigiladas">
              <dl className="kv">
                {Object.entries(p.health?.fence.counters ?? {}).map(([k, v]) => (
                  <div key={k} style={{ display: "contents" }}>
                    <dt>{k}</dt><dd>{v}</dd>
                  </div>
                ))}
              </dl>
            </PanelSection>
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
        <span className="empty-ico" aria-hidden="true"><Icon name="event" size={30} /></span>
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
  // Graduación NATO AJP-2.1 que sirve el backend en cada evento (A-F + 1-6).
  const admiralty = ev.admiralty ? String(ev.admiralty) : "";
  const admiraltyWhy = ev.grading ? String(ev.grading) : "";
  const tlp = ev.tlp ? String(ev.tlp) : "";
  const when = fechaExacta(ev.event_time);
  const country = ev.country_es ?? ev.country ?? "";
  const coords = (p.selected?.geometry as any)?.coordinates ?? [];
  const evLat = Number(ev.lat ?? coords[1]);
  const evLon = Number(ev.lon ?? coords[0]);

  return (
    <div>
      <div className="detail">
        <div className="detail-meta" style={{ marginBottom: 8 }}>
          <span className="badge solid" style={{ background: meta.color }}><Icon name={meta.icon} size={14} /> {meta.label}</span>
          {severityText && (
            <span className="badge" style={{ color: severityColorHex, borderColor: severityColorHex }}>
              Gravedad {severityText}
            </span>
          )}
          <span className="badge">{sourceEs(ev.source)}</span>
          <button className="faint detail-close" style={{ marginLeft: "auto" }} onClick={p.onClearSelection} title="Cerrar la ficha"><Icon name="close" size={16} /></button>
        </div>

        <h2 className="detail-title">{ev.title}</h2>

        <div className="pn-meta" style={{ marginBottom: 10 }}>
          <span>{when.local}</span>
          <span>hace {timeAgo(ev.event_time)}</span>
          <span>{country || "sin país"}</span>
          <span>{sourceList.length > 1 ? `${sourceList.length} fuentes` : "una fuente"} · {ev.mentions ?? 1} menciones</span>
        </div>

        {ev.summary && (
          <p className="detail-lede" style={{ marginBottom: 12 }}>{ev.summary}</p>
        )}

        <SummaryStrip
          items={[
            { label: "Gravedad", value: severityText || "sin dato", tone: severityColorHex, hint: "Gravedad calculada del suceso" },
            { label: "Confianza", value: `${Math.round((ev.confidence ?? 0) * 100)} %`, hint: "Confianza del suceso consolidado" },
            { label: "Fuentes", value: sourceList.length || 1, hint: "Fuentes que confirman el suceso" },
          ]}
        />

        <div className="pn-tools">
          <div className="btn-row" style={{ flexWrap: "wrap" }}>
            <button className="btn primary" onClick={p.onGenerateBriefing} disabled={p.briefingLoading}>
              {p.briefingLoading ? <span className="spinner" /> : <Icon name="report" size={16} />} Informe de la zona
            </button>
            {ev.url && (
              <a className="btn" href={ev.url} target="_blank" rel="noreferrer"><Icon name="external" size={15} /> Abrir la fuente</a>
            )}
            {Number.isFinite(evLat) && Number.isFinite(evLon) && (
              <>
                <a
                  className="btn ghost"
                  href={`https://apps.sentinel-hub.com/eo-browser/?lat=${evLat}&lng=${evLon}&zoom=13`}
                  target="_blank"
                  rel="noreferrer"
                  title="Comparar la imagen de hoy con la de hace 30 días (Sentinel-2, 10 m, gratis)"
                >
                  ◭ Sentinel-2
                </a>
                <a
                  className="btn ghost"
                  href={`https://www.google.com/maps/@${evLat},${evLon},1200m/data=!3m1!1e3`}
                  target="_blank"
                  rel="noreferrer"
                >
                  <Icon name="grid" size={15} /> Satélite
                </a>
              </>
            )}
          </div>
        </div>

        <div style={{ padding: "10px 14px 0" }}>
          <EventPhoto eventId={String(ev.id ?? "")} />
        </div>

        <PanelSection title="Dónde y cuándo" count={country || "coordenadas"} defaultOpen>
          <dl className="kv">
            <dt>País / región</dt><dd>{country || "sin datos"}</dd>
            <dt>Coordenadas</dt><dd>{Number(ev.lat).toFixed(4)}, {Number(ev.lon).toFixed(4)}</dd>
            <dt>Hora local</dt><dd>{when.local}</dd>
            <dt>Hora UTC</dt><dd>{when.utc}</dd>
            <dt>Categoría</dt><dd>{meta.label}{ev.subtype ? ` · ${ev.subtype}` : ""}</dd>
            {ev.depth_km != null && (
              <><dt>Profundidad</dt><dd>{Number(ev.depth_km).toLocaleString("es-ES", { maximumFractionDigits: 1 })} km</dd></>
            )}
            <dt>Fuentes</dt><dd>{sourceList.map(sourceEs).join(" · ") || sourceEs(ev.source)}</dd>
          </dl>
        </PanelSection>

        <PanelSection title="Cómo interpretarlo" defaultOpen>
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
        </PanelSection>
      </div>

      {/* corroboración */}
      {p.detail?.mentions && p.detail.mentions.length > 0 && (
        <PanelSection
          title="Menciones fusionadas"
          count={p.detail.mentions.length}
          hint="Noticias y avisos unidos en este suceso"
        >
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
        </PanelSection>
      )}

      {/* proximidad */}
      <PanelSection
        title="Población e infraestructura cerca"
        count={`${p.nearbyRadiusKn} km`}
        hint={
          p.nearby
            ? `${p.nearby.count} núcleos · ${fmtNumber(p.nearby.population_exposed)} hab.`
            : "Núcleos urbanos y habitantes expuestos"
        }
      >
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
      </PanelSection>

      <PanelSection
        title="Datos técnicos"
        count={admiralty || "fuente"}
        hint="Grado OTAN, identificador y datos originales"
      >
        <dl className="kv">
          {ev.severity != null && (
            <><dt>Valor de gravedad</dt><dd>{Number(ev.severity).toLocaleString("es-ES")}</dd></>
          )}
          <dt>Confianza</dt><dd>{Math.round((ev.confidence ?? 0) * 100)} %</dd>
          {admiralty && (
            <><dt>Grado OTAN</dt><dd title={admiraltyWhy}>{admiralty}{tlp ? ` · TLP:${tlp}` : ""}</dd></>
          )}
          <dt>Identificador</dt><dd style={{ fontSize: 9.5 }}>{ev.id}</dd>
        </dl>
        {payload && Object.keys(payload).length > 0 && (
          <>
            <div className="section-title" style={{ marginTop: 10 }}>Datos originales de la fuente</div>
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
          </>
        )}
      </PanelSection>
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
    fetch(apiUrl(`/api/events/${encodeURIComponent(eventId)}/photo`))
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

const REASON_ES: Record<string, string> = {
  disaster: "desastre",
  earthquake: "sismo",
  flood: "inundación",
  wildfire: "incendio",
  fire: "incendio",
  conflict: "conflicto",
  protest: "protesta",
  traffic: "tráfico",
  health: "salud",
  storm: "tormenta",
  cyclone: "ciclón",
  volcano: "volcán",
  military: "militar",
  economy: "economía",
  terror: "terrorismo",
  population: "población",
};

function reasonEs(reason: string) {
  return REASON_ES[reason.toLowerCase()] ?? reason;
}

function ThreatsPanel({ onPick, hourWindow, onWindow }: { onPick: (id: string) => void; hourWindow: number; onWindow: (h: number) => void }) {
  const [items, setItems] = useState<ThreatItem[]>([]);
  const [meta, setMeta] = useState<{ count: number; considered: number; levels: Record<string, number> } | null>(null);
  const [loading, setLoading] = useState(false);
  const [minScore, setMinScore] = useState(5.5);

  useEffect(() => {
    let alive = true;
    const cargar = () => {
      setLoading(true);
      fetch(apiUrl(`/api/events/priority?hours=${hourWindow}&min_score=${minScore}&limit=250`))
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
      <PanelHeader
        icon="warning"
        eyebrow="Prioridad"
        title="Amenazas"
        subtitle="Sucesos con riesgo para las personas, ordenados por gravedad, corroboración y palabras de riesgo del titular."
        meta={
          <>
            <span>{loading ? "actualizando…" : "se refresca cada 45 s"}</span>
            <span>{minScore === 7.5 ? "solo críticas" : minScore === 5.5 ? "alta o superior" : "media o superior"}</span>
          </>
        }
      />

      <SummaryStrip
        items={[
          { label: "Ahora", value: meta?.count ?? items.length, hint: "Sucesos por encima del umbral" },
          { label: "Crítica", value: meta?.levels["crítica"] ?? 0, tone: "var(--danger)", hint: "Riesgo inmediato para la población" },
          { label: "Alta", value: meta?.levels["alta"] ?? 0, tone: "var(--warn)", hint: "Riesgo alto" },
          { label: "Base", value: meta?.considered ?? "—", hint: "Sucesos evaluados en la ventana" },
        ]}
      />

      <div className="pn-tools">
        <div className="pn-tool-row">
          <span className="tiny faint">Ventana</span>
          {[24, 168, 720].map((h) => (
            <button key={h} className={`chip ${hourWindow === h ? "active" : ""}`} onClick={() => onWindow(h)}>
              {h === 24 ? "24 h" : h === 168 ? "7 días" : "30 días"}
            </button>
          ))}
        </div>
        <div className="pn-tool-row">
          <span className="tiny faint">Desde</span>
          {[3.5, 5.5, 7.5].map((v) => (
            <button key={v} className={`chip ${minScore === v ? "active" : ""}`} onClick={() => setMinScore(v)}
              title={v === 7.5 ? "solo crítica" : v === 5.5 ? "alta o crítica" : "media o superior"}>
              {v === 7.5 ? "crítica" : v === 5.5 ? "alta" : "media"}
            </button>
          ))}
        </div>
      </div>

      <div className="pn-tools" style={{ paddingTop: 8, gap: 0 }}>
        {items.length === 0 && !loading && (
          <div className="empty">
            <span className="empty-ico" aria-hidden="true"><Icon name="warning" size={30} /></span>
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
              </span>
              {it.priority.reasons?.length ? (
                <span className="tiny" style={{ display: "block", marginTop: 3, color: "var(--text-faint)" }}>
                  Motivos: {it.priority.reasons.map(reasonEs).join(" · ")}
                </span>
              ) : null}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}
