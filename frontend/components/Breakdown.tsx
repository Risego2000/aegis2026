"use client";

/**
 * Desglose de un número.
 *
 * Todo contador de la interfaz (items de una fuente, categoría, cúmulo del mapa)
 * abre esta hoja con los elementos reales que lo componen: título, fuente,
 * instante y coordenadas. Al pulsar una fila se selecciona ese elemento en el
 * mapa y se abre su ficha completa.
 */

import { useEffect, useMemo, useState } from "react";

import { api } from "@/lib/api";
import { categoryMeta, fmtNumber, timeAgo } from "@/lib/format";
import { Icon } from "@/components/Icon";
import type { LiveCollection } from "@/lib/types";

export type BreakdownItem = {
  id: string;
  title: string;
  sub?: string;
  meta?: string;
  color?: string;
  lat?: number;
  lon?: number;
};

export type BreakdownKind = "events" | "aircraft" | "vessels" | "satellites" | "inline";

export type BreakdownSpec = {
  kind: BreakdownKind;
  title: string;
  subtitle?: string;
  /** ventana temporal declarada en la cabecera (p. ej. «últimos 30 días») */
  window?: string;
  filters?: {
    sources?: string[];
    categories?: string[];
    hours?: number;
    q?: string;
    bbox?: [number, number, number, number];
  };
  /** elementos ya en memoria (cúmulo del mapa) */
  items?: BreakdownItem[];
  /** colección viva ya sondeada (aeronaves, buques, satélites) */
  live?: LiveCollection | null;
  /** acción extra de la cabecera (acercar el cúmulo) */
  zoomTo?: () => void;
};

type Props = {
  spec: BreakdownSpec | null;
  onClose: () => void;
  onPick: (item: BreakdownItem) => void;
};

const PAGE = 120;

function actorLabel(kind: string): string {
  if (kind === "aircraft") return "aeronave";
  if (kind === "vessels") return "buque";
  if (kind === "satellites") return "satélite";
  return "elemento";
}

/** Tope de filas derivadas de una capa viva: el resto se alcanza con la búsqueda. */
const ACTOR_CAP = 600;

function actorItems(live: LiveCollection | null): BreakdownItem[] {
  return (live?.features ?? []).slice(0, ACTOR_CAP).map((f) => {
    const p: any = f.properties ?? {};
    const [lon, lat] = f.geometry.coordinates;
    const tag =
      p.callsign || p.name || p.ship_type || p.mmsi || p.norad || p.id || "—";
    const bits = [
      p.flag || p.origin_country || p.country,
      p.alt_baro !== undefined ? `${Math.round(Number(p.alt_baro))} ft` : null,
      p.gs !== undefined ? `${Math.round(Number(p.gs))} kt` : null,
      p.sog !== undefined ? `${Number(p.sog).toFixed(1)} kn` : null,
      p.ship_type || null,
      p.operator || null,
    ].filter(Boolean);
    return {
      id: String(p.id ?? p.norad ?? p.mmsi ?? ""),
      title: String(tag),
      sub: bits.join(" · ") + ` · ${lat.toFixed(2)}, ${lon.toFixed(2)}`,
      lat,
      lon,
      color: "#a5e8ff",
      meta: p.seen_at || p.updated_at ? timeAgo(p.seen_at ?? p.updated_at) : undefined,
    };
  });
}

/** Convierte un Feature de evento en una fila del desglose. */
export function eventFeatureToItem(f: any): BreakdownItem {
  {
    const p = f.properties ?? {};
    const coords =
      f.geometry?.type === "Point"
        ? f.geometry.coordinates
        : f.geometry?.coordinates?.[0]?.[0] ?? [p.lon, p.lat];
    const meta = categoryMeta(p.category);
    const src = Array.isArray(p.sources) ? p.sources.join(" + ") : p.source;
    return {
      id: String(p.id),
      title: String(p.title ?? p.id),
      sub: [meta.label, src, p.severity_label].filter(Boolean).join(" · "),
      meta: p.event_time ? timeAgo(p.event_time) : undefined,
      color: meta.color,
      lat: coords?.[1],
      lon: coords?.[0],
    };
  }
}

function eventItems(features: any[]): BreakdownItem[] {
  return features.map(eventFeatureToItem);
}

export default function Breakdown({ spec, onClose, onPick }: Props) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fetched, setFetched] = useState<BreakdownItem[]>([]);
  const [query, setQuery] = useState("");
  const [shown, setShown] = useState(PAGE);

  /* carga (solo cuando el desglose necesita red) */
  useEffect(() => {
    setQuery("");
    setShown(PAGE);
    setError(null);
    setFetched([]);
    if (!spec) return;
    if (spec.kind === "inline" || spec.kind === "aircraft" || spec.kind === "vessels" || spec.kind === "satellites") {
      return;
    }
    let alive = true;
    setLoading(true);
    api
      .events({
        hours: spec.filters?.hours ?? 720,
        bbox: spec.filters?.bbox,
        categories: spec.filters?.categories,
        sources: spec.filters?.sources,
        q: spec.filters?.q,
        limit: 20000,
      })
      .then((data) => {
        if (alive) setFetched(eventItems(data.features ?? []));
      })
      .catch((err: any) => {
        if (alive) setError(String(err?.message ?? err).slice(0, 160));
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [spec]);

  const all = useMemo<BreakdownItem[]>(() => {
    if (!spec) return [];
    if (spec.kind === "inline") return spec.items ?? [];
    if (spec.kind === "events") return fetched;
    return actorItems(spec.live ?? null);
  }, [spec, fetched]);

  const recortado = useMemo(() => {
    const total = spec?.live?.features?.length ?? 0;
    const listado = all.length;
    return total > listado ? { total, listado } : null;
  }, [spec, all]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return all;
    return all.filter((i) =>
      `${i.title} ${i.sub ?? ""} ${i.id}`.toLowerCase().includes(q)
    );
  }, [all, query]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  if (!spec) return null;

  const noun =
    spec.kind === "events" || spec.kind === "inline"
      ? "elemento"
      : actorLabel(spec.kind);

  return (
    <>
      <div className="breakdown-scrim" onClick={onClose} aria-hidden="true" />
      <section className="breakdown" role="dialog" aria-label={spec.title}>
        <header className="breakdown-head">
          <div style={{ minWidth: 0 }}>
            <div className="breakdown-title">{spec.title}</div>
            <div className="breakdown-sub">
              {loading ? "consultando…" : <><strong>{fmtNumber(filtered.length)}</strong> {noun}{filtered.length === 1 ? "" : "s"}</>}
              {spec.window ? ` · ${spec.window}` : ""}
              {spec.subtitle ? ` · ${spec.subtitle}` : ""}
              {recortado ? ` · mostrando ${fmtNumber(recortado.listado)} de ${fmtNumber(recortado.total)}: usa la búsqueda` : ""}
            </div>
          </div>
          <div style={{ display: "flex", gap: 6, flex: "0 0 auto" }}>
            {spec.zoomTo && (
              <button className="chip" onClick={spec.zoomTo} title="Acercar la vista a este conjunto">
                acercar
              </button>
            )}
            <button className="panel-close" style={{ display: "grid" }} onClick={onClose} aria-label="Cerrar desglose">
              <Icon name="close" size={16} />
            </button>
          </div>
        </header>

        {(spec.kind === "events" || all.length > 40) && (
          <div className="breakdown-search">
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="filtrar por título, fuente o id…"
              spellCheck={false}
            />
          </div>
        )}

        <div className="breakdown-list">
          {loading && <div className="breakdown-empty">consultando el almacén…</div>}
          {error && <div className="breakdown-empty" style={{ color: "var(--danger)" }}>{error}</div>}
          {!loading && !error && filtered.length === 0 && (
            <div className="breakdown-empty">Sin elementos con este criterio.</div>
          )}
          {filtered.slice(0, shown).map((item, i) => (
            <button
              className="bd-item"
              key={`${item.id}-${i}`}
              onClick={() => onPick(item)}
              title="Abrir ficha y centrar en el mapa"
            >
              <span className="bd-dot" style={{ background: item.color ?? "#35e0d0" }} />
              <span className="bd-main">
                <span className="bd-title">{item.title}</span>
                {item.sub && <span className="bd-sub">{item.sub}</span>}
              </span>
              {item.meta && <span className="bd-meta">{item.meta}</span>}
            </button>
          ))}
          {filtered.length > shown && (
            <button className="bd-more" onClick={() => setShown((n) => n + PAGE)}>
              mostrar {Math.min(PAGE, filtered.length - shown)} más · quedan{" "}
              {fmtNumber(filtered.length - shown)}
            </button>
          )}
        </div>
      </section>
    </>
  );
}
