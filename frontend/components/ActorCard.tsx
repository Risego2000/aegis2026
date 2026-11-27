"use client";

import { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";

/* ---------------------------------------------------------------------------
   Ficha completa de un elemento móvil (aeronave / buque / satélite).
   Se muestran TODOS los campos que devuelve el backend, traducidos cuando
   existe etiqueta en español, más el histórico de la estela y los datos
   orbitales en el caso de satélites.
--------------------------------------------------------------------------- */

const LABELS: Record<string, [string, string?]> = {
  // aeronaves
  id: ["Identificador"],
  callsign: ["Indicativo"],
  registration: ["Matrícula"],
  type: ["Modelo"],
  typecode: ["Código ICAO"],
  category: ["Categoría"],
  description: ["Descripción"],
  operator: ["Operador"],
  line_label: ["Línea"],
  next_stop_name: ["Próxima parada"],
  route_name: ["Trayecto"],
  delay_s: ["Retraso", "s"],
  airline: ["Aerolínea"],
  owner: ["Propietario"],
  altitude_ft: ["Altitud", "ft"],
  alt_baro: ["Altitud barométrica", "ft"],
  alt_geom: ["Altitud geométrica", "ft"],
  speed_kn: ["Velocidad", "kt"],
  gs: ["Velocidad terrestre", "kt"],
  ias: ["Velocidad indicada", "kt"],
  tas: ["Velocidad verdadera", "kt"],
  mach: ["Mach"],
  track: ["Rumbo", "°"],
  true_heading: ["Rumbo verdadero", "°"],
  mag_heading: ["Rumbo magnético", "°"],
  heading: ["Proa", "°"],
  course: ["Rumbo", "°"],
  squawk: ["Squawk"],
  emergency: ["Emergencia"],
  spi: ["Squawk SPI"],
  on_ground: ["En tierra"],
  ground: ["En tierra"],
  vertical_rate: ["Régimen vertical", "ft/min"],
  vertical_fpm: ["Régimen vertical", "ft/min"],
  mlat: ["Multilateración"],
  seen_pos: ["Última posición vista", "s"],
  sos: ["Baliza de socorro"],
  baro_rate: ["Régimen barométrico", "ft/min"],
  geom_rate: ["Régimen geométrico", "ft/min"],
  nav_altitude_mcp: ["Altitud seleccionada", "ft"],
  nav_qnh: ["QNH", "hPa"],
  nav_modes: ["Modos de navegación"],
  latency: ["Latencia", "s"],
  messages: ["Mensajes recibidos"],
  rssi: ["Señal", "dBFS"],
  seen: ["Última señal", "s"],
  nic: ["NIC"],
  rc: ["Radio de contención", "m"],
  nac_p: ["Precisión NACp"],
  region: ["Región"],
  country: ["País"],
  source: ["Fuente"],
  updated: ["Actualizado"],
  photo: ["Fotografía"],
  // buques
  mmsi: ["MMSI"],
  imo: ["IMO"],
  name: ["Nombre"],
  ship_type: ["Tipo de buque"],
  destination: ["Destino"],
  eta: ["ETA"],
  draught: ["Calado", "m"],
  dimension: ["Dimensiones"],
  to_bow: ["Eslora a proa", "m"],
  to_stern: ["Eslora a popa", "m"],
  to_port: ["Manga a babor", "m"],
  to_starboard: ["Manga a estribor", "m"],
  navstat: ["Estado de navegación"],
  navstat_label: ["Estado de navegación"],
  rot: ["Razón de giro", "°/min"],
  sog: ["Velocidad", "kt"],
  cog: ["Rumbo", "°"],
  // satélites
  norad: ["NORAD"],
  intl_designator: ["Designación internacional"],
  groups: ["Grupos"],
  object_id: ["Identificador"],
  launch_date: ["Lanzamiento"],
  decay_date: ["Fecha de decaimiento"],
  period_min: ["Periodo", "min"],
  inclination: ["Inclinación", "°"],
  eccentricity: ["Excentricidad"],
  altitude_km: ["Altitud", "km"],
  speed_km_s: ["Velocidad orbital", "km/s"],
  orbits_per_day: ["Órbitas por día"],
  footprint_radius_km: ["Huella de cobertura", "km"],
  semi_major_axis_km: ["Semieje mayor", "km"],
  apogee_km: ["Apogeo", "km"],
  perigee_km: ["Perigeo", "km"],
  raan_deg: ["Ascensión recta (RAAN)", "°"],
  arg_perigee_deg: ["Argumento del perigeo", "°"],
  mean_anomaly_deg: ["Anomalía media", "°"],
  bstar: ["Coeficiente B*"],
  // histórico
  first_seen: ["Primera observación"],
  first_seen_s: ["Primera observación", "s"],
  age_s: ["Antigüedad", "s"],
  samples: ["Muestras"],
  track_minutes: ["Ventana de estela", "min"],
  distance_km: ["Distancia recorrida", "km"],
  avg_speed_kmh: ["Velocidad media", "km/h"],
  lat: ["Latitud", "°"],
  lon: ["Longitud", "°"],
  ts: ["Instante"],
};

const SKIP = new Set(["photo_url", "photos", "raw", "json", "lon", "lat"]);
const HIDDEN_ORDER = ["id", "callsign", "name", "mmsi", "norad", "registration"];

function label(key: string, fallback?: string) {
  const hit = LABELS[key];
  if (!hit) return fallback ?? key;
  return hit[1] ? `${hit[0]} (${hit[1]})` : hit[0];
}

function fmt(v: any): string {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "boolean") return v ? "sí" : "no";
  if (typeof v === "number") {
    if (!Number.isFinite(v)) return "—";
    const abs = Math.abs(v);
    if (abs !== 0 && abs < 0.001) return v.toExponential(2);
    if (Number.isInteger(v)) return v.toLocaleString("es-ES");
    return v.toLocaleString("es-ES", { maximumFractionDigits: abs < 10 ? 4 : 2 });
  }
  if (Array.isArray(v)) return v.length ? v.join(" · ") : "—";
  if (typeof v === "object") return JSON.stringify(v);
  const s = String(v);
  if (/^\d{4}-\d{2}-\d{2}T/.test(s)) {
    const d = new Date(s);
    if (!Number.isNaN(d.getTime())) return d.toLocaleString("es-ES");
  }
  return s;
}

/** Origen y destino de un vuelo según su indicativo (fuente abierta adsbdb.com). */
function RouteBlock({ d }: { d: any }) {
  const route = d?.route;
  const o = route?.origin;
  const dst = route?.destination;
  if (route && (o || dst)) {
    return (
      <>
        <div className="route-box">
          <div className="route-end">
            <div className="route-code">{o?.iata || o?.icao || "—"}</div>
            <div className="route-city">{o?.city || "origen"}</div>
            <div className="tiny faint">{o?.country || ""}</div>
          </div>
          <div className="route-arrow" aria-hidden="true">
            <span className="route-line" />→<span className="route-line" />
          </div>
          <div className="route-end right">
            <div className="route-code">{dst?.iata || dst?.icao || "—"}</div>
            <div className="route-city">{dst?.city || "destino"}</div>
            <div className="tiny faint">{dst?.country || ""}</div>
          </div>
        </div>
        <div className="kv-grid" style={{ marginTop: 10 }}>
          <div><span>Indicativo</span><b className="mono">{route.callsign}</b></div>
          <div><span>Aerolínea</span><b>{route.airline || "no publicada"}</b></div>
          <div><span>Aeropuerto origen</span><b>{o?.name || "—"}</b></div>
          <div><span>Aeropuerto destino</span><b>{dst?.name || "—"}</b></div>
        </div>
        <div className="cov-note">
          Ruta publicada por la aerolínea para este indicativo (adsbdb.com). No es un plan de vuelo
          en tiempo real: indica el trayecto que opera esa matrícula.
        </div>
      </>
    );
  }
  return (
    <div className="tiny faint" style={{ lineHeight: 1.6 }}>
      Este indicativo no tiene ruta publicada en las fuentes abiertas.
      <br />
      Se resuelve automáticamente en cuanto el vuelo figura en el registro público de rutas
      (adsbdb.com); los vuelos militares, privados y muchos de carga no lo están.
    </div>
  );
}

/** Puerto de destino y ETA de un buque (metadatos AIS de Digitraffic). */
function PortBlock({ d, actor }: { d: any; actor: Record<string, any> }) {
  const port = d?.port ?? {};
  const destino = port.destination || actor.destination || "";
  const eta = port.eta || actor.eta || "";
  const etaTxt = (() => {
    if (!eta) return "sin ETA";
    if (typeof eta === "string" && /^\d{4}-\d{2}-\d{2}/.test(eta)) {
      const dt = new Date(eta);
      if (!Number.isNaN(dt.getTime())) return dt.toLocaleString("es-ES");
    }
    return String(eta);
  })();
  return (
    <>
      <div className="route-box">
        <div className="route-end">
          <div className="route-code" style={{ fontSize: 13 }}>{actor.ship_type || actor.type || "Buque"}</div>
          <div className="route-city">Posición actual</div>
          <div className="tiny faint">
            {Number(actor.lat ?? actor.latitude ?? 0).toFixed(2)}, {Number(actor.lon ?? actor.longitude ?? 0).toFixed(2)}
          </div>
        </div>
        <div className="route-arrow" aria-hidden="true">
          <span className="route-line" />→<span className="route-line" />
        </div>
        <div className="route-end right">
          <div className="route-code" style={{ fontSize: 13, wordBreak: "break-word" }}>{destino || "—"}</div>
          <div className="route-city">Puerto de destino</div>
          <div className="tiny faint">ETA {etaTxt}</div>
        </div>
      </div>
      <div className="cov-note">
        El AIS <b>no transmite el puerto de salida</b>: solo el destino declarado por el capitán y la
        hora estimada de llegada. Cobertura de metadatos: {port.coverage || "Báltico · Digitraffic"}.
      </div>
    </>
  );
}

function Spark({ series, color, unit, label: text }: { series: number[]; color: string; unit: string; label: string }) {
  if (series.length < 2) return null;
  const w = 240;
  const h = 34;
  const min = Math.min(...series);
  const max = Math.max(...series);
  const span = max - min || 1;
  const pts = series.map((v, i) => {
    const x = (i / (series.length - 1)) * w;
    const y = h - ((v - min) / span) * (h - 4) - 2;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  return (
    <div style={{ marginTop: 6 }}>
      <div className="tiny faint" style={{ display: "flex", justifyContent: "space-between" }}>
        <span>{text}</span>
        <span className="mono">{fmt(min)} … {fmt(max)} {unit}</span>
      </div>
      <svg viewBox={`0 0 ${w} ${h}`} width="100%" height={h} preserveAspectRatio="none" style={{ display: "block" }}>
        <polyline points={pts.join(" ")} fill="none" stroke={color} strokeWidth="1.5" strokeLinejoin="round" />
        <circle cx={w} cy={pts[pts.length - 1].split(",")[1]} r="2.4" fill={color} />
      </svg>
    </div>
  );
}

export type ActorLike = {
  kind: "aircraft" | "vessels" | "satellites" | "air" | "trains";
  detail: any | null;
  loading?: boolean;
  follow?: boolean;
  onToggleFollow?: () => void;
  onRecenter?: () => void;
  onClear?: () => void;
};

const KIND_META: Record<string, { icon: string; title: string; color: string }> = {
  aircraft: { icon: "✈", title: "Aeronave", color: "#4dd0e1" },
  vessels: { icon: "⚓", title: "Buque", color: "#57d9c3" },
  satellites: { icon: "🛰", title: "Satélite", color: "#7ee7ff" },
  air: { icon: "🜁", title: "Sensor de calidad del aire", color: "#a5d6a7" },
  trains: { icon: "🚆", title: "Tren de Renfe", color: "#ffb454" },
};

export default function ActorCard(p: ActorLike) {
  const [raw, setRaw] = useState(false);
  const [copied, setCopied] = useState(false);
  const meta = KIND_META[p.kind] ?? KIND_META.aircraft;
  const d = p.detail;

  const actor: Record<string, any> = d?.actor ?? {};
  const title =
    actor.callsign || actor.name || d?.name || actor.registration || actor.mmsi || actor.norad || actor.id || "—";

  const history: any[] = d?.history ?? [];
  const altSeries = useMemo(() => history.map((h) => Number(h.altitude_ft ?? h.altitude_km ?? NaN)).filter(Number.isFinite), [history]);
  const spdSeries = useMemo(() => history.map((h) => Number(h.speed_kn ?? h.speed_km_s ?? NaN)).filter(Number.isFinite), [history]);

  const entries = useMemo(() => {
    const rows: [string, any][] = Object.entries(actor).filter(
      ([k, v]) => !SKIP.has(k) && v !== null && v !== undefined && typeof v !== "object"
    );
    rows.sort((a, b) => {
      const ia = HIDDEN_ORDER.indexOf(a[0]);
      const ib = HIDDEN_ORDER.indexOf(b[0]);
      return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib);
    });
    return rows;
  }, [actor]);

  const orbit = d?.orbit ?? null;
  const state = d?.state ?? null;

  const copy = () => {
    navigator.clipboard?.writeText(JSON.stringify(d, null, 2)).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    }).catch(() => {});
  };

  if (p.loading && !d) {
    return (
      <div className="section">
        <div className="tiny faint"><span className="spinner" /> cargando ficha completa…</div>
      </div>
    );
  }
  if (!d) {
    return (
      <div className="section">
        <div className="section-title">Sin elemento seleccionado</div>
        <div className="tiny faint">
          Toca una aeronave, un buque, un tren o un satélite en el mapa para ver todos sus datos y su trayectoria.
        </div>
      </div>
    );
  }

  return (
    <div data-actor={String(actor.id ?? "")} data-callsign={String(actor.callsign ?? "")} data-kind={p.kind}>
      <div className="section" style={{ borderLeft: `2px solid ${meta.color}`, paddingLeft: 10 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 20, color: meta.color }}>{meta.icon}</span>
          <div style={{ minWidth: 0 }}>
            <div style={{ fontWeight: 700, fontSize: 15, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
              {String(title)}
            </div>
            <div className="tiny faint mono">
              {meta.title} · {String(actor.id ?? actor.mmsi ?? actor.norad ?? "")}
            </div>
          </div>
          <span className="live-dot" style={{ marginLeft: "auto" }} title="dato en vivo" />
        </div>

        <div className="btn-row" style={{ marginTop: 8, flexWrap: "wrap" }}>
          <button className={`btn ${p.follow ? "primary" : ""}`} onClick={p.onToggleFollow}>
            {p.follow ? "◉ Siguiendo" : "◎ Seguir"}
          </button>
          <button className="btn" onClick={p.onRecenter}>⊕ Centrar</button>
          <button className="btn" onClick={copy}>{copied ? "✓ copiado" : "⧉ JSON"}</button>
          <button className="btn" onClick={p.onClear}>✕</button>
        </div>
      </div>

      {/* ------------------------------------------------- fotografía real */}
      <PhotoSection kind={p.kind} id={String(actor.id ?? "")} />

      {/* ------------------------------------------------------- tren (Renfe) */}
      {p.kind === "trains" && (
        <div className="section">
          <div className="section-title">
            <span>Tren en circulación</span>
            <span className="st-count">GTFS-Realtime</span>
          </div>
          <dl className="kv">
            <dt>Línea</dt>
            <dd>{actor.line_label || actor.line || "—"}</dd>
            <dt>Destino</dt>
            <dd>{actor.destination || d?.itinerary?.destination || "—"}</dd>
            <dt>Núcleo / red</dt>
            <dd>{actor.nucleo || actor.network || "—"}</dd>
            <dt>Operador</dt>
            <dd>{actor.operator || "Renfe"}</dd>
            <dt>Estado</dt>
            <dd>{actor.status || "—"}</dd>
            <dt>Velocidad</dt>
            <dd>{actor.speed_kmh != null ? `${actor.speed_kmh} km/h` : "—"}</dd>
            <dt>Retraso</dt>
            <dd>
              {actor.delay_s != null
                ? `${Math.round(Number(actor.delay_s) / 60)} min`
                : "sin dato en el feed"}
            </dd>
            <dt>Próxima parada</dt>
            <dd>{actor.next_stop_name || actor.next_stop || "—"}</dd>
          </dl>
          {d?.itinerary?.alert ? (
            <div className="cov-note" style={{ borderColor: "rgba(255,180,84,0.35)" }}>
              <b>Aviso de Renfe:</b> {String(d.itinerary.alert).slice(0, 320)}
            </div>
          ) : null}
          {(d?.itinerary?.stops?.length ?? 0) > 0 && (
            <>
              <div className="section-title" style={{ marginTop: 10 }}>
                <span>Itinerario</span>
                <span className="st-count">{d.itinerary.stops.length} paradas</span>
              </div>
              <ol className="train-stops">
                {d.itinerary.stops.map((st: any, i: number) => (
                  <li
                    key={`${st.id}-${i}`}
                    className={
                      st.id === actor.next_stop ? "next" : st.id === d.itinerary.stops[d.itinerary.stops.length - 1].id ? "last" : ""
                    }
                  >
                    <span className="train-stop-dot" />
                    <span className="train-stop-name">{st.name}</span>
                  </li>
                ))}
              </ol>
            </>
          )}
          <div className="tiny faint" style={{ marginTop: 6 }}>
            Fuente: Renfe, datos abiertos GTFS-Realtime + GTFS estático (CC-BY 4.0). Ouigo e Iryo,
            los otros dos operadores de alta velocidad, no publican la posición de sus trenes.
          </div>
        </div>
      )}

      {/* ------------------------------------------------ origen / destino */}
      {(p.kind === "aircraft" || p.kind === "vessels") && (
        <div className="section">
          <div className="section-title">
            <span>{p.kind === "aircraft" ? "Recorrido del vuelo" : "Recorrido del buque"}</span>
            <span className="st-count">{p.kind === "aircraft" ? "origen → destino" : "destino declarado"}</span>
          </div>
          {p.kind === "aircraft" ? <RouteBlock d={d} /> : <PortBlock d={d} actor={actor} />}
        </div>
      )}

      {p.kind === "air" && (
        <div className="section">
          <div className="section-title">Calidad del aire medida</div>
          <dl className="kv">
            <dt>PM2.5</dt>
            <dd>{actor.pm25 ?? "—"} µg/m³</dd>
            <dt>PM10</dt>
            <dd>{actor.pm10 ?? "—"} µg/m³</dd>
            <dt>Índice</dt>
            <dd>{actor.level ?? "—"}</dd>
            <dt>Temperatura</dt>
            <dd>{actor.temp_c ?? "—"} °C</dd>
            <dt>Humedad</dt>
            <dd>{actor.humidity ?? "—"} %</dd>
            <dt>Observado</dt>
            <dd>{actor.observed_at ?? "—"}</dd>
          </dl>
          <div className="tiny faint" style={{ marginTop: 6 }}>
            Sensor ciudadano de Sensor.Community (hardware SDS011/ PMS). Lectura pública, sin clave.
          </div>
        </div>
      )}

      {/* ------------------------------------------------------------ estela */}
      <div className="section">
        <div className="section-title">Trayectoria registrada</div>
        <div className="kv-grid">
          <div><span>Muestras</span><b className="mono">{fmt(actor.samples ?? history.length)}</b></div>
          <div><span>Ventana</span><b className="mono">{fmt(actor.track_minutes)} min</b></div>
          <div><span>Distancia</span><b className="mono">{fmt(actor.distance_km)} km</b></div>
          <div><span>Vel. media</span><b className="mono">{fmt(actor.avg_speed_kmh)} km/h</b></div>
          <div><span>Primera vez</span><b className="mono">{fmt(actor.first_seen_s)} s</b></div>
          <div><span>Observado</span><b className="mono">{fmt(actor.age_s)} s</b></div>
        </div>
        {p.kind === "satellites" ? (
          <Spark series={altSeries} color="#7ee7ff" unit="km" label="Altitud" />
        ) : (
          <>
            <Spark series={altSeries} color="#4dd0e1" unit={p.kind === "vessels" ? "m" : "ft"} label="Altitud" />
            <Spark series={spdSeries} color="#ffd166" unit="kt" label="Velocidad" />
          </>
        )}
      </div>

      {/* --------------------------------------------------------- orbital */}
      {orbit && (
        <div className="section">
          <div className="section-title">Elementos orbitales (SGP4)</div>
          <div className="kv-grid">
            {Object.entries(orbit).map(([k, v]) => (
              <div key={k}><span>{label(k)}</span><b className="mono">{fmt(v)}</b></div>
            ))}
          </div>
        </div>
      )}
      {state && (
        <div className="section">
          <div className="section-title">Estado instantáneo</div>
          <div className="kv-grid">
            {Object.entries(state).map(([k, v]) => (
              <div key={k}><span>{label(k)}</span><b className="mono">{fmt(v)}</b></div>
            ))}
            {d?.tle_age_min !== undefined && (
              <div><span>Edad del TLE</span><b className="mono">{fmt(d.tle_age_min)} min</b></div>
            )}
            {d?.epoch && <div><span>Época</span><b className="mono">{fmt(d.epoch)}</b></div>}
            {d?.groups && <div><span>Grupos</span><b className="mono">{fmt(d.groups)}</b></div>}
          </div>
        </div>
      )}

      {/* -------------------------------------------------- todos los campos */}
      <div className="section">
        <div className="section-title" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <span>Todos los campos ({entries.length})</span>
          <button className="btn ghost tiny" onClick={() => setRaw((v) => !v)}>{raw ? "vista tabla" : "JSON"}</button>
        </div>
        {raw ? (
          <pre className="code-block mono" style={{ maxHeight: 320, overflow: "auto", fontSize: 10.5 }}>
            {JSON.stringify(actor, null, 2)}
          </pre>
        ) : (
          <div className="kv-grid">
            {entries.map(([k, v]) => (
              <div key={k}>
                <span title={k}>{label(k)}</span>
                <b className={typeof v === "number" ? "mono" : ""}>{fmt(v)}</b>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* --------------------------------------------------------------- TLE */}
      {d?.tle && (
        <div className="section">
          <div className="section-title">TLE en uso</div>
          <pre className="code-block mono" style={{ fontSize: 10.5, overflowX: "auto" }}>
            {Array.isArray(d.tle) ? d.tle.join("\n") : String(d.tle)}
          </pre>
        </div>
      )}
    </div>
  );
}

/* ---------------------------------------------------------------------------
   Fotografía del aparato concreto.
   Avión: Planespotters (foto de ESE hex/matrícula, no del modelo).
   Buque: Wikimedia Commons (foto de archivo; el AIS no publica imagen).
--------------------------------------------------------------------------- */
function PhotoSection({ kind, id }: { kind: string; id: string }) {
  const [photo, setPhoto] = useState<{ url: string; proxy?: string; credit: string; link: string; source: string; note?: string } | null>(null);
  const [state, setState] = useState<"idle" | "loading" | "none" | "error">("idle");

  useEffect(() => {
    const CON_FOTO = ["aircraft", "vessels", "trains", "satellites", "cameras"];
    if (!id || !CON_FOTO.includes(kind)) { setPhoto(null); setState("idle"); return; }
    let alive = true;
    setState("loading");
    api.photo(CON_FOTO.includes(kind) ? kind : "aircraft", id)
      .then((r) => {
        if (!alive) return;
        if (r.photo?.url) { setPhoto(r.photo); setState("idle"); }
        else { setPhoto(null); setState("none"); }
      })
      .catch(() => { if (alive) { setPhoto(null); setState("error"); } });
    return () => { alive = false; };
  }, [kind, id]);

  if (!["aircraft", "vessels", "trains", "satellites", "cameras"].includes(kind)) return null;

  return (
    <div className="section">
      <div className="section-title">
        <span>{kind === "cameras" ? "Imagen en vivo" : kind === "satellites" ? "Imagen del satélite" : "Fotografía"}</span>
        {photo?.source && <span className="st-count">{photo.source}</span>}
      </div>
      {photo ? (
        <>
          <a href={photo.link || photo.url} target="_blank" rel="noreferrer" className="actor-photo">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={photo.proxy || photo.url} alt={`Fotografía de ${id}`} loading="lazy" referrerPolicy="no-referrer" />
          </a>
          <div className="tiny faint" style={{ marginTop: 4 }}>
            © {photo.credit}
            {photo.note ? ` · ${photo.note}` : ""}
          </div>
        </>
      ) : (
        <div className="tiny faint">
          {state === "loading"
            ? "buscando fotografía del aparato…"
            : state === "none"
              ? "no hay fotografía publicada de este aparato en los bancos abiertos"
              : "no se pudo consultar el banco de fotografías"}
        </div>
      )}
    </div>
  );
}
