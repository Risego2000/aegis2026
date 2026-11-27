"use client";

/**
 * Piezas compartidas por todas las fichas del panel derecho.
 *
 * La regla es la misma en cada pestaña: primero qué estoy viendo y qué cifras
 * importan; después el detalle. Lo secundario vive en secciones plegables para
 * que la ficha se pueda recorrer de un vistazo.
 */

import { useState, type ReactNode } from "react";
import { Icon, type IconName } from "@/components/Icon";

export function PanelHeader({
  icon,
  eyebrow,
  title,
  subtitle,
  meta,
  actions,
  tone = "var(--accent)",
}: {
  icon: IconName;
  eyebrow: string;
  title: ReactNode;
  subtitle?: ReactNode;
  meta?: ReactNode;
  actions?: ReactNode;
  tone?: string;
}) {
  return (
    <header className="pn-head">
      <div className="pn-head-row">
        <span className="pn-icon" style={{ color: tone }} aria-hidden="true">
          <Icon name={icon} size={18} />
        </span>
        <div className="pn-head-text">
          <div className="pn-eyebrow">{eyebrow}</div>
          <h2 className="pn-title">{title}</h2>
          {subtitle ? <div className="pn-sub">{subtitle}</div> : null}
          {meta ? <div className="pn-meta">{meta}</div> : null}
        </div>
        {actions ? <div className="pn-head-actions">{actions}</div> : null}
      </div>
    </header>
  );
}

export type PanelStat = {
  label: string;
  value: ReactNode;
  hint?: string;
  tone?: string;
};

/** Cuatro cifras como máximo por fila; el resto continúa en la siguiente. */
export function SummaryStrip({ items }: { items: PanelStat[] }) {
  if (!items.length) return null;
  return (
    <div
      className="pn-stats"
      style={{ gridTemplateColumns: `repeat(${Math.min(items.length, 4)}, minmax(0, 1fr))` }}
    >
      {items.map((it) => (
        <div className="pn-stat" key={it.label} title={it.hint ?? `${it.label}: ${String(it.value)}`}>
          <b style={it.tone ? { color: it.tone } : undefined}>{it.value}</b>
          <span>{it.label}</span>
        </div>
      ))}
    </div>
  );
}

/**
 * Sección plegable. `defaultOpen` solo para lo que hay que leer sí o sí; el
 * resto empieza cerrado y muestra su recuento en la cabecera.
 */
export function PanelSection({
  title,
  count,
  hint,
  defaultOpen = false,
  children,
}: {
  title: string;
  count?: ReactNode;
  hint?: string;
  defaultOpen?: boolean;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <section className={`pn-sec ${open ? "open" : ""}`}>
      <button
        type="button"
        className="pn-sec-head"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        <span className="pn-sec-chev" aria-hidden="true">{open ? "▾" : "▸"}</span>
        <span className="pn-sec-title">{title}</span>
        {count !== undefined && count !== null ? <span className="pn-sec-count">{count}</span> : null}
        {!open && hint ? <span className="pn-sec-hint">{hint}</span> : null}
      </button>
      {open ? <div className="pn-sec-body">{children}</div> : null}
    </section>
  );
}
