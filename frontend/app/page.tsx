"use client";

import dynamic from "next/dynamic";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import Breakdown, { type BreakdownItem, type BreakdownSpec } from "@/components/Breakdown";
import Help from "@/components/Help";
import { Icon } from "@/components/Icon";
import RightPanel, { type Tab } from "@/components/RightPanel";
import type { PlaceData } from "@/components/PlacePanel";
import SidePanel, { BASEMAP_IDS, type LayerCounts } from "@/components/SidePanel";
import Timeline from "@/components/Timeline";
import TopBar from "@/components/TopBar";
import { api, apiUrl, assetUrl, wsUrl } from "@/lib/api";
import { alertKey, mergeAlerts } from "@/lib/alerts";
import { locateMe } from "@/lib/geo";
import { CATEGORY_META, fmtNumber, timeAgo } from "@/lib/format";
import type {
  ActorDetail, ActorKind, ActorTrack, Alert, AppConfig, Briefing, EventFeature, FeatureCollection,
  Fence, Health, LiveCollection,
} from "@/lib/types";

const MapView = dynamic(() => import("@/components/MapView"), {
  ssr: false,
  loading: () => (
    <div style={{ display: "grid", placeItems: "center", height: "100%", color: "#4d5d70", fontSize: 12 }}>
      iniciando motor WebGL…
    </div>
  ),
});

const ALL_CATS = Object.keys(CATEGORY_META);
/** Ventana del archivo: coincide con RETENTION_DAYS por defecto (7 días). */
const RETENTION_H = 168;

/** Filtros rápidos: cada uno enciende o apaga una capa completa del mapa.
   * Grupos: eventos · transporte · sensores · lugares · zonas. */
const QUICK_FILTERS = [
  { key: "events", label: "Sucesos", icon: "event" },
  { key: "aircraft", label: "Aeronaves", icon: "plane" },
  { key: "vessels", label: "Buques", icon: "ship" },
  { key: "trains", label: "Trenes", icon: "train" },
  { key: "cameras", label: "Cámaras", icon: "camera" },
  { key: "satellites", label: "Satélites", icon: "satellite" },
  { key: "air", label: "Aire", icon: "air" },
  { key: "places", label: "Lugares", icon: "city" },
  { key: "fences", label: "Zonas", icon: "target" },
] as const;

/** Mensaje de error legible: sin HTML ni trazas kilométricas. */
function friendlyError(err: any): string {
  const raw = String(err?.message ?? err ?? "sin respuesta del servidor");
  const clean = raw.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim();
  if (/404/.test(clean)) return "404 · el servidor no expone /api (¿está sirviendo solo ficheros estáticos?)";
  if (/Failed to fetch|NetworkError|Load failed/i.test(clean)) return "sin conexión con el proceso del backend";
  return clean.slice(0, 140);
}

type Bbox = [number, number, number, number];

export default function Page() {
  /* ------------------------------------------------------------- state */
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [events, setEvents] = useState<FeatureCollection | null>(null);
  const [aircraft, setAircraft] = useState<LiveCollection | null>(null);
  const [vessels, setVessels] = useState<LiveCollection | null>(null);
  const [satellites, setSatellites] = useState<LiveCollection | null>(null);
  const [cameras, setCameras] = useState<LiveCollection | null>(null);
  const [air, setAir] = useState<LiveCollection | null>(null);
  const [trains, setTrains] = useState<LiveCollection | null>(null);
  const [cameraId, setCameraId] = useState<string | null>(null);
  // fondo de mapa: se recuerda entre sesiones. Los nombres anteriores
  // (vectorial, oscuro, satelite, transporte) se traducen a los actuales.
  const [basemap, setBasemap] = useState<string>(() => {
    if (typeof window === "undefined") return "operativo";
    const saved = window.localStorage.getItem("aegis.basemap") || "";
    const legacy: Record<string, string> = {
      vectorial: "operativo", oscuro: "detalle", satelite: "imagen", transporte: "detalle",
    };
    const id = legacy[saved] || saved;
    return BASEMAP_IDS.includes(id) ? id : "operativo";
  });
  const onBasemap = useCallback((id: string) => {
    setBasemap(id);
    try { window.localStorage.setItem("aegis.basemap", id); } catch { /* modo privado */ }
  }, []);
  const [fencesGeo, setFencesGeo] = useState<any>(null);
  const [fenceDefs, setFenceDefs] = useState<Fence[]>([]);
  const [alerts, setAlerts] = useState<Alert[]>([]);

  const [bbox, setBbox] = useState<Bbox>([-180, -85, 180, 85]);
  const [center, setCenter] = useState<[number, number]>([8, 26]);
  const [zoom, setZoom] = useState(1.55);
  const [hours, setHours] = useState(24);
  const [activeCats, setActiveCats] = useState<string[]>(ALL_CATS);
  const [query, setQuery] = useState("");
  const [visible, setVisible] = useState<Record<string, boolean>>({
    events: true, aircraft: true, vessels: true, satellites: true,
    cameras: true, air: false, trains: true, fences: true, places: true, graticule: true,
  });
  const toggleVisible = (key: (typeof QUICK_FILTERS)[number]["key"]) => {
    setVisible((prev) => ({ ...prev, [key]: prev[key] === false }));
  };
  const [terrain, setTerrain] = useState(false);
  const [aoiMode, setAoiMode] = useState(false);
  const [aoiRadiusKm, setAoiRadiusKm] = useState(200);

  const [selected, setSelected] = useState<EventFeature | null>(null);
  const [detail, setDetail] = useState<{ event: any; mentions: any[] } | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [nearby, setNearby] = useState<any>(null);
  const [nearbyLoading, setNearbyLoading] = useState(false);
  const [nearbyRadiusKn, setNearbyRadiusKm] = useState(150);

  const [actor, setActor] = useState<{ kind: ActorKind; id: string } | null>(null);
  const [actorDetail, setActorDetail] = useState<ActorDetail | null>(null);
  const [actorTrack, setActorTrack] = useState<ActorTrack | null>(null);
  const [actorLoading, setActorLoading] = useState(false);
  const [follow, setFollow] = useState(true);

  const [tab, setTab] = useState<Tab>("place");
  const [briefing, setBriefing] = useState<Briefing | null>(null);
  const [briefingLoading, setBriefingLoading] = useState(false);
  const [triggering, setTriggering] = useState<string | null>(null);

  /* desglose: cualquier número pulsado abre la lista de lo que cuenta */
  const [breakdown, setBreakdown] = useState<BreakdownSpec | null>(null);

  /* ficha del lugar: se abre con cualquier clic sobre el mapa */
  const [place, setPlace] = useState<{ lat: number; lon: number; name?: string } | null>(null);
  const [placeData, setPlaceData] = useState<PlaceData | null>(null);
  const [placeLoading, setPlaceLoading] = useState(false);
  const [placeRadiusKm, setPlaceRadiusKm] = useState(25);
  // ventana de eventos de la ficha de lugar (24 h / 7 días / 30 días)
  const [placeWindowH, setPlaceWindowH] = useState(168);
  const [threatHours, setThreatHours] = useState(24);
  const [placeNonce, setPlaceNonce] = useState(0);

  const [layerCounts, setLayerCounts] = useState<LayerCounts | null>(null);

  /** Recuento disponible por capa, para que el filtro diga cuánto se oculta. */
  const quickCount = (key: (typeof QUICK_FILTERS)[number]["key"]): number | null => {
    switch (key) {
      case "events": return layerCounts?.events.total ?? null;
      case "aircraft": return layerCounts?.aircraft ?? null;
      case "vessels": return layerCounts?.vessels ?? null;
      case "trains": return layerCounts?.trains ?? null;
      case "cameras": return layerCounts?.cameras.total ?? null;
      case "satellites": return layerCounts?.satellites ?? null;
      case "air": return layerCounts?.air ?? null;
      case "places": return layerCounts?.places ?? null;
      case "fences": return fenceDefs.length;
    }
  };
  const [showHelp, setShowHelp] = useState(false);
  const [wsState, setWsState] = useState<"connecting" | "open" | "closed">("connecting");
  const [notifyOn, setNotifyOn] = useState(false);
  const [shareCopied, setShareCopied] = useState(false);
  const [apiDown, setApiDown] = useState<string | null>(null);
  const [showHint, setShowHint] = useState(false);
  const [toasts, setToasts] = useState<Alert[]>([]);
  const [leftOpen, setLeftOpen] = useState(false);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [rightOpen, setRightOpen] = useState(true);
  const [newAlerts, setNewAlerts] = useState(0);
  const [eventsTick, setEventsTick] = useState(0);
  const [compact, setCompact] = useState(false);

  /* refs compartidos con el canal en vivo (se rellenan más abajo) */
  const liveTickRef = useRef<(() => Promise<void>) | null>(null);
  const refreshLayersRef = useRef<(() => Promise<void>) | null>(null);
  const pushAlertRef = useRef<((a: Alert) => void) | null>(null);
  const pushAlert = (a: Alert) => pushAlertRef.current?.(a);
  const knownAlerts = useRef<Set<string>>(new Set());

  const bboxRef = useRef<Bbox>(bbox);
  bboxRef.current = bbox;

  /* gancho de depuración: permite a las auditorías abrir una ficha concreta
     sin depender de la posición exacta de un punto en el mapa */
  useEffect(() => {
    (window as any).__aegisSelectActor = (kind: ActorKind, id: string) => {
      setActor({ kind, id });
      setSelected(null);
      setTab("actor");
      setRightOpen(true);
    };
    return () => { delete (window as any).__aegisSelectActor; };
  }, []);

  /* ------------------------------------------------ layout responsive */
  useEffect(() => {
    // Móvil = menos de 1180 px de ancho O menos de 620 px de alto (móvil en
    // horizontal, ventanas bajas). El CSS aplica el mismo criterio.
    const wide = window.matchMedia("(max-width: 1180px)");
    const short = window.matchMedia("(max-height: 620px)");
    const apply = () => {
      const isCompact = wide.matches || short.matches;
      setCompact(isCompact);
      // en pantalla estrecha el panel de análisis es una hoja inferior:
      // arrancar cerrado deja el mapa utilizable desde el primer toque
      if (isCompact) { setRightOpen(false); setLeftOpen(false); }
      else { setRightOpen(true); }
    };
    apply();
    wide.addEventListener("change", apply);
    short.addEventListener("change", apply);
    return () => {
      wide.removeEventListener("change", apply);
      short.removeEventListener("change", apply);
    };
  }, []);

  /** Histórico + avisos vivos: se fusionan para no perder ninguno al reconectar. */
  const refreshAlerts = useCallback(() => {
    return api.alerts()
      .then((r) => {
        const all = [...(r.alerts ?? []), ...(r.live ?? [])];
        for (const alert of all) knownAlerts.current.add(alertKey(alert));
        setAlerts((prev) => mergeAlerts(prev, all));
      })
      .catch(() => {});
  }, []);

  /* ------------------------------------------------------------- boot */
  useEffect(() => {
    api.config().then((c) => { setConfig(c); setApiDown(null); })
      .catch((e: any) => setApiDown(friendlyError(e)));
    api.fences().then((r) => { setFencesGeo(r.fences); setFenceDefs(r.definitions); }).catch(() => {});
    void refreshAlerts();
  }, [refreshAlerts]);

  /* Red de seguridad del histórico: aunque el WebSocket/long-polling se caiga,
     los avisos guardados se vuelven a leer al volver a la pestaña y cada 30 s. */
  useEffect(() => {
    const onVisible = () => { if (!document.hidden) void refreshAlerts(); };
    const id = setInterval(onVisible, 30_000);
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      clearInterval(id);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [refreshAlerts]);

  /* recuento de todas las capas (lo que se muestra junto a cada una) */
  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const res = await fetch(apiUrl("/api/layers"), { cache: "no-store" });
        if (!res.ok) return;
        const data = (await res.json()) as LayerCounts;
        if (alive) setLayerCounts(data);
      } catch { /* el recuento es informativo: no bloquea nada */ }
    };
    refreshLayersRef.current = tick;
    tick();
    const id = setInterval(tick, 60_000);
    return () => { alive = false; refreshLayersRef.current = null; clearInterval(id); };
  }, []);

  /* ------------------------------------------------- compartir la vista
     La URL lleva el encuadre, la ventana temporal y las categorías en el
     hash: copiar el enlace es copiar exactamente lo que estás viendo. */
  useEffect(() => {
    if (typeof window === "undefined") return;
    const [, queryString = ""] = (window.location.hash || "").split("?");
    if (!queryString) return;
    const params = new URLSearchParams(queryString);
    const view = params.get("v");
    if (view) {
      const [lat, lon, z] = view.split(",").map(Number);
      if (Number.isFinite(lat) && Number.isFinite(lon) && Number.isFinite(z)) {
        (window as any).__aegisMap?.jumpTo({ center: [lon, lat], zoom: z });
      }
    }
    const h = Number(params.get("h"));
    if (Number.isFinite(h) && h > 0) setHours(h);
    const c = params.get("c");
    if (c) {
      const cats = c.split(",").filter((x) => ALL_CATS.includes(x));
      if (cats.length) setActiveCats(cats);
    }
    const q = params.get("q");
    if (q) setQuery(q);
  }, []);

  const shareView = useCallback(async () => {
    const hash = `#?v=${center[1].toFixed(3)},${center[0].toFixed(3)},${zoom.toFixed(2)}`
      + `&h=${hours}`
      + (activeCats.length !== ALL_CATS.length ? `&c=${activeCats.join(",")}` : "")
      + (query ? `&q=${encodeURIComponent(query)}` : "");
    const url = `${window.location.origin}${window.location.pathname}${hash}`;
    try {
      window.history.replaceState(null, "", hash);
    } catch { /* algunos visores bloquean history: la URL sigue valiendo */ }
    try {
      if (navigator.share) {
        await navigator.share({ title: "AEGIS", text: "Vista del mapa AEGIS", url });
        return;
      }
      await navigator.clipboard.writeText(url);
      setShareCopied(true);
      setTimeout(() => setShareCopied(false), 2000);
    } catch {
      try { await navigator.clipboard.writeText(url); setShareCopied(true); } catch { /* sin permiso */ }
    }
  }, [center, zoom, hours, activeCats, query]);

  /* --------------------------------------------------- avisos del sistema */
  const toggleNotify = useCallback(async () => {
    if (typeof window === "undefined" || !("Notification" in window)) return;
    if (Notification.permission === "granted") { setNotifyOn(false); return; }
    const perm = await Notification.requestPermission();
    setNotifyOn(perm === "granted");
    if (perm === "granted") {
      try {
        const reg = await navigator.serviceWorker?.ready;
        reg?.showNotification("AEGIS · avisos activados", {
          body: "Te avisaré de lo que entre en tus zonas vigiladas aunque no estés mirando.",
          icon: assetUrl("/icon.svg"),
          tag: "aegis-bienvenida",
        });
      } catch { /* la notificación es opcional */ }
    }
  }, []);

  /* service worker: armazón sin red + notificaciones */
  useEffect(() => {
    if (typeof window === "undefined" || !("serviceWorker" in navigator)) return;
    // Si había un service worker antiguo controlando la página, al activarse el
    // nuevo se recarga una vez para que el armazón cacheado no siga mostrando
    // la interfaz anterior (filtros, leyenda y controles descolocados).
    const hadController = !!navigator.serviceWorker.controller;
    const onControllerChange = () => {
      if (hadController) window.location.reload();
    };
    navigator.serviceWorker.addEventListener("controllerchange", onControllerChange);
    navigator.serviceWorker
      .register(assetUrl("/sw.js"), { updateViaCache: "none" })
      .then((reg) => reg.update().catch(() => {}))
      .catch(() => {});
    if ("Notification" in window && Notification.permission === "granted") setNotifyOn(true);
    return () => navigator.serviceWorker.removeEventListener("controllerchange", onControllerChange);
  }, []);

  /* atajo de teclado: ? abre la guía */
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      const typing = target && /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName);
      if (!typing && (e.key === "?" || (e.key === "h" && !e.metaKey && !e.ctrlKey))) {
        e.preventDefault();
        setShowHelp((v) => !v);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  /* health poll */
  useEffect(() => {
    let alive = true;
    const tick = () =>
      api.health()
        .then((h) => { if (!alive) return; setHealth(h); setApiDown(null); })
        .catch((e: any) => { if (alive) setApiDown(friendlyError(e)); });
    tick();
    const id = setInterval(tick, 8_000);
    return () => { alive = false; clearInterval(id); };
  }, []);

  /* live layers */
  /* Las capas vivas las refresca el canal SSE (arriba). Aquí solo queda la
     descarga inicial de la capa de aire, que es opcional y pesada: se pide al
     activarla si aún no está en memoria. */
  useEffect(() => {
    if (!visible.air || air) return;
    api.air().then(setAir).catch(() => {});
  }, [visible.air, air]);

  /* ------------------------------------------------- canal en vivo único
     Long-polling en cadena contra /api/poll: el servidor responde en cuanto
     cambia una capa (o a los 18 s, como latido) y el cliente recarga solo esa
     capa. Se eligió long-polling en vez de SSE porque el túnel público de
     Cloudflare retiene las respuestas en streaming; una respuesta que termina
     atraviesa cualquier proxy. Con la pestaña oculta se espacia a 30 s. */
  const reloaders = useRef<Record<string, () => void>>({});
  reloaders.current = {
    aircraft: () => { api.aircraft().then(setAircraft).catch(() => {}); },
    vessels: () => { api.vessels().then(setVessels).catch(() => {}); },
    satellites: () => { api.satellites().then(setSatellites).catch(() => {}); },
    trains: () => { api.trains().then(setTrains).catch(() => {}); },
    air: () => { api.air().then(setAir).catch(() => {}); },
    cameras: () => { api.cameras().then((d) => setCameras(d as LiveCollection)).catch(() => {}); },
    events: () => {
      // Amenazas es global: se refresca aunque el suceso nuevo caiga fuera de la vista.
      setEventsTick((n) => n + 1);
      void liveTickRef.current?.();
    },
    layers: () => { void refreshLayersRef.current?.(); },
  };
  const visibleRef = useRef(visible);
  visibleRef.current = visible;

  /** descarga inicial completa (se llama al arrancar y al volver a la pestaña) */
  const loadAll = useCallback(() => {
    api.aircraft().then(setAircraft).catch(() => {});
    api.vessels().then(setVessels).catch(() => {});
    api.satellites().then(setSatellites).catch(() => {});
    api.cameras().then((d) => setCameras(d as LiveCollection)).catch(() => {});
    if (visibleRef.current.trains) api.trains().then(setTrains).catch(() => {});
    void liveTickRef.current?.();
  }, []);

  useEffect(() => {
    let disposed = false;
    let timer: any = null;
    let cursor = 0;
    let alertCursor = 0;
    let failures = 0;
    // los avisos de patrón pueden repetirse entre reconexiones: huella por aviso
    const seenAlerts = new Set<string>();

    const schedule = (ms: number) => {
      clearTimeout(timer);
      timer = setTimeout(cycle, ms);
    };

    const cycle = async () => {
      if (disposed) return;
      if (typeof document !== "undefined" && document.hidden) { schedule(30_000); return; }
      const started = Date.now();
      try {
        const res = await fetch(apiUrl(`/api/poll?since=${cursor}&as=${alertCursor}&wait=18`), { cache: "no-store" });
        if (!res.ok) throw new Error(`poll ${res.status}`);
        const data = await res.json();
        failures = 0;
        setWsState("open");
        const layers: string[] = data.layers ?? [];
        const freshCursor = Number(data.cursor ?? cursor);
        if (layers.length) {
          for (const layer of layers) {
            if (layer === "air" && !visibleRef.current.air) continue;
            if (layer === "trains" && !visibleRef.current.trains) continue;
            reloaders.current[layer]?.();
          }
          if (layers.some((l: string) => l === "events" || l === "trains" || l === "cameras" || l === "air")) {
            reloaders.current.layers?.();
          }
        }
        // solo los avisos posteriores al cursor, sin repetir huellas ya vistas
        const alerts: any[] = data.alerts ?? [];
        for (const alert of alerts) {
          const stamp = alertKey(alert as Alert);
          if (!stamp || seenAlerts.has(stamp)) continue;
          seenAlerts.add(stamp);
          if (seenAlerts.size > 400) seenAlerts.clear();
          pushAlert(alert as Alert);
        }
        cursor = freshCursor;
        alertCursor = Number(data.alert_cursor ?? alertCursor);
        // si hubo cambios, se vuelve enseguida; si fue un latido, se espera 2 s
        const elapsed = Date.now() - started;
        schedule(layers.length ? 400 : Math.max(1200, elapsed < 3000 ? 2000 : 400));
      } catch {
        failures += 1;
        setWsState(failures > 2 ? "closed" : "connecting");
        // reintento con espera creciente, como máximo 30 s
        schedule(Math.min(30_000, 5000 * failures));
      }
    };

    // primera descarga de todo (el cursor 0 devuelve el estado actual)
    loadAll();
    cycle();
    const onVisible = () => { if (!document.hidden) schedule(300); };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      disposed = true;
      clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, []);

  /* la salud del sistema sigue en su propio latido: es lo que alimenta el KPI */
  useEffect(() => {
    const id = setInterval(() => api.health().then(setHealth).catch(() => {}), 10_000);
    return () => clearInterval(id);
  }, []);

  /* gancho de inspección (usado por las pruebas automatizadas) */
  useEffect(() => {
    (window as any).__aegisLive = { aircraft, vessels, satellites, trains };
  }, [aircraft, vessels, satellites]);

  /* refresco a la carta del tráfico de la zona visible (para verlo volar) */
  const focusRef = useRef<{ t: number; lat: number; lon: number }>({ t: 0, lat: 0, lon: 0 });
  useEffect(() => {
    if (zoom < 4) return;
    const now = Date.now();
    const moved =
      Math.abs(center[0] - focusRef.current.lon) > 0.8 || Math.abs(center[1] - focusRef.current.lat) > 0.8;
    if (!moved && now - focusRef.current.t < 25_000) return;
    const id = setTimeout(() => {
      focusRef.current = { t: Date.now(), lat: center[1], lon: center[0] };
      api.refreshAircraft(center[1], center[0])
        .then((r) => { if (r.updated > 0) api.aircraft().then(setAircraft).catch(() => {}); })
        .catch(() => {});
    }, 2500);
    return () => clearTimeout(id);
  }, [center, zoom]);

  /* events: refetch on viewport / window / filters (debounced) */
  const loadEvents = useCallback(async () => {
    const [w, s, e, n] = bboxRef.current;
    const padX = Math.max(2, (e - w) * 0.25);
    const padY = Math.max(2, (n - s) * 0.25);
    const padded: Bbox = [Math.max(-180, w - padX), Math.max(-85, s - padY), Math.min(180, e + padX), Math.min(85, n + padY)];
    try {
      const data = await api.events({
        bbox: padded,
        categories: activeCats.length === ALL_CATS.length ? undefined : activeCats,
        hours,
        q: query || undefined,
        limit: 8000,
      });
      // los eventos entrantes van delante y en orden cronológico inverso
      const feats = [...(data?.features ?? [])].sort((a: any, b: any) =>
        String(b.properties?.first_seen || "").localeCompare(String(a.properties?.first_seen || ""))
      );
      setEvents({ ...data, features: feats } as any);
      setEventsTick((n) => n + 1);
      const mark = (data as any)?.server_time
        || (feats.length ? String(feats[0].properties.first_seen) : null);
      if (mark) {
        liveMark.current = mark;
        try { window.localStorage.setItem("aegis.eventsMark", mark); } catch { /* modo privado */ }
      }
    } catch (err) {
      console.warn("events fetch failed", err);
    }
  }, [activeCats, hours, query]);

  useEffect(() => {
    const id = setTimeout(loadEvents, 380);
    return () => clearTimeout(id);
  }, [loadEvents, bbox]);

  useEffect(() => {
    const id = setInterval(loadEvents, 60_000);
    return () => clearInterval(id);
  }, [loadEvents]);

  /* ------ eventos en vivo: cada 15 s se piden SOLO los aparecidos después ----
     El sondeo completo son ~1,4 MB; el incremental suele ser 0 o unos pocos
     eventos, así que se puede ir a 15 s sin castigar la red y los sucesos
     nuevos (sismos, incendios, avisos) salen en el mapa al momento. */
  const liveMark = useRef<string | null>(null);
  const filtersRef = useRef({ activeCats, hours, query, bbox });
  filtersRef.current = { activeCats, hours, query, bbox };
  useEffect(() => {
    const cached = typeof window !== "undefined" ? window.localStorage.getItem("aegis.eventsMark") : null;
    if (cached) liveMark.current = cached;
  }, []);

  useEffect(() => {
    let stopped = false;
    const tick = async () => {
      const mark = liveMark.current;
      if (!mark) return;              // aún no hay referencia del sondeo grande
      if (typeof document !== "undefined" && document.hidden) return;
      const f = filtersRef.current;
      const [w, s, e, n] = f.bbox;
      const padX = Math.max(2, (e - w) * 0.25);
      const padY = Math.max(2, (n - s) * 0.25);
      try {
        const fresh = await api.events({
          bbox: [Math.max(-180, w - padX), Math.max(-85, s - padY), Math.min(180, e + padX), Math.min(85, n + padY)],
          categories: f.activeCats.length === ALL_CATS.length ? undefined : f.activeCats,
          hours: f.hours,
          q: f.query || undefined,
          limit: 8000,
          since: mark,
        });
        if (stopped || !fresh?.features?.length) {
          if (!stopped && (fresh as any)?.server_time) liveMark.current = (fresh as any).server_time;
          return;
        }
        setEvents((prev) => {
          if (!prev) return fresh;
          const seen = new Set(prev.features.map((x: any) => x.properties.id));
          const add = fresh.features.filter((x: any) => !seen.has(x.properties.id));
          return add.length ? { ...prev, features: [...add, ...prev.features], count: prev.count + add.length } : prev;
        });
        setEventsTick((n) => n + 1);
        if ((fresh as any)?.server_time) liveMark.current = (fresh as any).server_time;
      } catch { /* sin red: el siguiente ciclo reintenta */ }
    };
    liveTickRef.current = tick;
    // 60 s de red de seguridad: el canal SSE avisa de los sucesos al instante
    const id = setInterval(tick, 60_000);
    const onVisible = () => { if (!document.hidden) tick(); };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      stopped = true;
      liveTickRef.current = null;
      clearInterval(id);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, []);

  /* ------------------------------------------------------------- ws */
  useEffect(() => {
    let socket: WebSocket | null = null;
    let timer: any = null;
    let attempt = 0;
    let disposed = false;

    const push = (alert: Alert) => {
      const key = alertKey(alert);
      const isNew = !knownAlerts.current.has(key);
      knownAlerts.current.add(key);
      setAlerts((prev) => mergeAlerts(prev, [alert]));
      if (!isNew) return;
      setNewAlerts((n) => n + 1);
      if (alert.severity === "critical" || alert.event_type === "rule") {
        setToasts((prev) => [alert, ...prev].slice(0, 4));
        setTimeout(() => setToasts((prev) => prev.filter((t) => t !== alert)), 9000);
      }
      // aviso del sistema si el usuario lo ha permitido y la pestaña no está a la vista
      if (typeof document !== "undefined" && document.hidden && "Notification" in window
          && Notification.permission === "granted") {
        try {
          navigator.serviceWorker?.ready
            .then((reg) => reg.showNotification(`AEGIS · ${alert.title}`, {
              body: (alert as any).message || (alert as any).fence_name || "alerta de zona vigilada",
              tag: `${alert.fence_id ?? "aegis"}-${alert.event_type ?? "aviso"}`,
              icon: assetUrl("/icon.svg"),
            }))
            .catch(() => {});
        } catch { /* sin service worker no hay notificación, nada más */ }
      }
    };
    pushAlertRef.current = push;

    const connect = () => {
      setWsState("connecting");
      try {
        socket = new WebSocket(wsUrl());
      } catch {
        return;
      }
      socket.onopen = () => {
        setWsState("open");
        attempt = 0;
        // al reconectar, recupera lo que se emitiera mientras estaba caído
        void refreshAlerts();
      };
      socket.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data);
          if (msg.type === "hello" && Array.isArray(msg.recent)) {
            const recent = msg.recent as Alert[];
            for (const alert of recent) knownAlerts.current.add(alertKey(alert));
            setAlerts((prev) => mergeAlerts(prev, recent));
          }
          if (msg.type === "alert" && msg.alert) push(msg.alert);
        } catch {}
      };
      socket.onclose = () => {
        setWsState("closed");
        if (!disposed) timer = setTimeout(connect, Math.min(20_000, 1200 * 2 ** attempt++));
      };
      socket.onerror = () => socket?.close();
    };
    connect();
    return () => {
      disposed = true;
      clearTimeout(timer);
      socket?.close();
    };
  }, [refreshAlerts]);

  /* ------------------------------------------------------ selection */
  useEffect(() => {
    if (!selected) { setDetail(null); setNearby(null); return; }
    const id = selected.properties.id;
    setDetailLoading(true);
    api.event(id)
      .then(setDetail)
      .catch(() => setDetail(null))
      .finally(() => setDetailLoading(false));
  }, [selected]);

  /* -------- elemento móvil: ficha completa + trayectoria (refresco vivo) */
  useEffect(() => {
    if (!actor) { setActorDetail(null); setActorTrack(null); return; }
    let alive = true;
    let trackTick = 0;
    const minutes = actor.kind === "satellites" ? 90 : 45;

    const loadDetail = () => {
      api.actorDetail(actor.kind, actor.id)
        .then((d) => { if (alive) setActorDetail(d as ActorDetail); })
        .catch(() => {})
        .finally(() => { if (alive) setActorLoading(false); });
    };
    const loadTrack = () => {
      api.actorTrack(actor.kind, actor.id, minutes)
        .then((t) => { if (alive) setActorTrack(t as ActorTrack); })
        .catch(() => {});
    };

    setActorLoading(true);
    loadDetail();
    loadTrack();
    // la ficha se refresca con el sondeo de cada capa; la estela cada 4 vueltas
    const dId = setInterval(loadDetail, actor.kind === "aircraft" ? 8_000 : actor.kind === "satellites" ? 6_000 : 25_000);
    const tId = setInterval(() => { if (++trackTick % 4 === 0) loadTrack(); }, 8_000);
    return () => { alive = false; clearInterval(dId); clearInterval(tId); };
  }, [actor]);

  useEffect(() => {
    if (!selected) return;
    setNearbyLoading(true);
    api.nearby(selected.properties.id, nearbyRadiusKn)
      .then(setNearby)
      .catch(() => setNearby(null))
      .finally(() => setNearbyLoading(false));
  }, [selected, nearbyRadiusKn]);

  const selectById = useCallback(async (id: string) => {
    try {
      const data = await api.event(id);
      const ev = data.event;
      setSelected({
        type: "Feature",
        geometry: { type: "Point", coordinates: [ev.lon, ev.lat] },
        properties: ev,
      } as EventFeature);
      setTab("detail");
      setRightOpen(true);
      setLeftOpen(false);
      (window as any).__aegisMap?.easeTo({ center: [ev.lon, ev.lat], zoom: 5 });
    } catch {}
  }, []);

  const onSelect = useCallback((feature: EventFeature | null) => {
    setSelected(feature);
    if (feature) {
      setActor(null);
      setTab("detail");
      setRightOpen(true);   // en móvil despliega la hoja inferior con el detalle
      setLeftOpen(false);
    }
  }, []);

  const onCameraSelect = useCallback((id: string) => {
    setCameraId(id);
    setActor(null);
    setSelected(null);
    setTab("camera");
    setRightOpen(true);
    setLeftOpen(false);
  }, []);

  const onActorSelect = useCallback((kind: ActorKind, id: string) => {
    setActor({ kind, id });
    setSelected(null);
    setTab("actor");
    setRightOpen(true);      // en móvil abre la hoja inferior con la ficha
    setLeftOpen(false);
  }, []);

  /* ------------------------------------------- ficha del lugar pinchado */
  const onPlaceSelect = useCallback(
    (hit: { lat: number; lon: number; name?: string; zoom: number }) => {
      if (aoiMode) return;
      // el radio se adapta al zoom: cuanto más cerca miras, menos entorno
      const radius = Math.min(250, Math.max(10, Math.round(Math.pow(2, 15 - hit.zoom))));
      setPlaceRadiusKm((prev) => (prev === radius ? prev : radius));
      setPlace({ lat: hit.lat, lon: hit.lon, name: hit.name });
      setSelected(null);
      setActor(null);
      setCameraId(null);
      setTab("place");
      setRightOpen(true);      // en móvil abre la hoja inferior con la ficha
      setLeftOpen(false);
    },
    [aoiMode]
  );

  /* «Mi ubicación» → ficha de Lugar centrada en el usuario. Funciona desde el
     botón del mapa y desde el control de ubicación del buscador: en ambos casos se abre el panel
     con lo que hay alrededor (sucesos, tráfico aéreo, cámaras, trenes…). */
  useEffect(() => {
    const q = query.trim().toLowerCase();
    if (!["cerca", "cerca de mí", "cerca de mi", "aqui", "aquí", "mi ubicacion", "mi ubicación"].includes(q)) return;
    setQuery("");
    locateMe();
  }, [query]);

  useEffect(() => {
    const alUbicarme = (e: Event) => {
      const { lat, lon } = (e as CustomEvent<{ lat: number; lon: number }>).detail || ({} as any);
      if (typeof lat !== "number" || typeof lon !== "number") return;
      setPlace({ lat, lon, name: "Mi ubicación" });
      setPlaceRadiusKm(25);
      setSelected(null);
      setActor(null);
      setCameraId(null);
      setTab("place");
      setRightOpen(true);
      setLeftOpen(false);
    };
    window.addEventListener("aegis:me", alUbicarme as EventListener);
    return () => window.removeEventListener("aegis:me", alUbicarme as EventListener);
  }, []);

  /* Si el navegador bloquea o no encuentra la ubicación, se avisa en vez de
     dejar el botón sin respuesta aparente. */
  useEffect(() => {
    const alFallarUbicacion = (e: Event) => {
      const message = (e as CustomEvent<{ message?: string }>).detail?.message
        || "No se pudo obtener tu ubicación.";
      const alert: Alert = {
        ts: new Date().toISOString(), fence_id: null, actor_id: "-", actor_type: "geo",
        event_type: "error", severity: "info", title: "Ubicación no disponible", message,
        lat: null, lon: null, payload: {},
      };
      setToasts((prev) => [alert, ...prev].slice(0, 4));
      setTimeout(() => setToasts((prev) => prev.filter((t) => t !== alert)), 9000);
    };
    window.addEventListener("aegis:geo-error", alFallarUbicacion as EventListener);
    return () => window.removeEventListener("aegis:geo-error", alFallarUbicacion as EventListener);
  }, []);

  const placeKey = place
    ? `${place.lat.toFixed(5)},${place.lon.toFixed(5)},${placeRadiusKm},${placeWindowH}`
    : null;

  useEffect(() => {
    if (!place) { setPlaceData(null); return; }
    const ctrl = new AbortController();
    let alive = true;
    const load = async (silent: boolean) => {
      if (!silent) setPlaceLoading(true);
      try {
        const res = await fetch(
          `/api/where?lat=${place.lat}&lon=${place.lon}&radius_km=${placeRadiusKm}` +
            `&limit=200&since_hours=${placeWindowH}`,
          { signal: ctrl.signal, cache: "no-store" }
        );
        if (!res.ok) throw new Error(String(res.status));
        const data = (await res.json()) as PlaceData;
        if (!alive) return;
        setPlaceData({ ...data, fetched_at: Date.now() });
      } catch {
        /* abortado o backend caído: se mantiene la última ficha */
      } finally {
        if (alive) setPlaceLoading(false);
      }
    };
    load(false);
    // la ficha se refresca sola: el entorno del punto cambia en tiempo real
    const timer = window.setInterval(() => load(true), 15000);
    return () => {
      alive = false;
      ctrl.abort();
      window.clearInterval(timer);
    };
  }, [placeKey, placeNonce]);   // eslint-disable-line react-hooks/exhaustive-deps

  const clearPlace = useCallback(() => { setPlace(null); setPlaceData(null); }, []);

  const centerPlace = useCallback(() => {
    if (!place) return;
    (window as any).__aegisMap?.easeTo({ center: [place.lon, place.lat], zoom: Math.max(9, zoom), duration: 900 });
  }, [place, zoom]);

  const clearActor = useCallback(() => { setActor(null); setFollow(true); }, []);

  const recenterActor = useCallback(() => {
    const d: any = actorDetail;
    const lat = d?.actor?.lat ?? d?.lat;
    const lon = d?.actor?.lon ?? d?.lon;
    if (typeof lat === "number" && typeof lon === "number") {
      (window as any).__aegisMap?.easeTo({ center: [lon, lat], zoom: Math.max(4, zoom), duration: 900 });
    }
  }, [actorDetail, zoom]);

  const closePanels = useCallback(() => { setLeftOpen(false); setRightOpen(false); }, []);

  /* ------------------------------------------------------- desgloses */
  /** Número de una fuente de ingesta -> lista de los elementos que ha aportado. */
  const breakdownSource = useCallback((src: { name: string; source?: string; kind: string; items: number }) => {
    const label = src.source ?? src.name;
    if (src.kind === "aircraft" || src.kind === "vessels" || src.kind === "satellites") {
      setBreakdown({
        kind: src.kind,
        title: `${label} · ${src.items} elementos vivos`,
        subtitle: "posición actual en memoria",
        live: src.kind === "aircraft" ? aircraft : src.kind === "vessels" ? vessels : satellites,
      });
      return;
    }
    setBreakdown({
      kind: "events",
      title: `${label} · eventos en el almacén`,
      window: "últimos 14 días (retención)",
      filters: { sources: [src.name], hours: RETENTION_H },   
    });
  }, [aircraft, vessels, satellites]);

  /** Número de una categoría -> eventos de esa categoría en la ventana activa. */
  const breakdownCategory = useCallback((cat: string) => {
    setBreakdown({
      kind: "events",
      title: `${CATEGORY_META[cat]?.label ?? cat} · desglose`,
      window: `últimas ${hours} h`,
      filters: { categories: [cat], hours },
    });
  }, [hours]);

  /** Número de un cúmulo del mapa -> sus elementos (ya en memoria). */
  const breakdownCluster = useCallback((items: BreakdownItem[], zoomTo?: () => void) => {
    setBreakdown({
      kind: "inline",
      title: `Cúmulo · ${items.length} elementos`,
      subtitle: "en la vista actual",
      items,
      zoomTo,
    });
  }, []);

  /** Cámaras y aire: capas vivas que también se despliegan. */
  const breakdownCameras = useCallback((network?: string) => {
    const feats = (cameras?.features ?? []).filter(
      (f: any) => !network || f.properties?.network === network
    );
    setBreakdown({
      kind: "inline",
      title: network ? `Cámaras · ${network}` : "Cámaras públicas abiertas",
      subtitle: "catálogo indexado (imagen en vivo al pulsar)",
      items: feats.map((f: any) => ({
        id: String(f.properties.id),
        title: String(f.properties.name ?? f.properties.id),
        sub: [f.properties.network_label, f.properties.kind, f.properties.place]
          .filter(Boolean).join(" · "),
        color: "#b388ff",
        lat: f.geometry?.coordinates?.[1],
        lon: f.geometry?.coordinates?.[0],
      })),
    });
  }, [cameras]);

  /** KPIs de la barra superior -> desglose. */
  const breakdownKpi = useCallback((key: "view" | "stored" | "aircraft" | "vessels" | "satellites" | "cameras" | "air" | "trains") => {
    if (key === "cameras") {
      breakdownCameras();
      return;
    }
    if (key === "air") {
      setBreakdown({
        kind: "inline",
        title: "Calidad del aire · Sensor.Community",
        subtitle: "PM2.5 por sensor (µg/m³)",
        items: (air?.features ?? []).map((f: any) => ({
          id: String(f.properties.id),
          title: `PM2.5 ${f.properties.pm25 ?? "—"} µg/m³ · ${f.properties.level ?? ""}`,
          sub: [f.properties.sensor_type, f.properties.country, f.properties.observed_at]
            .filter(Boolean).join(" · "),
          color: "#a5d6a7",
          lat: f.geometry?.coordinates?.[1],
          lon: f.geometry?.coordinates?.[0],
        })),
      });
      return;
    }
    if (key === "trains") {
      setBreakdown({
        kind: "inline",
        title: "Trenes en vivo",
        subtitle: trains && trains.features.length
          ? "GTFS-Realtime · Renfe, FGC y Amtrak · pulsa uno para abrir su ficha"
          : "sin servicio ahora mismo: los feeds no publican trenes en este instante",
        items: (trains?.features ?? []).map((f: any) => ({
          id: `trains:${f.properties.id}`,
          title: `${f.properties.line || f.properties.name || "tren"} · ${f.properties.status || ""}`.trim(),
          sub: [f.properties.nucleo, f.properties.operator,
                f.properties.delay_s != null ? `${Math.round(Number(f.properties.delay_s) / 60)} min de retraso` : null]
            .filter(Boolean).join(" · "),
          color: f.properties.network === "amtrak" ? "#9ecbff"
            : f.properties.network === "fgc" ? "#8ee6a8" : "#ffb454",
          lat: f.geometry?.coordinates?.[1],
          lon: f.geometry?.coordinates?.[0],
        })),
      });
      return;
    }
    if (key === "aircraft" || key === "vessels" || key === "satellites") {
      const coll = key === "aircraft" ? aircraft : key === "vessels" ? vessels : satellites;
      setBreakdown({
        kind: key,
        title: key === "aircraft" ? "Aeronaves en seguimiento" : key === "vessels" ? "Buques en seguimiento" : "Satélites propagados",
        subtitle: "posición actual en memoria",
        live: coll,
      });
      return;
    }
    if (key === "view") {
      setBreakdown({
        kind: "events",
        title: "Eventos en la vista",
        window: `últimas ${hours} h`,
        filters: { bbox: bboxRef.current, hours, categories: activeCats.length === ALL_CATS.length ? undefined : activeCats, q: query || undefined },
      });
      return;
    }
    setBreakdown({
      kind: "events",
      title: "Eventos consolidados",
      window: "últimos 14 días (retención)",
      filters: { hours: RETENTION_H },
    });
  }, [aircraft, vessels, satellites, air, trains, hours, activeCats, query, breakdownCameras]);

  /** Número de una capa -> la lista de lo que cuenta. */
  const breakdownLayer = useCallback((key: string) => {
    if (key === "events") {
      breakdownKpi("view");
      return;
    }
    if (key === "aircraft" || key === "vessels" || key === "satellites" || key === "cameras" || key === "air" || key === "trains") {
      breakdownKpi(key);
      return;
    }
    if (key === "places") {
      setBreakdown({
        kind: "inline",
        title: "Núcleos urbanos del mundo",
        subtitle: "7.342 ciudades y poblaciones (Natural Earth 1:10m)",
        items: [
          { id: "hint", title: "Pulsa cualquier ciudad del mapa", sub: "se abre su ficha con todo lo que hay en 25 km a la redonda", color: "#8fb4c9" },
        ],
      });
    }
  }, [breakdownKpi]);

  const pickBreakdown = useCallback((item: BreakdownItem) => {
    const kind = breakdown?.kind;
    if (kind === "inline" && String(item.id).includes(":")) {
      // los ids de cámara llevan prefijo de red ("dgt:...", "tfl:...", "caltrans:...")
      const net = String(item.id).split(":")[0];
      if (["dgt", "madrid", "cat", "euskadi", "tfl", "caltrans", "nyc", "digitraffic"].includes(net)) {
        onCameraSelect(String(item.id));
        if (typeof item.lat === "number" && typeof item.lon === "number") {
          (window as any).__aegisMap?.easeTo({ center: [item.lon, item.lat], zoom: 12, duration: 700 });
        }
        return;
      }
    }
    const rawId = String(item.id);
    if (rawId.startsWith("trains:")) {
      setActor({ kind: "trains", id: rawId.slice(7) });
      setSelected(null);
      setTab("actor");
      setRightOpen(true);
      return;
    }
    if (kind === "aircraft" || kind === "vessels" || kind === "satellites") {
      setActor({ kind, id: item.id });
      setSelected(null);
      setTab("actor");
      setRightOpen(true);
      if (typeof item.lat === "number" && typeof item.lon === "number") {
        (window as any).__aegisMap?.easeTo({ center: [item.lon, item.lat], zoom: 6, duration: 700 });
      }
      return;
    }
    selectById(item.id);
  }, [breakdown, selectById, onCameraSelect]);

  /* --------------------------------------------------------- fences */
  const reloadFences = useCallback(() => {
    api.fences().then((r) => { setFencesGeo(r.fences); setFenceDefs(r.definitions); }).catch(() => {});
  }, []);

  const createFence = useCallback(async (lat: number, lon: number, radiusKm: number) => {
    try {
      const res = await api.createFence({
        name: `Zona ${lat.toFixed(2)},${lon.toFixed(2)}`,
        lat, lon, radius_m: radiusKm * 1000,
      });
      reloadFences();
      setAoiMode(false);
      setTab("alerts");
      setToasts((prev) => [{
        ts: new Date().toISOString(), fence_id: res.fence.id, actor_id: "-", actor_type: "aoi",
        event_type: "enter", severity: "info", title: `Zona vigilada creada · ${res.fence.name}`,
        message: `Radio ${radiusKm} km — vigilancia activa`, lat, lon, payload: {},
      } as Alert, ...prev].slice(0, 4));
    } catch (err) {
      console.warn(err);
    }
  }, [reloadFences]);

  const deleteFence = useCallback(async (id: string) => {
    await api.deleteFence(id).catch(() => {});
    reloadFences();
  }, [reloadFences]);

  /* ------------------------------------------------------- briefing */
  const generateBriefing = useCallback(async () => {
    setBriefingLoading(true);
    setTab("briefing");
    try {
      const [w, s, e, n] = bboxRef.current;
      const data = await api.briefing({
        bbox: [w, s, e, n],
        hours,
        categories: activeCats.length === ALL_CATS.length ? undefined : activeCats,
        window: `${hours}h`,
      });
      setBriefing(data);
    } catch (err) {
      console.warn("briefing failed", err);
    } finally {
      setBriefingLoading(false);
    }
  }, [hours, activeCats]);

  const downloadBriefing = useCallback(() => {
    if (!briefing) return;
    const header = `# AEGIS · Expediente de situación\n\nGenerado: ${briefing.generated_at}\nMotor: ${briefing.provider}\nVentana: ${briefing.window}\nEventos: ${briefing.event_count}\n\n---\n\n`;
    const blob = new Blob([header + briefing.markdown], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `aegis-briefing-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-")}.md`;
    a.click();
    URL.revokeObjectURL(url);
  }, [briefing]);

  /* ------------------------------------------------- exportar lo que se ve */
  const exportEvents = useCallback((fmt: "csv" | "geojson") => {
    const [w, s, e, n] = bbox;
    const padX = Math.max(2, (e - w) * 0.25);
    const padY = Math.max(2, (n - s) * 0.25);
    const padded = [Math.max(-180, w - padX), Math.max(-85, s - padY), Math.min(180, e + padX), Math.min(85, n + padY)];
    const params = new URLSearchParams({
      bbox: padded.map((v) => v.toFixed(3)).join(","),
      hours: String(hours),
      fmt,
    });
    if (activeCats.length !== ALL_CATS.length) params.set("categories", activeCats.join(","));
    if (query) params.set("q", query);
    window.open(`/api/export/events?${params.toString()}`, "_blank", "noopener");
  }, [bbox, hours, activeCats, query]);

  /* -------------------------------------------------------- sources */
  const triggerSource = useCallback(async (name: string) => {
    setTriggering(name);
    try {
      await api.trigger(name);
      const h = await api.health();
      setHealth(h);
      loadEvents();
    } catch (err) {
      console.warn(err);
    } finally {
      setTriggering(null);
    }
  }, [loadEvents]);

  /* ------------------------------------------------------------ ui */
  const toggleCat = useCallback((cat: string) => {
    setActiveCats((prev) => (prev.includes(cat) ? prev.filter((c) => c !== cat) : [...prev, cat]));
  }, []);

  const flyTo = useCallback((lat: number, lon: number, z = 5) => {
    (window as any).__aegisMap?.flyTo({ center: [lon, lat], zoom: z, speed: 1.2 });
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") { setBreakdown(null); setSelected(null); setActor(null); setCameraId(null); setAoiMode(false); setPlace(null); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const retryApi = useCallback(() => {
    api.health().then((h) => { setHealth(h); setApiDown(null); }).catch((e: any) =>
      setApiDown(friendlyError(e)));
    api.config().then(setConfig).catch(() => {});
    loadEvents();
  }, [loadEvents]);

  const categoryCounts = useMemo(() => events?.numbers?.by_category ?? {}, [events]);
  const criticalAlerts = useMemo(
    () => alerts.filter((a) => a.severity === "critical" || a.event_type === "rule").length,
    [alerts]
  );

  return (
    <main className="app">
      <TopBar
        health={health}
        config={config}
        query={query}
        setQuery={setQuery}
        ws={wsState}
        viewCount={events?.count ?? 0}
        onOpenLeft={() => setLeftOpen((v) => !v)}
        onOpenRight={() => setRightOpen((v) => !v)}
        onHelp={() => setShowHelp(true)}
        onBreakdown={breakdownKpi}
        onShare={shareView}
        shareCopied={shareCopied}
        onToggleNotify={toggleNotify}
        notifyOn={notifyOn}
      />

      <div className="stage">
        <SidePanel
          visible={visible}
          setVisible={setVisible}
          categoryCounts={categoryCounts}
          activeCats={activeCats}
          toggleCat={toggleCat}
          fences={fenceDefs}
          aoiMode={aoiMode}
          setAoiMode={setAoiMode}
          aoiRadiusKm={aoiRadiusKm}
          setAoiRadiusKm={setAoiRadiusKm}
          deleteFence={deleteFence}
          hotspots={config?.hotspots ?? {}}
          flyTo={flyTo}
          health={health}
          open={leftOpen}
          onClose={() => setLeftOpen(false)}
          onBreakdownSource={breakdownSource}
          onBreakdownCategory={breakdownCategory}
          onBreakdownCameras={() => breakdownCameras()}
          onBreakdownLayer={breakdownLayer}
          onExport={exportEvents}
          basemap={basemap}
          onBasemap={onBasemap}
          layerCounts={layerCounts}
        />

        <div className="map-col">
          <nav className={`map-views map-overlay ${filtersOpen ? "open" : ""}`} aria-label="Filtros de visibilidad del mapa">
            <button
              type="button"
              className="map-filters-toggle"
              aria-expanded={filtersOpen}
              aria-controls="map-quick-filters"
              onClick={() => setFiltersOpen((open) => !open)}
            >
              <Icon name="layers" size={16} />
              <span>Capas</span>
            </button>
            <div className="map-views-row map-views-filters">
              <span className="map-views-title">Capas</span>
              <div className="map-filters" id="map-quick-filters" role="group" aria-label="Capas visibles en el mapa">
                {QUICK_FILTERS.map((filter) => {
                  const on = visible[filter.key] !== false;
                  const count = quickCount(filter.key);
                  return (
                    <button
                      key={filter.key}
                      type="button"
                      className={`map-filter ${on ? "on" : "off"}`}
                      onClick={() => toggleVisible(filter.key)}
                      aria-pressed={on}
                      aria-label={`${on ? "Ocultar" : "Mostrar"} ${filter.label} en el mapa`}
                      title={`${on ? "Ocultar" : "Mostrar"} ${filter.label}${count !== null ? ` · ${fmtNumber(count)} disponibles` : ""}`}
                      data-filter={filter.key}
                      data-on={on}
                    >
                      <Icon name={filter.icon} size={13} />
                      <span>{filter.label}</span>
                      {count !== null && <b>{fmtNumber(count)}</b>}
                    </button>
                  );
                })}
              </div>
            </div>
          </nav>
          <MapView
            events={events}
            aircraft={aircraft}
            vessels={vessels}
            satellites={satellites}
            basemap={basemap}
            cameras={cameras}
            air={air}
            trains={trains}
            onCameraSelect={onCameraSelect}
            selectedCameraId={cameraId}
            fences={fencesGeo}
            visible={visible}
            selectedId={selected?.properties.id ?? null}
            onSelect={onSelect}
            onViewport={(b, z, c) => { setBbox(b); setZoom(z); setCenter(c); }}
            aoiMode={aoiMode}
            aoiRadiusKm={aoiRadiusKm}
            onCreateAoi={createFence}
            terrain={terrain}
            onActorSelect={onActorSelect}
            track={actorTrack}
            selectedActor={actor}
            follow={follow && !!actor}
            onBreakFollow={() => setFollow(false)}
            onBreakdownCluster={breakdownCluster}
            onPlaceSelect={onPlaceSelect}
          />
          <div className="map-tools map-overlay" role="toolbar" aria-label="Herramientas del mapa">
            <button
              type="button"
              className={`map-tool ${terrain ? "active" : ""}`}
              title="Terreno 3D (requiere conexión)"
              aria-label="Terreno 3D"
              aria-pressed={terrain}
              onClick={() => setTerrain((v) => !v)}
            >
              <Icon name="terrain" size={17} />
            </button>
            <button
              type="button"
              className="map-tool"
              title="Mi ubicación"
              aria-label="Mi ubicación"
              onClick={() => locateMe((lat, lon) => {
                const map = (window as any).__aegisMap;
                map?.easeTo({ center: [lon, lat], zoom: Math.max(Number(map.getZoom?.() ?? 9), 9), duration: 900 });
              })}
            >
              <Icon name="locate" size={17} />
            </button>
          </div>
        </div>

        <RightPanel
          open={rightOpen}
          tab={tab}
          threatHours={threatHours}
          onThreatWindow={setThreatHours}
          onPickThreat={(id: string) => { void selectById(id); }}
          setTab={(t) => { setTab(t); if (t === "alerts") setNewAlerts(0); }}
          selected={selected}
          onClearSelection={() => setSelected(null)}
          detail={detail}
          detailLoading={detailLoading}
          nearby={nearby}
          nearbyLoading={nearbyLoading}
          nearbyRadiusKn={nearbyRadiusKn}
          setNearbyRadiusKm={setNearbyRadiusKm}
          onGenerateBriefing={generateBriefing}
          briefing={briefing}
          briefingLoading={briefingLoading}
          onSelectById={selectById}
          onDownloadBriefing={downloadBriefing}
          alerts={alerts}
          alertsCount={criticalAlerts}
          origin={{ lat: center[1], lon: center[0] }}
          eventsTick={eventsTick}
          health={health}
          config={config}
          onTriggerSource={triggerSource}
          onBreakdownSource={breakdownSource}
          triggering={triggering}
          cameraId={cameraId}
          onClearCamera={() => setCameraId(null)}
          onFlyTo={(lat, lon) => flyTo(lat, lon, Math.max(9, zoom))}
          actorKind={actor?.kind ?? null}
          actorDetail={actorDetail}
          actorLoading={actorLoading}
          actorFollow={follow}
          onToggleFollow={() => setFollow((v) => !v)}
          onRecenterActor={recenterActor}
          onClearActor={clearActor}
          place={place}
          placeData={placeData}
          placeLoading={placeLoading}
          placeRadiusKm={placeRadiusKm}
          placeWindowH={placeWindowH}
          onPlaceWindow={setPlaceWindowH}
          onPlaceRadius={(km) => setPlaceRadiusKm(km)}
          onPlaceRefresh={() => setPlaceNonce((n) => n + 1)}
          onPlaceClean={clearPlace}
          onPlaceCenter={centerPlace}
          onPickPlaceEvent={selectById}
          onPickPlaceCamera={onCameraSelect}
          onPickPlaceActor={onActorSelect}
          onClose={() => setRightOpen(false)}
        />
        {compact && (leftOpen || rightOpen) && (
          <div className="scrim" onClick={closePanels} aria-hidden="true" />
        )}
      </div>

      <Timeline
        events={events?.features ?? []}
        hours={hours}
        setHours={setHours}
        onSelect={(f) => onSelect(f)}
        alertsCount={criticalAlerts}
        onOpenAlerts={() => { setTab("alerts"); setNewAlerts(0); setRightOpen(true); setLeftOpen(false); }}
      />

      {apiDown && (
        <div className="fatal" role="alert">
          <div className="fatal-card">
            <div className="fatal-title">No se puede alcanzar el backend</div>
            <div className="fatal-body">
              El cliente está cargado, pero <span className="mono">{apiUrl("/api/health")}</span>{" "}
              no responde. El motor OSINT vive en un proceso aparte y en este momento no está escuchando.
              Si el backend ya está en otra URL, abre esta página con{" "}
              <span className="mono">?api=https://tu-backend</span> o deja esa URL en{" "}
              <span className="mono">runtime-config.json</span>.
              <div className="fatal-err mono">{apiDown}</div>
            </div>
            <div className="btn-row">
              <button className="btn primary" onClick={retryApi}>Reintentar</button>
              <button className="btn" onClick={() => setShowHint((v) => !v)}>Cómo arrancarlo</button>
            </div>
            {showHint && (
              <pre className="fatal-cmds">{`# en la carpeta del proyecto
bash scripts/dev.sh          # compila y sirve en :8000
# o, con el backend ya instalado:
bash scripts/serve.sh        # supervisor con reinicio automático
make dev                     # atajo equivalente`}</pre>
            )}
          </div>
        </div>
      )}

      <Breakdown spec={breakdown} onClose={() => setBreakdown(null)} onPick={pickBreakdown} />

      <Help
        open={showHelp}
        onClose={() => setShowHelp(false)}
        onOpenLayers={() => { setShowHelp(false); setLeftOpen(true); }}
        hours={hours}
      />

      <div className="toasts">
        {toasts.map((t, i) => (
          <div key={`${t.ts}-${i}`} className={`toast ${t.severity === "critical" ? "critical" : ""}`}>
            <div className="toast-title">{t.title}</div>
            <div className="toast-msg">{t.message}</div>
            <div className="toast-msg faint">{timeAgo(t.ts)} · {t.fence_name || t.fence_id || "global"}</div>
          </div>
        ))}
      </div>
    </main>
  );
}
