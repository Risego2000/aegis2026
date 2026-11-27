/** Thin typed client. All URLs are relative: FastAPI serves this bundle and the
 *  API from the same origin, so there is no CORS configuration to get wrong.
 *
 *  Cuando el cliente se publica como sitio estático (GitHub Pages) no hay
 *  backend en ese origen. El origen de la API se resuelve en este orden:
 *
 *    1. `?api=https://mi-backend` en la URL del mapa  (cambio inmediato, sin
 *       recompilar: sirve para repuntar un sitio ya publicado a un túnel nuevo)
 *    2. `runtime-config.json` junto al cliente        (un fichero, no un build)
 *    3. `NEXT_PUBLIC_AEGIS_API` en tiempo de compilación (valor por defecto)
 *    4. nada → rutas relativas y todo contra el mismo origen
 *
 *  `assetUrl()` añade el prefijo del sitio cuando se publica en un
 *  subdirectorio (`NEXT_BASE_PATH`), que es lo que rompía el manifest, el icono
 *  y el service worker en GitHub Pages. */

const BUILD_API = (process.env.NEXT_PUBLIC_AEGIS_API || "").replace(/\/+$/, "");
const BASE_PATH = (process.env.NEXT_PUBLIC_BASE_PATH || "").replace(/\/+$/, "");

let apiBase = BUILD_API;

/** Ruta de un recurso propio del cliente (icono, manifest, service worker). */
export const assetUrl = (path: string) => `${BASE_PATH}${path}`;

/** URL de un endpoint de la API: absoluta si hay backend externo, relativa si no. */
export const apiUrl = (path: string) =>
  apiBase && path.startsWith("/") ? apiBase + path : path;

/** Origen de la API en uso (cadena vacía = mismo origen). Para diagnóstico. */
export const apiOrigin = () => apiBase;

function sanitize(raw: unknown): string {
  if (typeof raw !== "string" || !raw.trim()) return "";
  try {
    const parsed = new URL(raw.trim(), typeof window === "undefined" ? "http://localhost" : window.location.href);
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return "";
    return `${parsed.origin}${parsed.pathname}`.replace(/\/+$/, "");
  } catch {
    return "";
  }
}

let configPromise: Promise<void> | null = null;

function announce() {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent("aegis:api-ready", { detail: { apiBase } }));
}

/** Resuelve el origen de la API una sola vez por carga de página. */
export function ensureApiConfig(): Promise<void> {
  if (configPromise) return configPromise;
  configPromise = (async () => {
    if (typeof window === "undefined") return;
    // 1. parámetro de la URL: la vía rápida para repuntar sin desplegar
    const fromQuery = sanitize(new URLSearchParams(window.location.search).get("api"));
    if (fromQuery) {
      apiBase = fromQuery;
      announce();
      return;
    }
    // 2. fichero de configuración servido junto al cliente
    try {
      const res = await fetch(assetUrl("/runtime-config.json"), { cache: "no-store" });
      if (!res.ok) return;
      const data = await res.json();
      const fromFile = sanitize(data?.api);
      if (fromFile) {
        apiBase = fromFile;
        announce();
      }
    } catch {
      /* sin fichero (o bloqueado): se queda el valor de compilación */
    }
  })();
  return configPromise;
}

if (typeof window !== "undefined") void ensureApiConfig();

import type {
  AppConfig, Alert, Briefing, FeatureCollection, Fence, Health, LiveCollection, NearbyHit,
} from "./types";

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  await ensureApiConfig();
  const res = await fetch(apiUrl(path), { ...init, headers: { "Content-Type": "application/json", ...(init?.headers || {}) } });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`${res.status} ${res.statusText} — ${text.slice(0, 200)}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  config: () => json<AppConfig>("/api/config"),
  health: () => json<Health>("/api/health"),
  stats: () => json<any>("/api/stats"),

  events: (params: {
    bbox?: [number, number, number, number] | null;
    categories?: string[];
    sources?: string[];
    hours: number;
    limit?: number;
    q?: string;
    since?: string | null;
  }) => {
    const search = new URLSearchParams();
    if (params.since) search.set("since", params.since);
    if (params.bbox) search.set("bbox", params.bbox.map((v) => v.toFixed(3)).join(","));
    if (params.categories?.length) search.set("categories", params.categories.join(","));
    if (params.sources?.length) search.set("sources", params.sources.join(","));
    search.set("hours", String(params.hours));
    search.set("limit", String(params.limit ?? 6000));
    if (params.q) search.set("q", params.q);
    return json<FeatureCollection>(`/api/events?${search.toString()}`);
  },

  refreshAircraft: (lat: number, lon: number, radius = 250) =>
    json<{ ok: boolean; updated: number; count: number }>(
      `/api/live/aircraft/refresh?lat=${lat.toFixed(3)}&lon=${lon.toFixed(3)}&radius=${radius}`,
    ),

  actorDetail: (kind: "aircraft" | "vessels" | "satellites" | "air" | "trains", id: string) =>
    json<any>(`/api/live/${kind}/${encodeURIComponent(id)}`),
  actorTrack: (kind: "aircraft" | "vessels" | "satellites" | "air" | "trains", id: string, minutes = 60) =>
    json<any>(`/api/live/${kind}/${encodeURIComponent(id)}/track?minutes=${minutes}`),

  photo: (kind: string, id: string) =>
    json<{ photo: { url: string; proxy?: string; credit: string; link: string; source: string; note?: string } | null }>(
      `/api/media/photo?kind=${encodeURIComponent(kind)}&id=${encodeURIComponent(id)}`
    ),

  event: (id: string) => json<{ event: any; mentions: any[] }>(`/api/events/${encodeURIComponent(id)}`),
  nearby: (id: string, radiusKm: number) =>
    json<{ count: number; population_exposed: number; hits: NearbyHit[]; query: string }>(
      `/api/events/${encodeURIComponent(id)}/nearby?radius_km=${radiusKm}&limit=60`
    ),

  aircraft: () => json<LiveCollection>("/api/live/aircraft"),
  trains: () => json<LiveCollection>("/api/live/trains"),
  air: () => json<LiveCollection>("/api/live/air"),
  cameras: () => json<LiveCollection & { networks: any[] }>("/api/cameras?limit=20000"),
  camera: (id: string) => json<{ camera: any; frame_url: string }>(`/api/cameras/${encodeURIComponent(id)}`),
  vessels: () => json<LiveCollection>("/api/live/vessels"),
  satellites: () => json<LiveCollection>("/api/live/satellites"),
  orbit: (norad: number) =>
    json<{ norad: number; geometry: { type: "LineString"; coordinates: number[][] } }>(
      `/api/live/satellites/${norad}/orbit`
    ),

  fences: () => json<{ engine: string; fences: any; definitions: Fence[] }>("/api/fences"),
  createFence: (body: { name?: string; lat: number; lon: number; radius_m: number; rules?: string[] }) =>
    json<{ ok: boolean; fence: Fence }>("/api/fences", { method: "POST", body: JSON.stringify(body) }),
  deleteFence: (id: string) => json<{ ok: boolean }>(`/api/fences/${encodeURIComponent(id)}`, { method: "DELETE" }),

  alerts: () => json<{ alerts: Alert[]; live?: Alert[]; counters: Record<string, number> }>("/api/alerts?limit=250"),
  briefing: (body: { bbox: number[]; hours: number; categories?: string[]; window?: string; use_llm?: boolean }) =>
    json<Briefing>("/api/ai/briefing", { method: "POST", body: JSON.stringify(body) }),
  aiStatus: () => json<{ provider: string; model: string; available: boolean; detail: string }>("/api/ai/status"),
  trigger: (name: string) => json<any>(`/api/ingest/${name}/run`, { method: "POST" }),
};

export function wsUrl(path = "/ws/alerts"): string {
  // con la API en otro origen (sitio estático) el canal también va allí
  if (apiBase) return apiBase.replace(/^http/, "ws") + path;
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}${path}`;
}
