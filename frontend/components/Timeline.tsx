"use client";

import { useMemo } from "react";
import type { EventFeature } from "@/lib/types";
import { categoryMeta, fmtNumber, timeAgo } from "@/lib/format";

type Props = {
  events: EventFeature[];
  hours: number;
  setHours: (h: number) => void;
  onSelect: (f: EventFeature) => void;
  alertsCount: number;
  onOpenAlerts: () => void;
};

export default function Timeline({ events, hours, setHours, onSelect, alertsCount, onOpenAlerts }: Props) {
  const bins = useMemo(() => {
    const buckets = 48;
    const span = hours * 3600 * 1000;
    const now = Date.now();
    const arr = new Array(buckets).fill(0);
    for (const f of events) {
      const t = new Date(f.properties.event_time).getTime();
      if (Number.isNaN(t)) continue;
      const idx = Math.floor(((t - (now - span)) / span) * buckets);
      if (idx >= 0 && idx < buckets) arr[idx] += 1;
      else if (idx >= buckets) arr[buckets - 1] += 1;
    }
    return arr;
  }, [events, hours]);

  const max = Math.max(1, ...bins);
  const latest = useMemo(
    () =>
      [...events]
        .sort((a, b) => new Date(b.properties.event_time).getTime() - new Date(a.properties.event_time).getTime())
        .slice(0, 6),
    [events]
  );

  return (
    <footer className="timeline">
      <div className="timeline-hist-wrap">
        <span className="tiny faint mono" style={{ letterSpacing: "0.14em" }}>DENSIDAD {hours}H</span>
        <div className="timeline-hist" title="Eventos por franja temporal">
          {bins.map((v, i) => (
            <div
              key={i}
              className="hist-bar"
              style={{
                height: `${Math.max(2, (v / max) * 100)}%`,
                background: v === max && v > 0 ? "rgba(255,61,113,0.65)" : undefined,
                opacity: 0.35 + (i / bins.length) * 0.65,
              }}
              title={`${v} eventos`}
            />
          ))}
        </div>
      </div>

      <div style={{ display: "flex", gap: 4, flex: "0 0 auto" }}>
        {[15 / 60, 1, 6, 24, 72, 168].map((h) => (
          <button key={h} className={`chip ${hours === h ? "active" : ""}`} onClick={() => setHours(h)}>
            {h < 1 ? "AHORA" : h < 24 ? `${h}H` : `${h / 24}D`}
          </button>
        ))}
      </div>

      <div className="ticker">
        <span className="ticker-label">ÚLTIMOS</span>
        <div className="ticker-text">
          {latest.map((f, i) => (
            <span key={f.properties.id}>
              {i > 0 && <span className="faint"> · </span>}
              <span
                style={{ color: categoryMeta(f.properties.category).color, cursor: "pointer" }}
                onClick={() => onSelect(f)}
                title={f.properties.title}
              >
                {f.properties.title.slice(0, 74)} ({timeAgo(f.properties.event_time)})
              </span>
            </span>
          ))}
          {latest.length === 0 && <span className="faint">sin eventos en la ventana del mapa</span>}
        </div>
      </div>

      <button className="btn" onClick={onOpenAlerts} style={{ flex: "0 0 auto" }}>
        <span className="status-dot" style={{ background: alertsCount ? "#ff3d71" : "#4d5d70" }} />
        Alertas {alertsCount ? <span className="mono">{fmtNumber(alertsCount)}</span> : null}
      </button>
    </footer>
  );
}
