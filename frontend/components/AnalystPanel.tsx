"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { apiUrl } from "@/lib/api";
import { markdownToHtml, timeAgo } from "@/lib/format";

/**
 * Panel de analista: lo que convierte el visor en herramienta de investigación.
 *
 * Todo lo que hay aquí son endpoints que ya existen (`/api/report/sitrep`,
 * `/api/gnss`, `/api/anomalies`, `/api/cases`, `/api/graph`, `/api/playback`,
 * `/api/sources/transparency`). El panel no calcula nada por su cuenta: si el
 * backend dice «sin datos», se dice «sin datos» y se explica por qué.
 */

type Section = "sitrep" | "patterns" | "cases" | "graph" | "playback" | "sources";

const SECTIONS: { key: Section; label: string; hint: string }[] = [
  { key: "sitrep", label: "SITREP", hint: "Informe de situación con grados de fuente OTAN" },
  { key: "patterns", label: "Patrones", hint: "Anomalías AIS y calidad GNSS" },
  { key: "cases", label: "Casos", hint: "Evidencia con cadena de custodia SHA-256" },
  { key: "graph", label: "Grafo", hint: "Vínculos suceso ↔ fuente ↔ país, export GraphML" },
  { key: "playback", label: "Reproducción", hint: "Posiciones históricas muestreadas" },
  { key: "sources", label: "Transparencia", hint: "Latencia y errores reales por fuente" },
];

type Props = {
  selectedEventId?: string | null;
  selectedTitle?: string | null;
};

async function getJson(path: string): Promise<any> {
  const res = await fetch(apiUrl(path), { cache: "no-store" });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

function download(name: string, text: string, type = "text/markdown") {
  const blob = new Blob([text], { type: `${type};charset=utf-8` });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}

export default function AnalystPanel({ selectedEventId, selectedTitle }: Props) {
  const [section, setSection] = useState<Section>("sitrep");
  const [hours, setHours] = useState(24);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  /* sitrep */
  const [sitrep, setSitrep] = useState<string>("");
  /* patrones */
  const [gnss, setGnss] = useState<any>(null);
  const [anomalies, setAnomalies] = useState<any>(null);
  /* casos */
  const [cases, setCases] = useState<any[]>([]);
  const [caseId, setCaseId] = useState<string>("");
  const [caseTitle, setCaseTitle] = useState("");
  const [verify, setVerify] = useState<any>(null);
  /* grafo */
  const [graph, setGraph] = useState<any>(null);
  /* playback */
  const [offsetMin, setOffsetMin] = useState(0);
  const [playback, setPlayback] = useState<any>(null);
  /* fuentes */
  const [sources, setSources] = useState<any>(null);

  const load = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      if (section === "sitrep") {
        const res = await fetch(apiUrl(`/api/report/sitrep?hours=${hours}`), { cache: "no-store" });
        setSitrep(await res.text());
      } else if (section === "patterns") {
        const [g, a] = await Promise.all([getJson("/api/gnss"), getJson("/api/anomalies")]);
        setGnss(g);
        setAnomalies(a);
      } else if (section === "cases") {
        const data = await getJson("/api/cases");
        setCases(data.cases ?? []);
        setCaseId((current) => current || data.cases?.[0]?.id || "");
      } else if (section === "graph") {
        setGraph(await getJson(`/api/graph?hours=${hours}&limit=150`));
      } else if (section === "playback") {
        const ts = new Date(Date.now() - offsetMin * 60_000).toISOString().slice(0, 19);
        setPlayback(await getJson(`/api/playback?ts=${encodeURIComponent(ts)}&window_s=300`));
      } else if (section === "sources") {
        setSources(await getJson("/api/sources/transparency"));
      }
    } catch (exc: any) {
      setError(String(exc?.message ?? exc));
    } finally {
      setBusy(false);
    }
  }, [section, hours, offsetMin]);

  useEffect(() => {
    void load();
  }, [load]);

  const currentCase = useMemo(() => cases.find((c) => c.id === caseId), [cases, caseId]);

  async function createCase() {
    if (!caseTitle.trim()) return;
    await fetch(apiUrl("/api/cases"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: caseTitle.trim(), tlp: "AMBER" }),
    });
    setCaseTitle("");
    await load();
  }

  async function addSelected() {
    if (!caseId || !selectedEventId) return;
    await fetch(apiUrl(`/api/cases/${encodeURIComponent(caseId)}/items`), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        kind: "event",
        ref: selectedEventId,
        title: selectedTitle ?? selectedEventId,
        payload: { event_id: selectedEventId, title: selectedTitle ?? "" },
      }),
    });
    setVerify(null);
    await load();
  }

  async function verifyCase() {
    if (!caseId) return;
    setVerify(await getJson(`/api/cases/${encodeURIComponent(caseId)}/verify`));
  }

  return (
    <div>
      <div className="section" style={{ paddingBottom: 8 }}>
        <div className="section-title">
          <span>Panel de analista</span>
          <span className="st-count">{busy ? "cargando…" : "datos en vivo"}</span>
        </div>
        <div className="chips" style={{ marginTop: 6 }}>
          {SECTIONS.map((s) => (
            <button
              key={s.key}
              className={`chip ${section === s.key ? "active" : ""}`}
              title={s.hint}
              onClick={() => setSection(s.key)}
            >
              {s.label}
            </button>
          ))}
        </div>
        {(section === "sitrep" || section === "graph") && (
          <div className="chips" style={{ marginTop: 6 }}>
            {[6, 24, 72, 168].map((h) => (
              <button key={h} className={`chip ${hours === h ? "active" : ""}`} onClick={() => setHours(h)}>
                {h} h
              </button>
            ))}
          </div>
        )}
      </div>

      {error && (
        <div className="section">
          <div className="cov-note" style={{ borderColor: "rgba(255,82,119,0.5)" }}>
            No se pudo consultar la API: {error}. Si estás en el sitio de Pages, apunta el cliente al
            backend con <code>?api=https://tu-backend</code> o edita <code>runtime-config.json</code>.
          </div>
        </div>
      )}

      {/* ------------------------------------------------------------ SITREP */}
      {section === "sitrep" && (
        <div className="section">
          <div className="btn-row" style={{ marginBottom: 8 }}>
            <button className="btn" onClick={() => void load()} disabled={busy}>↻ Actualizar</button>
            <button className="btn" onClick={() => download(`sitrep-${hours}h.md`, sitrep)} disabled={!sitrep}>
              ↓ .md
            </button>
          </div>
          {sitrep ? (
            <div className="briefing" dangerouslySetInnerHTML={{ __html: markdownToHtml(sitrep) }} />
          ) : (
            <div className="empty">
              <span className="empty-ico" aria-hidden="true">▤</span>
              <strong>Sin SITREP todavía</strong>
              El informe se compone de los sucesos ya guardados en la ventana elegida.
            </div>
          )}
        </div>
      )}

      {/* ---------------------------------------------------------- PATRONES */}
      {section === "patterns" && (
        <>
          <div className="section">
            <div className="section-title">
              <span>Calidad GNSS</span>
              <span className="st-count">{gnss?.status ?? "—"}</span>
            </div>
            <div className="tiny faint" style={{ marginBottom: 8 }}>
              NIC/NACp que declaran las aeronaves, agrupados por celda de 1°. Varios aviones
              degradados a la vez apuntan a interferencia, no a un receptor defectuoso.
            </div>
            {gnss?.cells?.length ? gnss.cells.map((c: any) => (
              <div key={c.cell} className="source-row">
                <span className={`status-dot ${c.level === "alert" ? "err" : "warn"}`} />
                <span className="source-name mono tiny">{c.cell}</span>
                <span className="source-meta">{c.degraded}/{c.evaluated} · ×{c.index}</span>
              </div>
            )) : <div className="tiny faint">Sin celdas degradadas en este momento.</div>}
            <div className="kv" style={{ marginTop: 8 }}>
              <dt>Aeronaves</dt>
              <dd>{gnss?.aircraft ? `${gnss.aircraft.ok} ok · ${gnss.aircraft.degraded} degradadas · ${gnss.aircraft.unknown} sin dato` : "—"}</dd>
            </div>
          </div>
          <div className="section">
            <div className="section-title">
              <span>Anomalías marítimas</span>
              <span className="st-count">{anomalies?.count ?? 0}</span>
            </div>
            {anomalies?.items?.length ? anomalies.items.slice(0, 40).map((a: any) => (
              <div key={`${a.kind}-${a.id}`} className="source-row">
                <span className={`status-dot ${a.severity === "high" ? "err" : a.severity === "medium" ? "warn" : "idle"}`} />
                <span className="source-name">{a.name || a.id}</span>
                <span className="source-meta">{a.detail}</span>
              </div>
            )) : (
              <div className="tiny faint">
                Sin anomalías: los huecos AIS y las trayectorias imposibles necesitan histórico, y
                este se construye desde que arranca el servidor.
              </div>
            )}
          </div>
        </>
      )}

      {/* ------------------------------------------------------------- CASOS */}
      {section === "cases" && (
        <>
          <div className="section">
            <div className="section-title">Nuevo caso</div>
            <div style={{ display: "flex", gap: 6 }}>
              <input
                value={caseTitle}
                onChange={(e) => setCaseTitle(e.target.value)}
                placeholder="Título del caso"
                style={{ flex: 1, minWidth: 0 }}
              />
              <button className="btn primary" onClick={() => void createCase()} disabled={!caseTitle.trim()}>
                Crear
              </button>
            </div>
            <div className="tiny faint" style={{ marginTop: 6 }}>
              Cada evidencia se encadena con SHA-256 sobre la anterior: si alguien edita el archivo,
              la verificación deja de cuadrar.
            </div>
          </div>

          <div className="section">
            <div className="section-title">
              <span>Casos</span>
              <span className="st-count">{cases.length}</span>
            </div>
            {cases.length === 0 && <div className="tiny faint">Aún no hay casos abiertos.</div>}
            {cases.map((c) => (
              <button
                key={c.id}
                className={`source-row ${c.id === caseId ? "active" : ""}`}
                style={{ width: "100%", textAlign: "left", background: "none", border: "none", cursor: "pointer" }}
                onClick={() => { setCaseId(c.id); setVerify(null); }}
              >
                <span className={`status-dot ${c.id === caseId ? "ok" : "idle"}`} />
                <span className="source-name">{c.title}</span>
                <span className="source-meta">{c.items} evid. · TLP:{c.tlp} · {timeAgo(c.updated_at)}</span>
              </button>
            ))}
          </div>

          {currentCase && (
            <div className="section">
              <div className="section-title">
                <span>{currentCase.title}</span>
                <span className="st-count">{currentCase.id}</span>
              </div>
              <div className="btn-row" style={{ marginBottom: 8 }}>
                <button className="btn" onClick={() => void addSelected()} disabled={!selectedEventId}>
                  + Suceso seleccionado
                </button>
                <button className="btn" onClick={() => void verifyCase()}>Verificar cadena</button>
                <a
                  className="btn ghost"
                  href={apiUrl(`/api/cases/${encodeURIComponent(currentCase.id)}/report`)}
                  target="_blank"
                  rel="noreferrer"
                >
                  ↓ Informe
                </a>
              </div>
              {!selectedEventId && (
                <div className="tiny faint">Selecciona un suceso en el mapa para poder fijarlo.</div>
              )}
              {verify && (
                <div className="cov-note" style={{ borderColor: verify.ok ? "rgba(53,208,127,0.45)" : "rgba(255,82,119,0.5)" }}>
                  {verify.ok
                    ? `Cadena íntegra · ${verify.items} evidencias · cabeza ${String(verify.head).slice(0, 16)}…`
                    : `Cadena alterada en ${verify.broken?.length ?? 0} eslabón(es).`}
                </div>
              )}
            </div>
          )}
        </>
      )}

      {/* ------------------------------------------------------------- GRAFO */}
      {section === "graph" && (
        <div className="section">
          <div className="section-title">
            <span>Grafo de vínculos</span>
            <span className="st-count">
              {graph ? `${graph.counts.nodes} nodos · ${graph.counts.edges} aristas` : "—"}
            </span>
          </div>
          <div className="btn-row" style={{ marginBottom: 8 }}>
            <a className="btn" href={apiUrl(`/api/graph/export?fmt=graphml&hours=${hours}`)} target="_blank" rel="noreferrer">
              ↓ GraphML
            </a>
            <span className="tiny faint" style={{ alignSelf: "center" }}>
              Se abre en yEd, Gephi, i2 o Maltego.
            </span>
          </div>
          <GraphSvg graph={graph} />
        </div>
      )}

      {/* --------------------------------------------------------- REPRODUCCIÓN */}
      {section === "playback" && (
        <div className="section">
          <div className="section-title">
            <span>Reproducción histórica</span>
            <span className="st-count">hace {offsetMin} min</span>
          </div>
          <input
            type="range"
            min={0}
            max={360}
            step={5}
            value={offsetMin}
            onChange={(e) => setOffsetMin(Number(e.target.value))}
            style={{ width: "100%" }}
          />
          <div className="kv" style={{ marginTop: 8 }}>
            <dt>Instante</dt><dd className="mono">{playback?.ts ?? "—"}</dd>
            <dt>Posiciones</dt><dd>{playback?.count ?? 0}</dd>
            <dt>Aeronaves</dt><dd>{playback?.by_kind?.aircraft ?? 0}</dd>
            <dt>Buques</dt><dd>{playback?.by_kind?.vessels ?? 0}</dd>
            <dt>Filas guardadas</dt><dd>{playback?.stats?.positions ?? 0}</dd>
          </div>
          <div className="tiny faint" style={{ marginTop: 6 }}>
            Se muestrea cada 5 minutos con 6 h de retención (~70 k filas como máximo). Las
            posiciones solo existen desde que el servidor lleva encendido ese tiempo.
          </div>
        </div>
      )}

      {/* -------------------------------------------------------- TRANSPARENCIA */}
      {section === "sources" && (
        <div className="section">
          <div className="section-title">
            <span>Tasa de acierto por fuente</span>
            <span className="st-count">{sources?.window_runs ?? 0} ingestas</span>
          </div>
          {sources?.sources?.map((s: any) => (
            <div key={s.source} className="source-row">
              <span className={`status-dot ${s.success_rate >= 0.95 ? "ok" : s.success_rate >= 0.7 ? "warn" : "err"}`} />
              <span className="source-name mono tiny">{s.source}</span>
              <span className="source-meta">
                {Math.round(s.success_rate * 100)} % · {s.avg_duration_ms} ms · {s.items_avg} elem.
              </span>
            </div>
          ))}
          <div className="tiny faint" style={{ marginTop: 8 }}>{sources?.method ?? ""}</div>
        </div>
      )}
    </div>
  );
}

/** Grafo mínimo: círculos por tipo dibujados en anillos concéntricos. */
function GraphSvg({ graph }: { graph: any }) {
  if (!graph?.nodes?.length) {
    return <div className="tiny faint">Sin vínculos en la ventana: hacen falta sucesos guardados.</div>;
  }
  const nodes = graph.nodes.slice(0, 120);
  const byKind: Record<string, any[]> = {};
  for (const node of nodes) (byKind[node.kind] ??= []).push(node);
  const kinds = Object.keys(byKind);
  const size = 300;
  const center = size / 2;
  const placed: Record<string, { x: number; y: number; color: string }> = {};
  const colors: Record<string, string> = {
    event: "#ff8f6b", source: "#4dd0e1", country: "#a5d6a7", category: "#b388ff",
  };
  kinds.forEach((kind, ring) => {
    const list = byKind[kind];
    const radius = 42 + ring * 34;
    list.forEach((node, i) => {
      const angle = (i / Math.max(1, list.length)) * Math.PI * 2;
      placed[node.id] = {
        x: center + Math.cos(angle) * radius,
        y: center + Math.sin(angle) * radius,
        color: colors[kind] ?? "#90a4ae",
      };
    });
  });
  return (
    <svg viewBox={`0 0 ${size} ${size}`} width="100%" height={size} role="img" aria-label="Grafo de vínculos">
      {graph.edges.slice(0, 400).map((edge: any, i: number) => {
        const a = placed[edge.src];
        const b = placed[edge.dst];
        if (!a || !b) return null;
        return <line key={i} x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke="rgba(150,180,200,0.18)" strokeWidth={0.7} />;
      })}
      {Object.entries(placed).map(([id, pos]) => (
        <circle key={id} cx={pos.x} cy={pos.y} r={3.2} fill={pos.color}>
          <title>{id}</title>
        </circle>
      ))}
      {kinds.map((kind, i) => (
        <text key={kind} x={6} y={14 + i * 12} fill={colors[kind] ?? "#90a4ae"} fontSize={8}>
          ● {kind}
        </text>
      ))}
    </svg>
  );
}
