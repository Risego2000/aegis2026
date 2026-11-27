/** Thin typed client. All URLs are relative: FastAPI serves this bundle and the
 *  API from the same origin, so there is no CORS configuration to get wrong. */

import type {
  AppConfig, Alert, Briefing, FeatureCollection, Fence, Health, LiveCollection, NearbyHit,
} from "./types";

async function json<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, { ...init, headers: { "Content-Type": "application/json", ...(init?.headers || {}) } });
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

  alerts: () => json<{ alerts: Alert[]; counters: Record<string, number> }>("/api/alerts?limit=120"),
  briefing: (body: { bbox: number[]; hours: number; categories?: string[]; window?: string; use_llm?: boolean }) =>
    json<Briefing>("/api/ai/briefing", { method: "POST", body: JSON.stringify(body) }),
  aiStatus: () => json<{ provider: string; model: string; available: boolean; detail: string }>("/api/ai/status"),
  trigger: (name: string) => json<any>(`/api/ingest/${name}/run`, { method: "POST" }),
};

export function wsUrl(path = "/ws/alerts"): string {
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}${path}`;
}
