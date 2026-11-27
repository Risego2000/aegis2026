export type EventFeature = {
  type: "Feature";
  geometry: { type: string; coordinates: any };
  properties: {
    id: string;
    cluster_id: string;
    source: string;
    sources: string[];
    category: string;
    subtype: string;
    title: string;
    summary: string;
    depth_km: number | null;
    severity: number | null;
    severity_label: string;
    country: string;
    iso3: string;
    event_time: string;
    first_seen: string;
    updated_at: string;
    url: string;
    mentions: number;
    sources_count: number;
    confidence: number;
    payload: Record<string, any>;
  };
};

export type FeatureCollection = {
  type: "FeatureCollection";
  count: number;
  features: EventFeature[];
  numbers?: {
    total: number;
    by_category: Record<string, number>;
    by_severity: Record<string, number>;
    by_country: Record<string, number>;
    multi_source: number;
    mentions: number;
  };
};

export type LiveCollection = {
  type: "FeatureCollection";
  count: number;
  updated_at: string;
  features: { type: "Feature"; geometry: { type: "Point"; coordinates: [number, number] }; properties: Record<string, any> }[];
  stats?: Record<string, any>;
};

export type Alert = {
  ts: string;
  fence_id: string | null;
  fence_name?: string;
  actor_id: string;
  actor_type: string;
  event_type: string;
  severity: string;
  title: string;
  message: string;
  lat: number | null;
  lon: number | null;
  payload: Record<string, any>;
};

export type SourceStatus = {
  name: string;
  enabled: boolean;
  active?: boolean;
  key_optional?: boolean;
  interval_s: number;
  kind: string;
  last_run: string | null;
  ok: boolean;
  message: string;
  items: number;
  duration_ms: number;
  runs: number;
  failures: number;
  next_run_s: number;
  source?: string;
  description?: string;
  url?: string;
  mode?: string;
  needs_key?: boolean;
};

export type Health = {
  status: string;
  storage: {
    backend: string;
    events: number;
    events_24h: number;
    by_category: Record<string, number>;
    mentions: number;
    infrastructure: number;
    multi_source_events: number;
  };
  ingest: { uptime_s: number; sources: SourceStatus[]; live: Record<string, any> };
  fence: {
    engine: string;
    fences: number;
    tracked_objects: number;
    counters: Record<string, number>;
    subscribers: number;
    rules: Record<string, string>;
  };
  live: Record<string, { name: string; count: number; updated_at?: string | null }>;
  version: string;
};

export type AppConfig = {
  categories: string[];
  rules: Record<string, string>;
  ai: { provider: string; model: string; available: boolean; detail: string };
  sources: Record<string, boolean>;
  hotspots: Record<string, { lat: number; lon: number; radius_nm: number }>;
  fence_engine: string;
  storage: string;
};

export type Briefing = {
  markdown: string;
  provider: string;
  llm_available: boolean;
  ai_status: { provider: string; model: string; available: boolean; detail: string };
  window: string;
  bbox: number[] | null;
  event_count: number;
  numbers: FeatureCollection["numbers"];
  citations: { ref: string; id: string; title: string; category: string; lat: number; lon: number; url: string }[];
  generated_at: string;
};

export type NearbyHit = {
  id: string;
  name: string;
  kind: string;
  subtype: string;
  country: string;
  iso3: string;
  lat: number;
  lon: number;
  population: number;
  distance_m: number;
};

export type Fence = {
  id: string;
  name: string;
  kind: string;
  lat: number | null;
  lon: number | null;
  radius_m: number | null;
  rules: string[];
  active: boolean;
};

/** Elemento móvil seleccionado en el mapa (aeronave, buque o satélite). */
export type ActorKind = "aircraft" | "vessels" | "satellites" | "air" | "trains";

export type ActorDetail = {
  kind: ActorKind;
  actor: Record<string, any>;
  history?: { ts: number; lat: number; lon: number; altitude_ft?: number; speed_kn?: number }[];
  // satélites
  name?: string;
  norad?: number;
  lat?: number;
  lon?: number;
  altitude_km?: number;
  orbit?: Record<string, any>;
  state?: Record<string, any>;
  tle?: string[];
  tle_age_min?: number;
  groups?: string[];
};

export type ActorTrack = {
  kind?: string;
  id?: string;
  points: number;
  distance_km?: number;
  geometry: { type: "LineString"; coordinates: [number, number][] };
};
