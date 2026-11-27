/**
 * Hechos legibles de un suceso.
 *
 * Cada fuente publica un payload distinto (DGT: carretera y causa; USGS:
 * magnitud y tsunami; GDACS: nivel de alerta; FIRMS: FRP…). La ficha no debe
 * enseñar ese JSON crudo como única explicación: aquí se traducen las claves
 * conocidas a una lista breve de «qué ocurrió», sin inventar valores.
 */

export type EventFact = { label: string; value: string };

const CAUSA_ES: Record<string, string> = {
  accident: "accidente",
  roadMaintenance: "obras",
  maintenanceWorks: "obras",
  obstruction: "obstrucción",
  vehicleObstruction: "vehículo averiado",
  environmentalObstruction: "obstáculo",
  infrastructureDamageObstruction: "daño en la vía",
  roadOrCarriagewayOrLaneManagement: "gestión de carriles",
  abnormalTraffic: "tráfico anómalo",
  poorEnvironment: "condiciones ambientales",
  weatherCondition: "meteorología",
  restriction: "restricción",
  publicEvent: "evento público",
  authorityOperation: "operación especial",
  generalObstruction: "obstrucción",
};

const SENTIDO_ES: Record<string, string> = {
  northBound: "norte",
  southBound: "sur",
  eastBound: "este",
  westBound: "oeste",
  northEastBound: "noreste",
  northWestBound: "noroeste",
  southEastBound: "sureste",
  southWestBound: "suroeste",
  bothDirections: "ambos sentidos",
  clockwise: "horario",
  anticlockwise: "antihorario",
};

const VALIDEZ_ES: Record<string, string> = {
  active: "activa",
  planned: "prevista",
  suspended: "suspendida",
  finished: "finalizada",
  closed: "cerrada",
};

const ALERTA_ES: Record<string, string> = {
  green: "verde",
  yellow: "amarilla",
  orange: "naranja",
  red: "roja",
  unknown: "sin datos",
};

const CERTEZA_ES: Record<string, string> = {
  observed: "observado",
  likely: "probable",
  possible: "posible",
  unlikely: "improbable",
  unknown: "sin datos",
};

const URGENCIA_ES: Record<string, string> = {
  immediate: "inmediata",
  expected: "prevista",
  future: "futura",
  past: "pasada",
  unknown: "sin datos",
};

const GRAVEDAD_NWS_ES: Record<string, string> = {
  extreme: "extrema",
  severe: "grave",
  moderate: "moderada",
  minor: "leve",
  unknown: "sin datos",
};

const ESTADO_NWS_ES: Record<string, string> = {
  actual: "vigente",
  test: "prueba",
  draft: "borrador",
  exercise: "ejercicio",
  system: "sistema",
};

const TIPO_GDACS_ES: Record<string, string> = {
  TC: "ciclón tropical",
  FL: "inundación",
  EQ: "terremoto",
  VO: "volcán",
  DR: "sequía",
  WF: "incendio forestal",
  TS: "tsunami",
  FR: "incendio forestal",
};

const CATEGORIA_EONET_ES: Record<string, string> = {
  wildfires: "incendios",
  volcanoes: "volcanes",
  floods: "inundaciones",
  severeStorms: "tormentas severas",
  seaLakeIce: "hielo marino",
  drought: "sequía",
  dustHaze: "polvo y calima",
  earthquakes: "terremotos",
  landslides: "deslizamientos",
  manmade: "antrópico",
  snow: "nieve",
  temperatureExtremes: "temperaturas extremas",
  waterColor: "color del agua",
};

const DIA_NOCHE_ES: Record<string, string> = {
  D: "día",
  N: "noche",
  day: "día",
  night: "noche",
};

const CONFIANZA_ES: Record<string, string> = {
  high: "alta",
  nominal: "nominal",
  low: "baja",
};

function payloadOf(ev: any): Record<string, any> {
  const raw = ev?.payload;
  if (!raw) return {};
  if (typeof raw === "string") {
    try {
      const parsed = JSON.parse(raw);
      return parsed && typeof parsed === "object" ? parsed : {};
    } catch {
      return {};
    }
  }
  return typeof raw === "object" ? raw : {};
}

function decimal(value: unknown, digits = 1): string | null {
  const n = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(n)) return null;
  return n.toLocaleString("es-ES", { maximumFractionDigits: digits });
}

function asText(value: unknown): string | null {
  if (value === null || value === undefined || value === "") return null;
  if (typeof value === "boolean") return value ? "Sí" : "No";
  if (typeof value === "number") return Number.isFinite(value) ? decimal(value, 2) : null;
  if (Array.isArray(value)) {
    const parts = value.map(asText).filter((v): v is string => Boolean(v));
    return parts.length ? parts.join(" · ") : null;
  }
  if (typeof value === "object") {
    const obj = value as Record<string, unknown>;
    const name = obj.name ?? obj.label ?? obj.title ?? obj.countryname ?? obj.iso3 ?? obj.id;
    return name === undefined ? null : asText(name);
  }
  const text = String(value).trim();
  return text || null;
}

function mapped(value: unknown, table: Record<string, string>): string | null {
  const text = asText(value);
  if (!text) return null;
  return table[text] ?? table[text.toLowerCase()] ?? text;
}

function signed(value: unknown): string | null {
  const n = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(n)) return null;
  return `${n >= 0 ? "+" : ""}${n.toLocaleString("es-ES", { maximumFractionDigits: 2 })}`;
}

function yesNo(value: unknown): string | null {
  if (value === null || value === undefined || value === "") return null;
  if (typeof value === "boolean") return value ? "Sí" : "No";
  const n = Number(value);
  if (Number.isFinite(n) && (value === 0 || value === 1 || value === "0" || value === "1")) {
    return n ? "Sí" : "No";
  }
  return asText(value);
}

function dateText(value: unknown): string | null {
  const text = asText(value);
  if (!text) return null;
  const date = new Date(text.endsWith("Z") || text.includes("+") ? text : `${text}Z`);
  if (Number.isNaN(date.getTime())) return text;
  return date.toLocaleString("es-ES", {
    day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

/** Resumen de la fuente con los códigos más habituales traducidos al español. */
export function eventSummary(ev: any): string {
  const raw = String(ev?.summary ?? "").trim();
  if (!raw) return "";
  const cat = String(ev?.category ?? "").toLowerCase();
  if (cat !== "trafico" && String(ev?.source ?? "").toLowerCase() !== "dgt") return raw;
  return raw
    .replace(/\b(vehicleObstruction|roadMaintenance|maintenanceWorks|infrastructureDamageObstruction|environmentalObstruction|abnormalTraffic|weatherCondition|publicEvent|authorityOperation)\b/g,
      (code) => CAUSA_ES[code] ?? code)
    .replace(/\b(northEastBound|northWestBound|southEastBound|southWestBound|northBound|southBound|eastBound|westBound|bothDirections)\b/g,
      (code) => SENTIDO_ES[code] ?? code)
    .replace(/\b(active|planned|suspended|finished|closed)\b/g,
      (code) => VALIDEZ_ES[code] ?? code);
}

/**
 * Lista ordenada de hechos. Solo aparecen claves que la fuente ha enviado de
 * verdad; si no hay payload, la lista queda vacía y la ficha mantiene el
 * titular y el resumen.
 */
export function eventFacts(ev: any): EventFact[] {
  const p = payloadOf(ev);
  const facts: EventFact[] = [];
  const add = (label: string, value: unknown) => {
    const text = asText(value);
    if (!text) return;
    if (facts.some((f) => f.label === label)) return;
    facts.push({ label, value: text });
  };

  /* DGT · incidencias de tráfico */
  if (p.causa || p.cause) add("Causa", mapped(p.causa ?? p.cause, CAUSA_ES));
  add("Carretera", p.carretera ?? p.road ?? p.roadName);
  add("Punto kilométrico", p.km ? `km ${asText(p.km)}` : null);
  add("Municipio", p.municipio);
  add("Provincia", p.provincia);
  add("Comunidad", p.comunidad);
  add("Sentido", mapped(p.direccion ?? p.direction, SENTIDO_ES));
  add("Estado", mapped(p.validez ?? p.validity, VALIDEZ_ES));

  /* Sismos · USGS / EMSC */
  if (p.mag !== undefined || p.magnitude !== undefined) {
    add("Magnitud", decimal(p.mag ?? p.magnitude, 1));
  }
  add("Tipo de magnitud", p.magtype ?? p.magType);
  add("Personas que lo sintieron", p.felt);
  add("Riesgo de tsunami", yesNo(p.tsunami));
  add("Alerta sísmica", mapped(p.alert, ALERTA_ES));
  add("Significancia", p.sig);
  add("Intensidad MMI", p.mmi);
  add("Red", p.agency ?? p.source);
  add("Región", p.region);

  /* GDACS · desastres */
  add("Tipo de evento", mapped(p.eventtype, TIPO_GDACS_ES));
  add("Nivel de alerta", mapped(p.alertlevel, ALERTA_ES));
  add("Puntuación de alerta", p.alertscore);
  add("Alerta del episodio", mapped(p.episodealertlevel, ALERTA_ES));
  add("Severidad", [asText(p.severitytext), asText(p.severityunit)].filter(Boolean).join(" "));
  add("Países afectados", p.affectedcountries);
  add("Episodio vigente", yesNo(p.iscurrent));

  /* NASA FIRMS · incendios */
  if (p.frp_mw !== undefined) add("Potencia radiativa (FRP)", `${decimal(p.frp_mw, 1)} MW`);
  if (p.brightness_k !== undefined) add("Temperatura de brillo", `${decimal(p.brightness_k, 1)} K`);
  add("Confianza de detección", [mapped(p.confidence, CONFIANZA_ES), p.confidence_pct ? `${asText(p.confidence_pct)} %` : ""].filter(Boolean).join(" · "));
  add("Satélite", p.satellite);
  add("Instrumento", p.instrument);
  add("Día/noche", mapped(p.daynight, DIA_NOCHE_ES));

  /* NWS · avisos meteorológicos */
  add("Fenómeno", p.event);
  add("Certeza", mapped(p.certainty, CERTEZA_ES));
  add("Urgencia", mapped(p.urgency, URGENCIA_ES));
  add("Gravedad del aviso", mapped(p.severity, GRAVEDAD_NWS_ES));
  add("Estado del aviso", mapped(p.status, ESTADO_NWS_ES));
  add("Área", p.area);
  add("Emisor", p.sender);
  add("Finaliza", dateText(p.ends));

  /* GDELT · prensa */
  add("Actores", p.actors);
  add("Código CAMEO", p.eventcode);
  add("Código raíz", p.rootcode);
  add("Escala Goldstein", signed(p.goldstein));
  add("Tono informativo", signed(p.tone));
  add("Menciones en prensa", p.mentions);
  add("Medios citados", p.sources);
  add("Lugar", p.place);

  /* NASA EONET · eventos naturales */
  add("Categorías", Array.isArray(p.categories)
    ? p.categories.map((c: unknown) => CATEGORIA_EONET_ES[String(c)] ?? String(c))
    : p.categories);
  add("Geometría", p.geometry_type === "Point" ? "punto" : p.geometry_type === "Polygon" ? "polígono" : p.geometry_type);
  add("Fuentes EONET", p.sources);
  add("Cerrado", p.closed ? dateText(p.closed) : null);

  /* IODA · cortes de internet */
  const ioda = p.ioda && typeof p.ioda === "object" ? p.ioda as Record<string, unknown> : null;
  add("Entidad medida", ioda?.entityName ?? ioda?.entityCode);
  add("Puntuación IODA", ioda?.score ?? ioda?.level);
  add("Señal", p.datasource ?? ioda?.datasource);

  /* Renfe · incidencias de servicio */
  add("Línea", p.linea);
  add("Rutas", p.routes);

  return facts;
}
