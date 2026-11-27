"use client";

import { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { Icon, type IconName } from "@/components/Icon";
import { PanelHeader, PanelSection, SummaryStrip } from "@/components/PanelUI";

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

const KIND_META: Record<string, { icon: IconName; title: string; color: string }> = {
  aircraft: { icon: "plane", title: "Aeronave", color: "#4dd0e1" },
  vessels: { icon: "ship", title: "Buque", color: "#57d9c3" },
  satellites: { icon: "satellite", title: "Satélite", color: "#7ee7ff" },
  air: { icon: "air", title: "Sensor de calidad del aire", color: "#a5d6a7" },
  trains: { icon: "train", title: "Tren en vivo", color: "#ffb454" },
};

/** Código interno de red → nombre legible en la ficha. */
const NETWORK_ES: Record<string, string> = {
  "renfe-cercanias": "Renfe Cercanías",
  "renfe-ld": "Renfe AVE/LD/MD",
  fgc: "FGC",
  amtrak: "Amtrak",
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

  // Cuatro cifras que resumen el elemento antes de entrar en detalles. El
  // resto de campos sigue disponible, plegado, al final de la ficha.
  const metrics = (() => {
    if (p.kind === "trains") {
      return [
        { label: "Línea", value: actor.line_label || actor.line || "—" },
        { label: "Destino", value: actor.destination || d?.itinerary?.destination || "—" },
                { label: "Retraso min",
          value: actor.delay_s != null ? fmt(Math.round(Number(actor.delay_s) / 60)) : "—",
          tone: Number(actor.delay_s) > 300 ? "var(--warn)" : undefined,
        },
        { label: "Vel. km/h", value: actor.speed_kmh != null ? fmt(actor.speed_kmh) : "—" },
      ];
    }
    if (p.kind === "vessels") {
      return [
        { label: "Vel. kt", value: actor.sog != null || actor.speed_kn != null ? fmt(actor.sog ?? actor.speed_kn) : "—" },
        { label: "Rumbo °", value: actor.cog != null || actor.course != null ? fmt(actor.cog ?? actor.course) : "—" },
        { label: "Tipo", value: actor.ship_type || actor.type || "—" },
        { label: "Calado m", value: actor.draught != null ? fmt(actor.draught) : actor.dimension || "—" },
      ];
    }
    if (p.kind === "satellites") {
      return [
        { label: "Altitud km", value: actor.altitude_km != null ? fmt(actor.altitude_km) : "—" },
        { label: "Vel. km/s", value: actor.speed_km_s != null ? fmt(actor.speed_km_s) : "—" },
        { label: "Incl. °", value: actor.inclination != null ? fmt(actor.inclination) : "—" },
        { label: "Periodo", value: actor.period_min != null ? fmt(actor.period_min) : "—" },
      ];
    }
    if (p.kind === "air") {
      return [
        { label: "PM2.5", value: actor.pm25 != null ? `${fmt(actor.pm25)}` : "—" },
        { label: "PM10", value: actor.pm10 != null ? `${fmt(actor.pm10)}` : "—" },
        { label: "Índice", value: actor.level || "—" },
        { label: "Temp. °C", value: actor.temp_c != null ? fmt(actor.temp_c) : "—" },
      ];
    }
    return [
      {
        label: actor.altitude_ft != null || actor.alt_baro != null || actor.altitude_km == null ? "Altitud ft" : "Altitud km",
        value: actor.altitude_ft != null || actor.alt_baro != null || actor.altitude_km != null
          ? fmt(actor.altitude_ft ?? actor.alt_baro ?? actor.altitude_km)
          : "—",
      },
      {
        label: "Vel. kt",
        value: actor.speed_kn != null || actor.gs != null ? fmt(actor.speed_kn ?? actor.gs) : "—",
      },
      {
        label: "Rumbo °",
        value: actor.track != null || actor.heading != null || actor.course != null
          ? fmt(actor.track ?? actor.heading ?? actor.course)
          : "—",
      },
      { label: "Squawk", value: actor.squawk || "—" },
    ];
  })();

  const identity = [
    actor.registration,
    actor.type || actor.ship_type,
    actor.operator || actor.airline,
    actor.country,
  ].filter(Boolean).slice(0, 3).join(" · ");

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
      <PanelHeader
        icon={meta.icon}
        eyebrow={meta.title}
        title={String(title)}
        subtitle={identity || undefined}
        tone={meta.color}
        meta={
          <>
            <span>{String(actor.id ?? actor.mmsi ?? actor.norad ?? "")}</span>
            {actor.source ? <span>fuente: {String(actor.source)}</span> : null}
            <span className="live-dot" title="dato en vivo" />
          </>
        }
        actions={
          <button className="btn ghost" onClick={p.onClear} aria-label="Cerrar la ficha">
            <Icon name="close" size={15} />
          </button>
        }
      />

      <SummaryStrip items={metrics} />

      <div className="pn-tools">
        <div className="btn-row" style={{ flexWrap: "wrap" }}>
          <button className={`btn ${p.follow ? "primary" : ""}`} onClick={p.onToggleFollow}>
            <Icon name="follow" size={15} /> {p.follow ? "Siguiendo" : "Seguir"}
          </button>
          <button className="btn" onClick={p.onRecenter}><Icon name="locate" size={15} /> Centrar</button>
          <button className="btn" onClick={copy}><Icon name={copied ? "check" : "copy"} size={15} /> {copied ? "Copiado" : "JSON"}</button>
        </div>
      </div>

      {/* ------------------------------------------------- fotografía real */}
      <PhotoSection kind={p.kind} id={String(actor.id ?? "")} />

      {/* ---------------------------------------------------------- tren vivo */}
      {p.kind === "trains" && (
        <PanelSection
          title="Servicio y próxima parada"
          count={d?.itinerary?.stops?.length ? `${d.itinerary.stops.length} paradas` : "GTFS-RT"}
          hint="Operador, estado y avisos"
        >
          <dl className="kv">
            <dt>Línea</dt>
            <dd>{actor.line_label || actor.line || "—"}</dd>
            <dt>Destino</dt>
            <dd>{actor.destination || d?.itinerary?.destination || "—"}</dd>
            <dt>Núcleo / red</dt>
            <dd>{actor.nucleo || NETWORK_ES[String(actor.network)] || actor.network || "—"}</dd>
            <dt>Operador</dt>
            <dd>{actor.operator || "—"}</dd>
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
              <b>Aviso del operador:</b> {String(d.itinerary.alert).slice(0, 320)}
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
            Fuente: {actor.source || "el operador"} · {actor.operator || "datos abiertos"}.
            {actor.network !== "amtrak"
              ? " Ouigo e Iryo, los otros operadores de alta velocidad en España, no publican la posición de sus trenes."
              : ""}
          </div>
        </PanelSection>
      )}

      {/* ------------------------------------------------ origen / destino */}
      {(p.kind === "aircraft" || p.kind === "vessels") && (
        <PanelSection
          title={p.kind === "aircraft" ? "Recorrido del vuelo" : "Recorrido del buque"}
          count={p.kind === "aircraft" ? "origen → destino" : "destino declarado"}
          defaultOpen
        >
          {p.kind === "aircraft" ? <RouteBlock d={d} /> : <PortBlock d={d} actor={actor} />}
        </PanelSection>
      )}

      {p.kind === "air" && (
        <PanelSection title="Calidad del aire medida" count={actor.level || undefined} defaultOpen={false}>
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
        </PanelSection>
      )}

      {/* ------------------------------------------------------------ estela */}
      <PanelSection
        title="Trayectoria registrada"
        count={actor.samples ?? history.length}
        hint="Muestras, distancia y series"
      >
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
      </PanelSection>

      {/* --------------------------------------------------------- orbital */}
      {orbit && (
        <PanelSection title="Elementos orbitales (SGP4)" count="órbita" hint="Parámetros propagados">
          <div className="kv-grid">
            {Object.entries(orbit).map(([k, v]) => (
              <div key={k}><span>{label(k)}</span><b className="mono">{fmt(v)}</b></div>
            ))}
          </div>
        </PanelSection>
      )}
      {state && (
        <PanelSection title="Estado instantáneo" hint="Cálculo para este instante">
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
        </PanelSection>
      )}

      {/* -------------------------------------------------- todos los campos */}
      <PanelSection
        title="Todos los campos"
        count={entries.length}
        hint="Datos en bruto del elemento"
      >
        <div className="btn-row" style={{ justifyContent: "flex-end", marginBottom: 6 }}>
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
      </PanelSection>

      {/* --------------------------------------------------------------- TLE */}
      {d?.tle && (
        <PanelSection title="TLE en uso" hint="Elementos orbitales originales">
          <pre className="code-block mono" style={{ fontSize: 10.5, overflowX: "auto" }}>
            {Array.isArray(d.tle) ? d.tle.join("\n") : String(d.tle)}
          </pre>
        </PanelSection>
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
