"use client";

import { useEffect, useMemo, useState } from "react";
import type { AppConfig, Health } from "@/lib/types";
import { fmtNumber, utcClock } from "@/lib/format";
import { Icon } from "@/components/Icon";
import { locateMe } from "@/lib/geo";

export type KpiKey = "view" | "stored" | "aircraft" | "vessels" | "satellites" | "cameras" | "air" | "trains";

type Props = {
  health: Health | null;
  config: AppConfig | null;
  query: string;
  setQuery: (v: string) => void;
  ws: "connecting" | "open" | "closed";
  viewCount: number;
  onOpenLeft: () => void;
  onOpenRight: () => void;
  onHelp: () => void;
  /** cada indicador despliega la lista de lo que cuenta */
  onBreakdown: (key: KpiKey) => void;
  /** copia/abre el enlace de la vista actual */
  onShare?: () => void;
  shareCopied?: boolean;
  /** activa o desactiva los avisos del sistema */
  onToggleNotify?: () => void;
  notifyOn?: boolean;
};

/** Barra superior: identidad, indicadores (todos pulsables), búsqueda, estado en vivo y ayuda. */
export default function TopBar({
  health, query, setQuery, ws, viewCount, onOpenLeft, onOpenRight, onHelp, onBreakdown,
  onShare, shareCopied, onToggleNotify, notifyOn,
}: Props) {
  const [clock, setClock] = useState("--:--:--Z");
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const tick = () => { setClock(utcClock()); setNow(Date.now()); };
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);

  // edad del dato en vivo más reciente: prueba visible de que todo se refresca
  const stamps: number[] = [];
  for (const layer of ["aircraft", "vessels", "trains", "air", "cameras", "satellites"] as const) {
    const raw = (health?.live as any)?.[layer]?.updated_at;
    if (typeof raw === "string" && raw) {
      const t = new Date(raw.endsWith("Z") || raw.includes("+") ? raw : raw + "Z").getTime();
      if (Number.isFinite(t)) stamps.push(t);
    }
  }
  const dataAge = stamps.length ? Math.max(0, Math.round((now - Math.max(...stamps)) / 1000)) : null;
  const hace = dataAge === null ? "—" : dataAge < 60 ? `${dataAge} s` : `${Math.round(dataAge / 60)} min`;

  const sources = health?.ingest.sources ?? [];
  const healthy = sources.filter((s) => s.ok).length;
  const inactive = sources.filter((s) => (s as any).active === false).length;
  const failing = sources.filter((s) => !s.ok).length;

  const kpis = useMemo(() => ([
    { key: "view" as KpiKey, label: "Eventos", value: viewCount, hint: "Eventos OSINT dentro de la vista actual del mapa. Pulsa para ver la lista." },
    { key: "stored" as KpiKey, label: "Archivo", secondary: true, value: health?.storage.events ?? 0, hint: "Eventos consolidados en la base de datos (30 días). Pulsa para ver la lista." },
    { key: "aircraft" as KpiKey, label: "Aeronaves", value: health?.live?.aircraft?.count ?? 0, hint: "Aeronaves recibidas por ADS-B en este momento. Pulsa para ver la lista." },
    { key: "vessels" as KpiKey, label: "Buques", value: health?.live?.vessels?.count ?? 0, hint: "Buques recibidos por AIS en este momento. Pulsa para ver la lista." },
    { key: "satellites" as KpiKey, label: "Satélites", value: health?.live?.satellites?.count ?? 0, hint: "Satélites propagados con elementos orbitales. Pulsa para ver la lista." },
    { key: "cameras" as KpiKey, label: "Cámaras", value: health?.live?.cameras?.count ?? 0, hint: "Cámaras públicas indexadas y su cobertura. Pulsa para ver la lista." },
    { key: "trains" as KpiKey, label: "Trenes", value: (health as any)?.live?.trains?.count ?? 0, hint: "Trenes de Renfe, FGC y Amtrak en circulación ahora mismo (GTFS-Realtime). Pulsa para ver la lista." },
    { key: "air" as KpiKey, label: "Aire", secondary: true, value: health?.live?.air?.count ?? 0, hint: "Sensores de calidad del aire. Pulsa para ver la lista." },
  ]), [viewCount, health]);

  return (
    <header className="topbar">
      <button className="brand" onClick={onOpenLeft} title="Abrir capas, filtros y fuentes">
        <div className="brand-mark" aria-hidden="true"><Icon name="aegis" size={18} /></div>
        <div style={{ textAlign: "left" }}>
          <div className="brand-name">AEGIS</div>
          <div className="brand-sub">Centro de inteligencia abierta</div>
        </div>
      </button>

      <div className="kpis" role="list" aria-label="Indicadores en vivo">
        {kpis.map((k) => (
          <button
            key={k.key}
            className={`kpi clickable ${(k as any).secondary ? "kpi-secondary" : ""}`}
            role="listitem"
            title={k.hint}
            onClick={() => onBreakdown(k.key)}
          >
            <span className="kpi-label">{k.label}</span>
            <span className={`kpi-value ${k.key === "view" ? "accent" : ""}`}>{fmtNumber(k.value)}</span>
          </button>
        ))}
        <div
          className="kpi"
          title={`Fuentes conectadas ahora mismo: ${healthy} de ${sources.length}. ${inactive > 0 ? `${inactive} no tienen clave abierta y no se cuentan.` : "Todas responden sin clave."}`}
        >
          <span className="kpi-label">Fuentes</span>
          <span className="kpi-value">
            <span className={`status-dot ${failing ? "warn" : "ok"}`} style={{ marginRight: 6, verticalAlign: "middle" }} />
            {healthy}/{sources.length || "—"}
          </span>
        </div>
      </div>

      <div className="search" title="Filtra por título, país, categoría o fuente. Escribe «cerca» para ver lo que tienes alrededor.">
        <button
          className="search-me"
          title="Usar mi ubicación: muestra los elementos y sucesos más cercanos a donde estoy"
          aria-label="Usar mi ubicación"
          onClick={() => locateMe()}
        >
          <Icon name="locate" size={16} />
        </button>
        <span className="faint" aria-hidden="true"><Icon name="search" size={16} /></span>
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Buscar evento, país…"
          aria-label="Buscar eventos"
          spellCheck={false}
        />
        {query && (
          <button className="faint tiny" onClick={() => setQuery("")} title="Borrar la búsqueda" aria-label="Borrar búsqueda"><Icon name="close" size={14} /></button>
        )}
      </div>

      <div className="top-actions">
      <span
        className={`live-pill ${ws === "open" ? "" : ws === "connecting" ? "warn" : "err"}`}
        title={`Canal en tiempo real: ${ws === "open" ? "conectado" : ws === "connecting" ? "conectando" : "interrumpido"}`}
      >
        <span className="live-dot" style={{ background: ws === "open" ? "#35d07f" : undefined }} />
        {ws === "open" ? "EN VIVO" : ws === "connecting" ? "CONECTANDO" : "SIN CANAL"}
      </span>

      <div className="tiny faint mono live-age" title={`Último dato recibido de las capas en vivo: hace ${hace}`}>
        datos hace {hace}
      </div>

      <div className="clock" title="Hora universal coordinada (UTC)">{clock}</div>

      {onShare && (
        <button
          className="icon-btn"
          title="Copiar el enlace de esta vista (encuadre, periodo y categorías)"
          onClick={onShare}
          aria-label="Compartir vista"
        >
          <Icon name={shareCopied ? "check" : "share"} size={16} />
        </button>
      )}
      {onToggleNotify && (
        <button
          className={`icon-btn ${notifyOn ? "active" : ""}`}
          title={notifyOn ? "Avisos del sistema activados · pulsa para dejar de recibirlos" : "Avisarme de las alertas aunque no esté mirando"}
          onClick={onToggleNotify}
          aria-label="Avisos del sistema"
        >
          <Icon name={notifyOn ? "bell" : "bellOff"} size={16} />
        </button>
      )}
      <button className="icon-btn mobile-only" title="Capas y filtros" onClick={onOpenLeft} aria-label="Capas y filtros"><Icon name="layers" size={17} /></button>
      <button className="icon-btn mobile-only" title="Panel de análisis" onClick={onOpenRight} aria-label="Panel de análisis"><Icon name="panel" size={17} /></button>
      <button className="icon-btn" title="Cómo funciona la aplicación (guía rápida)" onClick={onHelp} aria-label="Ayuda"><Icon name="help" size={17} /></button>
      </div>
    </header>
  );
}
