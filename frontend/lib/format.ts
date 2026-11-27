export const CATEGORY_META: Record<string, { label: string; color: string; icon: string }> = {
  earthquake: { label: "Sismos", color: "#ff7a45", icon: "◉" },
  disaster: { label: "Desastres", color: "#ff3d71", icon: "▲" },
  wildfire: { label: "Incendios", color: "#ffb703", icon: "✹" },
  conflict: { label: "Conflicto", color: "#ff2d2d", icon: "⚔" },
  protest: { label: "Protestas", color: "#b388ff", icon: "✊" },
  military: { label: "Militar", color: "#4dd0e1", icon: "✈" },
  diplomacy: { label: "Diplomacia", color: "#64b5f6", icon: "◈" },
  economy: { label: "Economía", color: "#a5d6a7", icon: "⬢" },
  news: { label: "Noticias", color: "#90a4ae", icon: "◌" },
  health: { label: "Salud", color: "#69f0ae", icon: "✚" },
  weather: { label: "Meteorología", color: "#4fc3f7", icon: "☁" },
  flood: { label: "Inundación", color: "#4dd0e1", icon: "≈" },
  volcano: { label: "Volcán", color: "#ff8a65", icon: "▲" },
  cyber: { label: "Ciberataque", color: "#ce93d8", icon: "⌘" },
  trafico: { label: "Tráfico", color: "#ffd166", icon: "⛗" },
  transporte: { label: "Transporte", color: "#ffb454", icon: "⛉" },
  network: { label: "Red / Internet", color: "#7c9cff", icon: "⌁" },
};

/** Qué significa cada categoría, para explicarlo dentro de la ficha. */
export const CATEGORY_DESC: Record<string, string> = {
  earthquake: "Movimiento sísmico localizado por redes sismológicas (USGS, EMSC). La magnitud mide la energía liberada.",
  disaster: "Desastre natural declarado o monitorizado por GDACS/EONET: ciclones, inundaciones, sequías, erupciones.",
  wildfire: "Foco de calor activo detectado por satélite (NASA FIRMS · VIIRS y MODIS). La potencia radiativa (FRP) indica intensidad.",
  conflict: "Enfrentamiento armado, ataque o acción violenta detectada en prensa y codificada con CAMEO (GDELT).",
  protest: "Protesta, manifestación o disturbio social detectado en prensa (GDELT).",
  military: "Movimiento o despliegue militar, ejercicios o incidentes con fuerzas armadas.",
  diplomacy: "Declaración, acuerdo, reunión o tensión diplomática entre países u organizaciones.",
  economy: "Hecho económico o comercial: sanciones, huelgas, quiebras, decisiones de bancos centrales.",
  news: "Suceso de actualidad sin encaje en el resto de categorías.",
  cyber: "Incidentes de ciberseguridad relevantes.",
  volcano: "Actividad volcánica: erupciones, ceniza y alertas.",
  flood: "Inundaciones y crecidas fluviales monitorizadas.",
  weather: "Avisos meteorológicos severos y episodios de tiempo extremo.",
  health: "Brotes, alertas sanitarias y emergencias de salud pública.",
  trafico: "Incidencia de tráfico en tiempo real publicada por la DGT (DATEX II): accidentes, obras, cortes, obstáculos y restricciones, con carretera y punto kilométrico.",
  transporte: "Aviso de servicio de un operador de transporte público (Renfe): reajustes, obras y cancelaciones que afectan a una línea.",
  network: "Caída de alcanzabilidad de internet medida por IODA (Georgia Tech) con tres señales independientes: BGP, sondas activas y telescopio de red. No es una denuncia: es una medición por país.",
};

/** Nombre en español de cada fuente de datos. */
export const SOURCE_ES: Record<string, string> = {
  gdelt: "GDELT · prensa mundial",
  usgs: "USGS · sismología EE. UU.",
  emsc: "EMSC · sismología europea",
  gdacs: "GDACS · desastres ONU",
  eonet: "NASA EONET · eventos naturales",
  nws: "NWS · meteorología EE. UU.",
  firms: "NASA FIRMS · incendios",
  adsb: "ADS-B · tráfico aéreo",
  ais: "AIS · tráfico marítimo",
  cameras: "Redes de cámaras públicas",
  air: "OpenAQ · calidad del aire",
  satellites: "CelesTrak · órbitas",
  osint: "Consolidado multi-fuente",
  ioda: "IODA · cortes de internet",
};

export function sourceEs(src?: string | null): string {
  if (!src) return "—";
  return SOURCE_ES[String(src).toLowerCase()] ?? String(src);
}

/** Fecha y hora exactas: hora local del dispositivo y UTC. */
export function fechaExacta(iso?: string | null): { local: string; utc: string } {
  if (!iso) return { local: "—", utc: "—" };
  const t = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : iso + "Z");
  if (Number.isNaN(t.getTime())) return { local: String(iso), utc: "—" };
  const local = t.toLocaleString("es-ES", {
    weekday: "short", day: "2-digit", month: "short", year: "numeric",
    hour: "2-digit", minute: "2-digit", second: "2-digit",
  });
  return { local, utc: `${t.toISOString().slice(0, 19).replace("T", " ")} UTC` };
}

export const SEVERITY_COLOR: Record<string, string> = {
  red: "#ff2d55",
  critical: "#ff2d55",
  orange: "#ff9f0a",
  high: "#ff9f0a",
  yellow: "#ffd60a",
  green: "#30d158",
  info: "#64d2ff",
};

export function timeAgo(iso: string): string {
  const then = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : iso + "Z").getTime();
  const diff = Math.max(0, Date.now() - then) / 1000;
  if (diff < 60) return `${Math.round(diff)}s`;
  if (diff < 3600) return `${Math.round(diff / 60)}m`;
  if (diff < 86400) return `${Math.round(diff / 3600)}h`;
  return `${Math.round(diff / 86400)}d`;
}

export function utcClock(d: Date = new Date()): string {
  return d.toISOString().slice(11, 19) + "Z";
}

export function fmtNumber(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  if (Math.abs(n) >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (Math.abs(n) >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

export function fmtDistance(m: number): string {
  return m >= 1000 ? `${(m / 1000).toFixed(1)} km` : `${Math.round(m)} m`;
}

export function categoryMeta(cat: string) {
  return CATEGORY_META[cat] ?? { label: cat, color: "#8ea0b5", icon: "•" };
}

/** Minimal markdown renderer (headings, bold, italics, lists, hr, links) —
 *  enough for AI briefings without pulling a dependency. */
export function markdownToHtml(md: string): string {
  const esc = (s: string) =>
    s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const inline = (s: string) =>
    esc(s)
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/(^|[\s(])\*(?!\s)(.+?)\*/g, "$1<em>$2</em>")
      .replace(/`(.+?)`/g, "<code>$1</code>")
      .replace(/\[(E\d+)\]/g, '<a class="cite" data-ref="$1">[$1]</a>')
      .replace(/\[(.+?)\]\((https?:\/\/.+?)\)/g, '<a href="$2" target="_blank" rel="noreferrer">$1</a>');

  const lines = md.split("\n");
  const out: string[] = [];
  let inList = false;
  const closeList = () => {
    if (inList) {
      out.push("</ul>");
      inList = false;
    }
  };
  for (const raw of lines) {
    const line = raw.trimEnd();
    if (/^###\s+/.test(line)) {
      closeList();
      out.push(`<h3>${inline(line.replace(/^###\s+/, ""))}</h3>`);
    } else if (/^##\s+/.test(line)) {
      closeList();
      out.push(`<h2>${inline(line.replace(/^##\s+/, ""))}</h2>`);
    } else if (/^#\s+/.test(line)) {
      closeList();
      out.push(`<h1>${inline(line.replace(/^#\s+/, ""))}</h1>`);
    } else if (/^---+$/.test(line.trim())) {
      closeList();
      out.push("<hr/>");
    } else if (/^\s*[-*]\s+/.test(line)) {
      if (!inList) {
        out.push("<ul>");
        inList = true;
      }
      out.push(`<li>${inline(line.replace(/^\s*[-*]\s+/, ""))}</li>`);
    } else if (line.trim() === "") {
      closeList();
    } else {
      closeList();
      out.push(`<p>${inline(line)}</p>`);
    }
  }
  closeList();
  return out.join("\n");
}

/** Los mensajes de error del backend llegan con el nombre de la excepción en
 * inglés (RuntimeError, TimeoutError…): se muestran en español llano. */
export function esError(msg?: string | null): string {
  if (!msg) return "";
  if (/https?:\/\//.test(msg)) return "Fallo: la fuente externa no respondió";
  const limpio = msg.replace(/^([A-Za-z_.]*(Error|Exception)):\s*/, "").trim();
  return limpio ? `Fallo: ${limpio}` : "Fallo al consultar la fuente";
}
