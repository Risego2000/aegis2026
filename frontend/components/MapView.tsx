"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import maplibregl, { Map as MlMap, Popup } from "maplibre-gl";
import Supercluster from "supercluster";
import "maplibre-gl/dist/maplibre-gl.css";

import { eventFeatureToItem, type BreakdownItem } from "@/components/Breakdown";
import type { ActorKind, EventFeature, FeatureCollection, LiveCollection } from "@/lib/types";
import { categoryMeta } from "@/lib/format";
import { apiUrl } from "@/lib/api";
import { categoryIconData } from "@/lib/mapIcons";

type Props = {
  events: FeatureCollection | null;
  aircraft: LiveCollection | null;
  vessels: LiveCollection | null;
  satellites: LiveCollection | null;
  basemap?: string;              // "vectorial" | calles | oscuro | claro | satelite
  cameras?: LiveCollection | null;
  trains?: LiveCollection | null;
  air?: LiveCollection | null;
  fences: any | null;
  visible: Record<string, boolean>;
  selectedId: string | null;
  onSelect: (feature: EventFeature | null) => void;
  onViewport: (bbox: [number, number, number, number], zoom: number, center: [number, number]) => void;
  onSatelliteSelect?: (norad: number | null) => void;
  onActorSelect?: (kind: ActorKind, id: string) => void;
  onCameraSelect?: (id: string) => void;
  /** Clic en un núcleo urbano o en zona vacía: ficha del lugar pinchado. */
  onPlaceSelect?: (place: { lat: number; lon: number; name?: string; zoom: number }) => void;
  selectedCameraId?: string | null;
  onBreakFollow?: () => void;
  track: { geometry: { type: "LineString"; coordinates: [number, number][] } } | null;
  selectedActor: { kind: ActorKind; id: string } | null;
  follow: boolean;
  aoiMode: boolean;
  aoiRadiusKm: number;
  onCreateAoi: (lat: number, lon: number, radiusKm: number) => void;
  terrain: boolean;
  /** Al pulsar el número de un cúmulo: sus elementos, en memoria. */
  onBreakdownCluster?: (items: BreakdownItem[], zoomTo?: () => void) => void;
};

const EMPTY_FC = { type: "FeatureCollection", features: [] } as any;

/** Velocidad estimada en grados/segundo a partir de la velocidad y el rumbo
    que publica la fuente (aeronaves: nudos + track, buques: nudos + course). */
function driftVelocity(f: any): [number, number] | null {
  const pr = f.properties || {};
  const kn = Number(pr.speed_kn ?? pr.gs ?? pr.sog);
  const kmh = Number(pr.speed_kmh);
  const hdg = Number(pr.track ?? pr.course ?? pr.cog ?? pr.heading);
  if (!Number.isFinite(hdg)) return null;
  // trenes: el feed da km/h; aviones y barcos, nudos
  const kmS = Number.isFinite(kmh) && kmh > 0
    ? kmh / 3600
    : Number.isFinite(kn) && kn > 0 ? (kn * 1.852) / 3600 : 0;
  if (!kmS) return null;
  const rad = (hdg * Math.PI) / 180;
  const lat = Number(f.geometry?.coordinates?.[1]);
  const cosLat = Math.max(0.15, Math.cos((lat * Math.PI) / 180));
  return [
    (kmS * Math.sin(rad)) / (111.32 * cosLat),         // °/s en longitud
    (kmS * Math.cos(rad)) / 111.32,                    // °/s en latitud
  ];
}

function makeCanvas(size: number, draw: (ctx: CanvasRenderingContext2D) => void) {
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext("2d")!;
  draw(ctx);
  return ctx.getImageData(0, 0, size, size);
}

function planeIcon(size = 40) {
  return makeCanvas(size, (ctx) => {
    const s = size / 40;
    ctx.scale(s, s);
    ctx.fillStyle = "#ffffff";
    ctx.beginPath();
    ctx.moveTo(20, 3);
    ctx.lineTo(23.4, 17);
    ctx.lineTo(36, 27);
    ctx.lineTo(36, 31);
    ctx.lineTo(23, 26.5);
    ctx.lineTo(22, 34);
    ctx.lineTo(27, 37.5);
    ctx.lineTo(27, 39);
    ctx.lineTo(20, 37);
    ctx.lineTo(13, 39);
    ctx.lineTo(13, 37.5);
    ctx.lineTo(18, 34);
    ctx.lineTo(17, 26.5);
    ctx.lineTo(4, 31);
    ctx.lineTo(4, 27);
    ctx.lineTo(16.6, 17);
    ctx.closePath();
    ctx.fill();
  });
}

function shipIcon(size = 32) {
  return makeCanvas(size, (ctx) => {
    const s = size / 32;
    ctx.scale(s, s);
    ctx.fillStyle = "#ffffff";
    ctx.beginPath();
    ctx.moveTo(16, 3);
    ctx.lineTo(24, 13);
    ctx.lineTo(21, 27);
    ctx.lineTo(11, 27);
    ctx.lineTo(8, 13);
    ctx.closePath();
    ctx.fill();
  });
}

/** Tren visto desde arriba: morro redondeado, ventanas y bogies. */
function trainIcon(size = 34) {
  return makeCanvas(size, (ctx) => {
    const s = size / 34;
    ctx.scale(s, s);
    ctx.fillStyle = "#ffffff";
    // cuerpo
    ctx.beginPath();
    ctx.moveTo(17, 2);
    ctx.quadraticCurveTo(26, 2, 26, 11);
    ctx.lineTo(26, 26);
    ctx.quadraticCurveTo(26, 32, 17, 32);
    ctx.quadraticCurveTo(8, 32, 8, 26);
    ctx.lineTo(8, 11);
    ctx.quadraticCurveTo(8, 2, 17, 2);
    ctx.fill();
    // franja central (se recorta en modo SDF con icon-color)
    ctx.globalCompositeOperation = "destination-out";
    ctx.fillRect(13, 7, 8, 2.6);
    ctx.fillRect(13, 12, 8, 2.6);
    ctx.fillRect(13, 17, 8, 2.6);
    ctx.beginPath();
    ctx.moveTo(11, 24); ctx.lineTo(23, 24);
    ctx.lineTo(23, 26.6); ctx.lineTo(11, 26.6);
    ctx.closePath();
    ctx.fill();
    ctx.globalCompositeOperation = "source-over";
  });
}

function satIcon(size = 28) {
  return makeCanvas(size, (ctx) => {
    const c = size / 2;
    ctx.fillStyle = "#ffffff";
    ctx.beginPath();
    ctx.moveTo(c, 2);
    ctx.lineTo(size - 3, c);
    ctx.lineTo(c, size - 2);
    ctx.lineTo(3, c);
    ctx.closePath();
    ctx.fill();
    ctx.fillRect(c - 1.5, 2, 3, size - 4);
  });
}

function cameraIcon(size = 28) {
  return makeCanvas(size, (ctx) => {
    const s = size;
    // cuerpo de la cámara + objetivo
    ctx.fillStyle = "#ffffff";
    ctx.beginPath();
    ctx.roundRect(s * 0.16, s * 0.3, s * 0.5, s * 0.34, s * 0.08);
    ctx.fill();
    ctx.beginPath();
    ctx.moveTo(s * 0.66, s * 0.36);
    ctx.lineTo(s * 0.86, s * 0.26);
    ctx.lineTo(s * 0.86, s * 0.68);
    ctx.lineTo(s * 0.66, s * 0.58);
    ctx.closePath();
    ctx.fill();
    ctx.fillRect(s * 0.28, s * 0.16, s * 0.1, s * 0.14);
  });
}

function clusterIcon(count: number, color: string, size = 54) {
  const label = count >= 1000 ? `${(count / 1000).toFixed(1)}k` : String(count);
  const scale = 2;
  return makeCanvas(size * scale, (ctx) => {
    const c = (size * scale) / 2;
    const radius = c - 3 * scale;
    const grad = ctx.createRadialGradient(c, c, radius * 0.2, c, c, radius);
    grad.addColorStop(0, color + "ee");
    grad.addColorStop(1, color + "44");
    ctx.fillStyle = grad;
    ctx.beginPath();
    ctx.arc(c, c, radius, 0, Math.PI * 2);
    ctx.fill();
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.6 * scale;
    ctx.stroke();
    ctx.fillStyle = "#02181a";
    ctx.font = `700 ${Math.round(13 * scale)}px SFMono-Regular, Menlo, monospace`;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(label, c, c + 0.5 * scale);
    return null as any;
  });
}

const CAT_COLORS: Record<string, string> = {
  earthquake: "#ff7a45",
  disaster: "#ff3d71",
  wildfire: "#ffb703",
  conflict: "#ff2d2d",
  protest: "#b388ff",
  military: "#4dd0e1",
  diplomacy: "#64b5f6",
  economy: "#a5d6a7",
  traffic: "#fb923c",
  transport: "#a3e635",
  news: "#90a4ae",
};

/* --------------------------------------------------------------- geometry */
function circleRing(lat: number, lon: number, radiusKm: number, steps = 72): number[][] {
  const ring: number[][] = [];
  const dLat = radiusKm / 111.32;
  const cos = Math.max(0.05, Math.cos((lat * Math.PI) / 180));
  for (let i = 0; i <= steps; i++) {
    const a = (i / steps) * Math.PI * 2;
    ring.push([lon + (Math.sin(a) * dLat) / cos, lat + Math.cos(a) * dLat]);
  }
  return ring;
}

function graticule(): GeoJSON.FeatureCollection {
  const features: any[] = [];
  for (let lon = -180; lon <= 180; lon += 15) {
    const coords: number[][] = [];
    for (let lat = -85; lat <= 85; lat += 5) coords.push([lon, lat]);
    features.push({ type: "Feature", geometry: { type: "LineString", coordinates: coords }, properties: {} });
  }
  for (let lat = -75; lat <= 75; lat += 15) {
    const coords: number[][] = [];
    for (let lon = -180; lon <= 180; lon += 5) coords.push([lon, lat]);
    features.push({ type: "Feature", geometry: { type: "LineString", coordinates: coords }, properties: {} });
  }
  return { type: "FeatureCollection", features };
}

/** Estilo base con las capas geográficas servidas por la API configurada. */
const withApi = (style: any) => {
  const sources: any = { ...style.sources };
  for (const id of ["land", "countries", "places"]) {
    sources[id] = { ...sources[id], data: apiUrl(`/api/basemap/${id}`) };
  }
  return { ...style, sources };
};

const BASE_STYLE: any = {
  version: 8,
  projection: { type: "globe" },
  sky: {
    "sky-color": "#04070d",
    "horizon-color": "#0b2130",
    "fog-color": "#071019",
    "sky-horizon-blend": 0.6,
    "horizon-fog-blend": 0.6,
    "fog-ground-blend": 0.9,
    "atmosphere-blend": 0.7,
  },
  sources: {
    land: { type: "geojson", data: "/api/basemap/land" },
    countries: { type: "geojson", data: "/api/basemap/countries" },
    places: { type: "geojson", data: "/api/basemap/places" },
    graticule: { type: "geojson", data: graticule() as any },
  },
  layers: [
    { id: "bg", type: "background", paint: { "background-color": "#04070d" } },
    {
      id: "land-fill",
      type: "fill",
      source: "land",
      paint: { "fill-color": "#0f2030", "fill-opacity": 1 },
    },
    {
      id: "countries-fill",
      type: "fill",
      source: "countries",
      paint: {
        "fill-color": [
          "case",
          ["boolean", ["feature-state", "hover"], false],
          "#1a4257",
          "#122434",
        ],
        "fill-opacity": 0.92,
      },
    },
    {
      id: "countries-line",
      type: "line",
      source: "countries",
      paint: { "line-color": "#2e617d", "line-width": 0.75, "line-opacity": 0.95 },
    },
    {
      id: "graticule",
      type: "line",
      source: "graticule",
      paint: { "line-color": "#16394a", "line-width": 0.45, "line-opacity": 0.5, "line-dasharray": [1, 3] },
    },
    {
      id: "places",
      type: "circle",
      source: "places",
      minzoom: 2.6,
      /* de cerca, las etiquetas del mapa ya nombran las poblaciones: dibujarlas
         todas a nivel de calle solo añade ruido y carga de GPU */
      maxzoom: 9.5,
      paint: {
        "circle-radius": [
          "interpolate", ["linear"], ["zoom"],
          2.6, ["case", ["<=", ["get", "rank"], 3], 2.2, ["<=", ["get", "rank"], 6], 1.3, 0.8],
          5, ["case", ["<=", ["get", "rank"], 3], 3.0, ["<=", ["get", "rank"], 6], 2.1, 1.3],
          10, ["case", ["<=", ["get", "rank"], 3], 4.2, ["<=", ["get", "rank"], 6], 3.0, 2.0],
        ],
        "circle-color": "#8fb8cd",
        "circle-opacity": ["interpolate", ["linear"], ["zoom"], 2.6, 0.35, 5, 0.6, 9, 0.8],
        "circle-stroke-color": "#05080f",
        "circle-stroke-width": 0.5,
      },
    },
  ],
};

/* -------------------------------------------------------------------- map */
/** 
 * `queryRenderedFeatures` devuelve los arrays/objetos de un GeoJSON como texto
 * (`'["gdelt"]'`). Antes de entregar el evento a React hay que rehidratarlos, o
 * cualquier `.join()` sobre `sources` revienta la vista.
 */
function hydrateProps(props: Record<string, any>): Record<string, any> {
  const out: Record<string, any> = { ...props };
  for (const key of Object.keys(out)) {
    const value = out[key];
    if (typeof value === "string" && (value.startsWith("[") || value.startsWith("{"))) {
      try { out[key] = JSON.parse(value); } catch { /* se deja como está */ }
    }
  }
  return out;
}

export default function MapView(props: Props) {
  const {
    events, aircraft, vessels, satellites, fences, visible, selectedId,
    onSelect, onViewport, onSatelliteSelect, onActorSelect, onBreakFollow, aoiMode, aoiRadiusKm, onCreateAoi, terrain,
    track, selectedActor, follow, onBreakdownCluster,
    cameras, air, trains, onCameraSelect, selectedCameraId, basemap = "oscuro", onPlaceSelect,
  } = props;

  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<MlMap | null>(null);
  const [ready, setReady] = useState(false);
  const [hover, setHover] = useState<string | null>(null);
  const [pending, setPending] = useState<{ lat: number; lon: number } | null>(null);
  const [layersReady, setLayersReady] = useState(false);
  const prevPos = useRef<Record<string, Map<string, [number, number]>>>({});
  const selectionPos = useRef<[number, number] | null>(null);
  // objetivos de interpolación persistentes: un sondeo de otra capa no debe
  // reiniciar ni borrar la animación en curso
  const targetsRef = useRef<Record<string, { feats: any[]; from: Map<string, [number, number]>; t0: number; dur: number }>>({});
  const [glError, setGlError] = useState<string | null>(null);

  const eventIndex = useRef<any>(null);
  const camIndex = useRef<any>(null);
  const acIndex = useRef<any>(null);
  const vesselIndex = useRef<any>(null);
  const orbitPopup = useRef<Popup | null>(null);

  /* Si la configuración de la API se resuelve después de crear el estilo
     (`runtime-config.json` o `?api=`), se recargan las capas base con la URL
     definitiva. En mismo origen no hay nada que hacer. */
  useEffect(() => {
    const apply = () => {
      const map = mapRef.current;
      if (!map || apiUrl("/api/basemap/land") === "/api/basemap/land") return;
      for (const id of ["land", "countries", "places"]) {
        const src = map.getSource(id) as maplibregl.GeoJSONSource | undefined;
        src?.setData(apiUrl(`/api/basemap/${id}`));
      }
    };
    apply();
    window.addEventListener("aegis:api-ready", apply);
    return () => window.removeEventListener("aegis:api-ready", apply);
  }, []);

  /* ------------------------------------------------------------- init map */
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    let map: MlMap;
    try {
      map = new maplibregl.Map({
      container: containerRef.current,
      style: withApi(BASE_STYLE),
      center: [8, 26],
      zoom: 1.55,
      minZoom: 0.6,
      maxZoom: 14,
      attributionControl: false,
      dragRotate: true,
      pitchWithRotate: true,
        renderWorldCopies: true,
      });
    } catch (err: any) {
      setGlError(String(err?.message ?? err));
      return;
    }

    map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), "top-right");

    /* --- Geolocalización: centra el mapa en el usuario y deja un pulso en su
       posición. La ubicación se pide solo al pulsar (nunca al cargar) y no
       sale del navegador: el servidor no la recibe. --- */
    class MeControl implements maplibregl.IControl {
      private map?: maplibregl.Map;
      private el?: HTMLButtonElement;
      private watch?: number;
      onAdd(map: maplibregl.Map) {
        this.map = map;
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "maplibregl-ctrl-icon maplibregl-ctrl-geolocate";
        btn.title = "Mi ubicación: centra el mapa donde estás";
        btn.setAttribute("aria-label", "Mi ubicación");
        btn.innerHTML =
          '<svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">' +
          '<circle cx="12" cy="12" r="3.2" fill="currentColor"/>' +
          '<circle cx="12" cy="12" r="7.2" fill="none" stroke="currentColor" stroke-width="1.7"/>' +
          '<path d="M12 1.4v3.4M12 19.2v3.4M1.4 12h3.4M19.2 12h3.4" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/>' +
          "</svg>";
        btn.onclick = () => {
          if (!navigator.geolocation) return;
          btn.classList.add("active");
          const pintar = (pos: GeolocationPosition) => {
            const { latitude, longitude } = pos.coords;
            const src = map.getSource("me") as maplibregl.GeoJSONSource | undefined;
            src?.setData({
              type: "FeatureCollection",
              features: [{ type: "Feature", geometry: { type: "Point", coordinates: [longitude, latitude] }, properties: {} }],
            } as any);
            map.easeTo({ center: [longitude, latitude], zoom: Math.max(map.getZoom(), 9), duration: 900 });
            window.dispatchEvent(new CustomEvent("aegis:me", { detail: { lat: latitude, lon: longitude } }));
          };
          navigator.geolocation.getCurrentPosition(pintar, () => btn.classList.remove("active"), {
            enableHighAccuracy: true, timeout: 12000, maximumAge: 30000,
          });
        };
        const wrap = document.createElement("div");
        wrap.className = "maplibregl-ctrl maplibregl-ctrl-group";
        wrap.appendChild(btn);
        this.el = btn;
        return wrap;
      }
      onRemove() { this.el?.removeEventListener("click", () => {}); this.map = undefined; }
    }
    map.addControl(new MeControl(), "top-right");

    /** Los controles nativos del motor traen textos en inglés («Zoom in»,
     * «Drag to rotate map, click to reset north»): se traducen en el DOM y se
     * vuelven a traducir tras cada interacción de la brújula. */
    const traducirControles = () => {
      const fijar = (sel: string, texto: string) => {
        const el = map.getContainer().querySelector<HTMLElement>(sel);
        if (!el) return;
        el.setAttribute("title", texto);
        el.setAttribute("aria-label", texto);
      };
      fijar(".maplibregl-ctrl-zoom-in", "Acercar");
      fijar(".maplibregl-ctrl-zoom-out", "Alejar");
      fijar(".maplibregl-ctrl-compass", "Arrastra para girar el mapa; pulsa para volver al norte");
      fijar(".maplibregl-ctrl-attrib-button", "Mostrar u ocultar la atribución del mapa");
      fijar(".maplibregl-ctrl-fullscreen", "Pantalla completa");
    };
    traducirControles();
    map.on("rotate", traducirControles);
    map.on("load", traducirControles);
    map.addControl(new maplibregl.ScaleControl({ maxWidth: 90, unit: "metric" }), "bottom-right");
    map.addControl(
      new maplibregl.AttributionControl({
        compact: true,
        customAttribution:
          "© colaboradores de OpenStreetMap · Esri · Natural Earth · adsb.lol · USGS · GDACS · GDELT · Celestrak",
      }),
      "bottom-right"
    );

    map.on("load", () => {
      // --- icons ---
      // Iconos característicos: cada capa y cada categoría de suceso tiene el
      // suyo (avión, caza, helicóptero, barco, satélite, tren, metro, cámara…).
      const ICON_NAMES = [
        "plane", "milPlane", "statePlane", "heli", "drone", "ship", "sat", "cam",
        "train", "metro", "earthquake", "cyclone", "fire", "conflict", "protest",
        "military", "diplomacy", "economy", "news", "traffic", "train", "generic", "pin",
      ];
      for (const name of new Set(ICON_NAMES)) {
        if (!map.hasImage(name)) map.addImage(name, categoryIconData(name === "train" ? "train" : name), { sdf: true });
      }
      for (const [n, color] of [[2, "#35e0d0"], [10, "#35e0d0"], [50, "#ffd166"], [200, "#ff9f0a"], [1000, "#ff3d71"]] as [number, string][]) {
        map.addImage(`cluster-${n}`, clusterIcon(n, color), { pixelRatio: 2 });
      }

      // --- dynamic sources ---
      map.addSource("events", { type: "geojson", data: EMPTY_FC, generateId: true });
      // eventos con extensión territorial (avisos NWS, ciclones GDACS, incendios EONET)
      map.addSource("event-areas", { type: "geojson", data: EMPTY_FC });
      // estela del elemento seleccionado + halo pulsante
      map.addSource("trail", { type: "geojson", data: EMPTY_FC });
      map.addSource("selection", { type: "geojson", data: EMPTY_FC });
      map.addSource("trail-head", { type: "geojson", data: EMPTY_FC });
      // capas de movimiento interpolado: al acercar el zoom, los iconos se
      // desplazan de forma continua entre sondeos en vez de saltar
      map.addSource("aircraft-motion", { type: "geojson", data: EMPTY_FC });
      map.addSource("vessel-motion", { type: "geojson", data: EMPTY_FC });
      map.addSource("aircraft", { type: "geojson", data: EMPTY_FC });
      map.addSource("vessels", { type: "geojson", data: EMPTY_FC });
      map.addSource("satellites", { type: "geojson", data: EMPTY_FC });
      map.addSource("cameras", { type: "geojson", data: EMPTY_FC });
      map.addSource("air", { type: "geojson", data: EMPTY_FC });
      map.addSource("trains", { type: "geojson", data: EMPTY_FC });
      map.addSource("fences", { type: "geojson", data: EMPTY_FC });
      map.addSource("aoi", { type: "geojson", data: EMPTY_FC });
      map.addSource("orbit", { type: "geojson", data: EMPTY_FC });
      // vías que usan los medios vigilados: ferrocarril y derrotas marítimas.
      // Se descargan EN CUANTO se pasa del zoom 3 (a escala mundial no aportan
      // y 6 MB de JSON retendrían el hilo principal en el arranque).
      map.addSource("railways", { type: "geojson", data: EMPTY_FC });
      map.addSource("roads", { type: "geojson", data: EMPTY_FC });
      map.addSource("me", { type: "geojson", data: EMPTY_FC });
      map.addSource("sealanes", { type: "geojson", data: EMPTY_FC });
      map.addSource("train-motion", { type: "geojson", data: EMPTY_FC });

      // --- fondo de mapa detallado (teselas servidas por el backend) ---
      // Se añaden antes que nada para que queden por debajo del resto de capas.
      // formato y zoom máximo de cada proveedor (los grises de Esri llegan a 16)
      const BASEMAPS: Record<string, { ext: string; maxzoom: number }> = {
        calles: { ext: "png", maxzoom: 19 },
        oscuro: { ext: "jpg", maxzoom: 16 },
        claro: { ext: "jpg", maxzoom: 16 },
        satelite: { ext: "jpg", maxzoom: 19 },
        // capas transparentes: solo nombres de calle y de lugar, encima de la base
        oscuro_ref: { ext: "png", maxzoom: 16 },
        claro_ref: { ext: "png", maxzoom: 16 },
        // red de carreteras y ferrocarril (transparente, va sobre cualquier fondo)
        transporte: { ext: "png", maxzoom: 19 },
        // derrotas marítimas con escala (transparente)
        oceanoref: { ext: "png", maxzoom: 13 },
      };
      // Ojo: hay una capa `bg` (background) al principio del estilo. Las teselas
      // deben ir JUSTO ENCIMA de ella; si se insertan antes, el fondo la tapa y
      // el mapa se ve negro aunque las teselas se hayan descargado.
      const underLand = map.getLayer("land-fill") ? "land-fill" : undefined;
      // las etiquetas van justo debajo de los datos pero por encima de su base
      const labelAnchor = map.getLayer("land-fill") ? "land-fill" : undefined;
      // ojo: el orden importa — cada una se apila encima de la anterior; la red
      // de transporte y las derrotas marítimas quedan por ENCIMA de todas
      const ORDER = ["calles", "oscuro", "claro", "satelite", "oscuro_ref", "claro_ref", "oceanoref", "transporte"];
      for (const id of ORDER) {
        const spec = BASEMAPS[id];
        if (!spec) continue;
        map.addSource(`base-${id}`, {
          type: "raster",
          tiles: [`/api/tiles/${id}/{z}/{x}/{y}.${spec.ext}`],
          tileSize: 256,
          maxzoom: spec.maxzoom,
          attribution: "© colaboradores de OpenStreetMap · Esri",
        });
        map.addLayer(
          {
            id: `base-${id}-raster`,
            type: "raster",
            source: `base-${id}`,
            layout: { visibility: "none" },
            paint: {
              "raster-opacity": id.endsWith("_ref") ? 0.95 : 1,
              "raster-fade-duration": 200,
            },
          },
          underLand
        );
      }

      // --- vías que usan los medios vigilados -------------------------
      // Ferrocarril (Natural Earth 10m) y derrotas marítimas reales
      // (IMF PortWatch, derivadas de AIS). Se dibujan sobre CUALQUIER fondo.
      map.addLayer({
        id: "sealanes-line", type: "line", source: "sealanes",
        layout: { "line-cap": "round", "line-join": "round" },
        paint: {
          "line-color": "#3aa6ff",
          "line-width": ["interpolate", ["linear"], ["zoom"], 0, 0.4, 4, 0.8, 8, 1.3, 12, 2],
          "line-opacity": ["interpolate", ["linear"], ["zoom"], 0, 0.35, 6, 0.5, 12, 0.6],
          "line-dasharray": [2.2, 1.8],
        },
      });
      // Red viaria: línea continua, por debajo del ferrocarril.
      map.addLayer({
        id: "roads-line", type: "line", source: "roads",
        minzoom: 5.8,
        layout: { "line-cap": "round", "line-join": "round" },
        paint: {
          "line-color": ["match", ["coalesce", ["get", "c"], 3], 1, "#8fa6c4", 2, "#6d8299", "#556575"],
          "line-width": ["interpolate", ["linear"], ["zoom"],
            2.2, 0.4, 6, 0.8, 10, 1.4, 14, 2.6],
          "line-opacity": ["interpolate", ["linear"], ["zoom"], 2.2, 0.28, 6, 0.5, 10, 0.7],
        },
      });
      // Ferrocarril: línea discontinua y en otro color, como pide la lectura
      // cartográfica clásica (carretera continua / vía discontinua).
      map.addLayer({
        id: "railways-line", type: "line", source: "railways",
        minzoom: 5.9,
        layout: { "line-cap": "butt", "line-join": "round" },
        paint: {
          "line-color": ["match", ["coalesce", ["get", "c"], 2], 1, "#ffd9a0", "#e8b06a"],
          "line-width": ["interpolate", ["linear"], ["zoom"],
            2.5, 0.8, 7, 1.4, 11, 2.2, 14, 3.1],
          "line-dasharray": [
            "step", ["zoom"],
            ["literal", [3, 2]], 7,
            ["literal", [3.2, 1.8]], 11,
            ["literal", [3.6, 1.6]],
          ],
          "line-opacity": ["interpolate", ["linear"], ["zoom"], 2.5, 0.55, 6, 0.8, 10, 0.95],
        },
      });

      // --- mi ubicación (si el usuario la comparte) ---
      map.addLayer({
        id: "me-halo", type: "circle", source: "me",
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 2, 10, 8, 26, 14, 60],
          "circle-color": "#38bdf8", "circle-opacity": 0.12,
          "circle-stroke-color": "#38bdf8", "circle-stroke-width": 1,
          "circle-stroke-opacity": 0.5,
        },
      });
      map.addLayer({
        id: "me-dot", type: "circle", source: "me",
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 2, 3, 8, 5, 14, 8],
          "circle-color": "#38bdf8",
          "circle-stroke-color": "#04131f", "circle-stroke-width": 1.6,
        },
      });

      // --- geofences ---
      map.addLayer({
        id: "fence-fill", type: "fill", source: "fences",
        paint: { "fill-color": "#35e0d0", "fill-opacity": 0.05 },
      });
      map.addLayer({
        id: "fence-line", type: "line", source: "fences",
        paint: { "line-color": "#35e0d0", "line-width": 1.4, "line-dasharray": [3, 2], "line-opacity": 0.85 },
      });
      map.addLayer({
        id: "aoi-fill", type: "fill", source: "aoi",
        paint: { "fill-color": "#ffd166", "fill-opacity": 0.09 },
      });
      map.addLayer({
        id: "aoi-line", type: "line", source: "aoi",
        paint: { "line-color": "#ffd166", "line-width": 1.6, "line-dasharray": [2, 2] },
      });

      // --- orbit trail ---
      map.addLayer({
        id: "orbit-line", type: "line", source: "orbit",
        paint: { "line-color": "#7ee7ff", "line-width": 1.1, "line-opacity": 0.6, "line-dasharray": [2, 2] },
      });

      // --- satellites ---
      // De lejos, 1.300 iconos simultáneos cuestan más memoria de la que aportan:
      // a escala global se dibujan como puntos (baratos y legibles) y el icono
      // en forma de satélite aparece al acercarse, donde sí se distingue.
      map.addLayer({
        id: "sat-dots", type: "circle", source: "satellites", maxzoom: 2.5,
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 0, 0.8, 2.5, 1.6],
          "circle-color": "#7ee7ff", "circle-opacity": 0.55,
        },
      });
      // icono de satélite (cuerpo + paneles + antena) desde z2.5, creciendo con
      // el zoom: 0,42 → 0,62 → 0,95 → 1,4
      map.addLayer({
        id: "sat-points", type: "symbol", source: "satellites", minzoom: 2.5,
        layout: {
          "icon-image": "sat",
          "icon-size": ["interpolate", ["linear"], ["zoom"], 2.5, 0.42, 5, 0.62, 9, 0.95, 13, 1.4],
          "icon-allow-overlap": true, "icon-ignore-placement": true,
        },
        paint: { "icon-color": "#7ee7ff", "icon-opacity": 0.62 },
      });

      // --- trenes de Renfe (GTFS-RT): pocos, siempre por encima ---

      map.addLayer({
        id: "train-points", type: "symbol", source: "trains",
        layout: {
          // cercanías → tren urbano; media/larga distancia y AVE → tren clásico
          "icon-image": ["match", ["coalesce", ["get", "service"], "tren"],
            "cercanías", "metro",
            "train"],
          "icon-size": ["interpolate", ["linear"], ["zoom"], 1, 0.3, 5, 0.62, 9, 1.05, 13, 1.45],
          "icon-rotate": ["coalesce", ["get", "track"], 0],
          "icon-rotation-alignment": "map",
          // todos los trenes visibles siempre, aunque se solapen
          "icon-allow-overlap": true,
          "icon-ignore-placement": true,
        },
        paint: {
          "icon-color": [
            "case",
            ["==", ["coalesce", ["get", "network"], ""], "amtrak"], "#9ecbff",
            ["match", ["coalesce", ["get", "service"], "tren"],
              "alta velocidad", "#ff6b9d",
              "bajo coste", "#c084fc",
              "larga distancia", "#ffd166",
              "media distancia", "#8ee6a8",
              "cercanías", "#ffb454",
              "#ffb454"]],
          "icon-halo-color": "rgba(10,6,0,0.85)",
          "icon-halo-width": 0.8,
        },
      });
      map.addLayer({
        id: "train-labels", type: "symbol", source: "trains",
        minzoom: 8.5,
        layout: {
          "text-field": ["coalesce", ["get", "line"], ""],
          "text-size": 10,
          "text-offset": [0, 1.25],
          "text-anchor": "top",
          "text-allow-overlap": false,
        },
        paint: { "text-color": "#ffd9a0", "text-halo-color": "rgba(4,8,12,0.9)", "text-halo-width": 1.2 },
      });

      // --- calidad del aire (Sensor.Community) ---
      map.addLayer({
        id: "air-halo", type: "circle", source: "air",
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 2, 4, 8, 12, 12, 26],
          "circle-color": [
            "interpolate", ["linear"], ["coalesce", ["get", "pm25"], ["get", "pm10"], 0],
            0, "#30d158", 10, "#a5d6a7", 25, "#ffd60a", 50, "#ff9f0a", 90, "#ff3d71",
          ],
          "circle-opacity": 0.18,
          "circle-blur": 0.6,
        },
      });
      map.addLayer({
        id: "air-points", type: "circle", source: "air",
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 2, 1.4, 8, 3, 12, 6],
          "circle-color": [
            "interpolate", ["linear"], ["coalesce", ["get", "pm25"], ["get", "pm10"], 0],
            0, "#30d158", 10, "#a5d6a7", 25, "#ffd60a", 50, "#ff9f0a", 90, "#ff3d71",
          ],
          "circle-stroke-width": 0.5,
          "circle-stroke-color": "rgba(4,10,16,0.6)",
          "circle-opacity": 0.9,
        },
      });

      // --- cámaras públicas (4 redes, ~5.800) ---
      map.addLayer({
        id: "camera-clusters", type: "circle", source: "cameras", maxzoom: 8.5, filter: ["has", "point_count"],
        paint: {
          "circle-color": "rgba(179,136,255,0.22)",
          "circle-stroke-color": "#b388ff", "circle-stroke-width": 1.2,
          "circle-radius": ["step", ["get", "point_count"], 13, 10, 17, 100, 22],
        },
      });
      map.addLayer({
        id: "camera-cluster-labels", type: "symbol", source: "cameras", maxzoom: 8.5, filter: ["has", "point_count"],
        layout: {
          "text-field": ["get", "point_count_abbreviated"],
          "text-font": ["Noto Sans Regular"], "text-size": 10,
        },
        paint: { "text-color": "#e6d8ff" },
      });
      map.addLayer({
        id: "camera-points", type: "symbol", source: "cameras", minzoom: 8, filter: ["!", ["has", "point_count"]],
        layout: {
          "icon-image": "cam",
          "icon-size": ["interpolate", ["linear"], ["zoom"], 3, 0.55, 8, 0.95, 13, 1.3],
          "icon-allow-overlap": true, "icon-ignore-placement": true,
        },
        paint: {
          // halo fino: separa la cámara del callejero sin engordar el SDF
          "icon-color": ["case", ["==", ["get", "online"], false], "#5b5566", "#7c3aed"],
          "icon-halo-color": "#ffffff",
          "icon-halo-width": 0.5,
          "icon-opacity": 0.95,
        },
      });

      // --- vessels ---
      map.addLayer({
        id: "vessel-points", type: "symbol", source: "vessels",
        layout: {
          "icon-image": "ship",
          "icon-size": ["interpolate", ["linear"], ["zoom"], 1, 0.28, 6, 0.62, 10, 0.95],
          "icon-rotate": ["coalesce", ["get", "course"], 0],
          "icon-rotation-alignment": "map",
          "icon-allow-overlap": true,
          "icon-ignore-placement": true,
        },
        paint: {
          "icon-color": ["interpolate", ["linear"], ["coalesce", ["get", "speed_kn"], 0], 0, "#4a7a8c", 12, "#57d9c3", 25, "#ffd166", 33, "#ff3d71"],
          "icon-opacity": 0.9,
        },
      });

      // --- aircraft ---
      map.addLayer({
        id: "aircraft-points", type: "symbol", source: "aircraft",
        layout: {
          // caza (ala delta) para militares, ala recta para vuelos de Estado
          "icon-image": ["match", ["coalesce", ["get", "mil"], ""],
            "military", "milPlane",
            "state", "statePlane",
            "plane"],
          "icon-size": ["interpolate", ["linear"], ["zoom"], 1, 0.3, 5, 0.62, 9, 1.05, 13, 1.35],
          "icon-rotate": ["coalesce", ["get", "track"], 0],
          "icon-rotation-alignment": "map",
          "icon-allow-overlap": true,
          "icon-ignore-placement": true,
        },
        paint: {
          "icon-color": [
            "case",
            ["==", ["coalesce", ["get", "emergency"], false], true], "#ff3d71",
            ["==", ["coalesce", ["get", "mil"], ""], "military"], "#ffd166",
            ["==", ["coalesce", ["get", "mil"], ""], "state"], "#c3f0ff",
            ["interpolate", ["linear"], ["coalesce", ["get", "altitude_ft"], 0], 0, "#3b7d8f", 10000, "#4dd0e1", 25000, "#a5e8ff", 40000, "#ffffff"],
          ],
          // halo constante: una expresión por dato en icon-halo-width obliga a
          // MapLibre a regenerar el SDF de cada icono en cada fotograma
          "icon-halo-width": 0.6,
          "icon-halo-color": "rgba(4,7,13,0.75)",
        },
      });

      // --- movimiento continuo (aeronaves y buques al acercar el zoom) ---
      map.addLayer({
        id: "aircraft-motion-layer", type: "symbol", source: "aircraft-motion", minzoom: 5,
        layout: {
          "icon-image": ["match", ["coalesce", ["get", "mil"], ""],
            "military", "milPlane",
            "state", "statePlane",
            "plane"],
          "icon-size": ["interpolate", ["linear"], ["zoom"], 5, 0.6, 9, 1.05, 13, 1.35],
          "icon-rotate": ["coalesce", ["get", "track"], 0],
          "icon-rotation-alignment": "map",
          "icon-allow-overlap": true,
          "icon-ignore-placement": true,
        },
        paint: {
          "icon-color": ["interpolate", ["linear"], ["coalesce", ["get", "altitude_ft"], 0],
            0, "#3b7d8f", 10000, "#4dd0e1", 25000, "#a5e8ff", 40000, "#ffffff"],
          "icon-halo-width": 0.6,
          "icon-halo-color": "rgba(4,7,13,0.7)",
          "icon-opacity": ["interpolate", ["linear"], ["coalesce", ["get", "age_s"], 0],
            10, 1, 60, 0.92, 150, 0.6, 420, 0.28],
        },
      });
      map.addLayer({
        id: "vessel-motion-layer", type: "symbol", source: "vessel-motion", minzoom: 4,
        layout: {
          "icon-image": "ship",
          "icon-size": ["interpolate", ["linear"], ["zoom"], 4, 0.5, 9, 0.9],
          "icon-rotate": ["coalesce", ["get", "course"], 0],
          "icon-rotation-alignment": "map",
          "icon-allow-overlap": true,
          "icon-ignore-placement": true,
        },
        paint: {
          "icon-color": ["interpolate", ["linear"], ["coalesce", ["get", "speed_kn"], 0],
            0, "#4a7a8c", 12, "#57d9c3", 25, "#ffd166", 33, "#ff3d71"],
          "icon-halo-width": 0.6,
          "icon-halo-color": "rgba(4,7,13,0.7)",
          "icon-opacity": ["interpolate", ["linear"], ["coalesce", ["get", "age_s"], 0],
            60, 1, 300, 0.85, 900, 0.55, 2400, 0.25],
        },
      });
      // trenes: los que se mueven de verdad, con el mismo icono pero avanzando
      map.addLayer({
        id: "train-motion-layer", type: "symbol", source: "train-motion", minzoom: 4,
        layout: {
          "icon-image": ["match", ["coalesce", ["get", "service"], "tren"],
            "cercanías", "metro",
            "train"],
          "icon-size": ["interpolate", ["linear"], ["zoom"], 4, 0.55, 9, 1.05, 13, 1.45],
          "icon-rotate": ["coalesce", ["get", "track"], 0],
          "icon-rotation-alignment": "map",
          "icon-allow-overlap": true,
          "icon-ignore-placement": true,
        },
        paint: {
          "icon-color": [
            "case",
            ["==", ["coalesce", ["get", "network"], ""], "amtrak"], "#9ecbff", "#ffb454"],
          "icon-halo-color": "rgba(10,6,0,0.85)",
          "icon-halo-width": 0.8,
        },
      });

      // a partir de este zoom mandan las capas animadas (sin duplicar iconos)
      ["vessel-points", "aircraft-points"].forEach((id) => {
        try { map.setLayerZoomRange(id, 0, id === "aircraft-points" ? 5 : 4); } catch {}
      });
      try { map.setLayerZoomRange("train-points", 0, 4); } catch {}

      // --- events: clusters + points ---
      map.addLayer({
        id: "trail-glow", type: "line", source: "trail",
        layout: { "line-cap": "round", "line-join": "round" },
        paint: { "line-color": "#35e0d0", "line-width": 7, "line-opacity": 0.12, "line-blur": 3 },
      });
      map.addLayer({
        id: "trail-line", type: "line", source: "trail",
        layout: { "line-cap": "round", "line-join": "round" },
        paint: {
          "line-color": ["case", ["==", ["get", "kind"], "satellites"], "#7ee7ff", "#35e0d0"],
          "line-width": 1.8,
          "line-opacity": 0.9,
          "line-dasharray": [2, 1.6],
        },
      });
      map.addLayer({
        id: "trail-head-glow", type: "circle", source: "trail-head",
        paint: {
          "circle-radius": 11,
          "circle-color": "#35e0d0",
          "circle-opacity": 0.12,
          "circle-blur": 1.6,
        },
      });
      map.addLayer({
        id: "trail-head-dot", type: "circle", source: "trail-head",
        paint: { "circle-radius": 3.4, "circle-color": "#eafffb", "circle-opacity": 0.95 },
      });
      map.addLayer({
        id: "selection-halo", type: "circle", source: "selection",
        paint: {
          "circle-radius": 18,
          "circle-color": "rgba(53,224,208,0.10)",
          "circle-stroke-width": 1.6,
          "circle-stroke-color": "#35e0d0",
          "circle-opacity": 0.9,
        },
      });
      map.addLayer({
        id: "event-areas-fill", type: "fill", source: "event-areas",
        filter: ["==", ["geometry-type"], "Polygon"],
        paint: {
          "fill-color": ["match", ["get", "category"],
            "wildfire", "#ffb703", "earthquake", "#ff7a45", "conflict", "#ff2d2d",
            "protest", "#b388ff", "military", "#4dd0e1", "diplomacy", "#64b5f6",
            "economy", "#a5d6a7", "#ff3d71"],
          "fill-opacity": 0.16,
        },
      });
      map.addLayer({
        id: "event-areas-line", type: "line", source: "event-areas",
        paint: {
          "line-color": ["match", ["get", "category"],
            "wildfire", "#ffb703", "earthquake", "#ff7a45", "conflict", "#ff2d2d",
            "protest", "#b388ff", "military", "#4dd0e1", "diplomacy", "#64b5f6",
            "economy", "#a5d6a7", "#ff3d71"],
          "line-width": 1.4, "line-opacity": 0.75, "line-dasharray": [2, 1.5],
        },
      });
      map.addLayer({
        id: "event-clusters", type: "circle", source: "events",
        filter: ["has", "point_count"],
        paint: {
          "circle-color": "rgba(0,0,0,0)",
          "circle-radius": ["step", ["get", "point_count"], 16, 10, 21, 50, 26, 200, 32, 1000, 38],
          "circle-stroke-width": 0,
        },
      });
      map.addLayer({
        id: "event-cluster-labels", type: "symbol", source: "events",
        filter: ["has", "point_count"],
        layout: {
          "icon-image": [
            "step", ["get", "point_count"],
            "cluster-2", 10, "cluster-10", 50, "cluster-50", 200, "cluster-200", 1000, "cluster-1000",
          ],
          "icon-size": ["interpolate", ["linear"], ["zoom"], 1, 0.55, 5, 0.8, 9, 1],
          "icon-allow-overlap": true,
        },
      });
      // Cada categoría de suceso lleva su icono (terremoto, ciclón, llama,
      // explosión, multitud, estrella militar, banderas, barras, aviso…).
      // El tamaño crece con el zoom: de lejos se lee el color, de cerca la forma.
      map.addLayer({
        id: "event-points", type: "symbol", source: "events",
        filter: ["!", ["has", "point_count"]],
        layout: {
          "icon-image": ["match", ["get", "category"],
            "earthquake", "earthquake",
            "disaster", "cyclone",
            "wildfire", "fire",
            "conflict", "conflict",
            "protest", "protest",
            "military", "military",
            "diplomacy", "diplomacy",
            "economy", "economy",
            "traffic", "traffic",
            "trafico", "traffic",
            "transport", "train",
            "transporte", "train",
            "news",
            "news",
            "news"],
          "icon-size": ["interpolate", ["linear"], ["zoom"],
            1, 0.28, 4, 0.38, 7, 0.52, 10, 0.68, 14, 0.9],
          "icon-allow-overlap": true,
          "icon-ignore-placement": true,
        },
        paint: {
          "icon-color": ["match", ["get", "category"],
            "earthquake", CAT_COLORS.earthquake,
            "disaster", CAT_COLORS.disaster,
            "wildfire", CAT_COLORS.wildfire,
            "conflict", CAT_COLORS.conflict,
            "protest", CAT_COLORS.protest,
            "military", CAT_COLORS.military,
            "diplomacy", CAT_COLORS.diplomacy,
            "economy", CAT_COLORS.economy,
            "traffic", CAT_COLORS.traffic || "#f97316",
            "trafico", CAT_COLORS.traffic || "#f97316",
            "transport", "#a3e635",
            "transporte", "#a3e635",
            CAT_COLORS.news],
          "icon-halo-color": "rgba(4,7,13,0.9)",
          "icon-halo-width": 1.2,
          "icon-opacity": ["case", ["==", ["coalesce", ["get", "sources_count"], 1], 1], 0.82, 1],
        },
      });
      map.addLayer({
        id: "event-halo", type: "circle", source: "events",
        filter: ["all", ["!", ["has", "point_count"]], ["==", ["get", "id"], selectedId ?? "__none__"]],
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 1, 9, 8, 17],
          "circle-color": "rgba(53,224,208,0.14)",
          "circle-stroke-width": 1.4,
          "circle-stroke-color": "#35e0d0",
        },
      });

      setLayersReady(true);
      setReady(true);
    });

    map.on("moveend", () => {
      const b = map.getBounds();
      const bbox: [number, number, number, number] = [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()];
      const c = map.getCenter();
      onViewport(bbox, map.getZoom(), [c.lng, c.lat]);
    });
    map.on("load", () => {
      const b = map.getBounds();
      const c = map.getCenter();
      onViewport([b.getWest(), b.getSouth(), b.getEast(), b.getNorth()], map.getZoom(), [c.lng, c.lat]);
    });

    // hover state for countries
    let hoveredCountry: string | number | null = null;
    map.on("mousemove", "countries-fill", (e) => {
      if (!e.features?.length) return;
      if (hoveredCountry !== null) map.setFeatureState({ source: "countries", id: hoveredCountry }, { hover: false });
      hoveredCountry = e.features[0].id ?? null;
      if (hoveredCountry !== null) map.setFeatureState({ source: "countries", id: hoveredCountry }, { hover: true });
      const name = (e.features[0].properties as any)?.ADMIN || (e.features[0].properties as any)?.NAME;
      if (name) setHover(name);
    });
    map.on("mouseleave", "countries-fill", () => {
      if (hoveredCountry !== null) map.setFeatureState({ source: "countries", id: hoveredCountry }, { hover: false });
      setHover(null);
    });

    for (const layer of ["event-points", "event-clusters", "event-cluster-labels", "event-areas-fill", "aircraft-points", "aircraft-motion-layer", "vessel-points", "vessel-motion-layer", "sat-points", "sat-dots", "places",
              "camera-points", "camera-clusters", "air-points"]) {
      map.on("mouseenter", layer, () => (map.getCanvas().style.cursor = "pointer"));
      map.on("mouseleave", layer, () => (map.getCanvas().style.cursor = ""));
    }

    /* el contenedor cambia de tamaño al abrir/cerrar cajones, al girar el
       móvil o al plegarse la barra del navegador: el canvas debe reajustarse */
    let raf = 0;
    const nudge = () => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => map.resize());
    };
    const ro = new ResizeObserver(nudge);
    ro.observe(containerRef.current);
    window.addEventListener("orientationchange", nudge);
    window.visualViewport?.addEventListener("resize", nudge);

    mapRef.current = map;
    (window as any).__aegisMap = map;

  return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
      window.removeEventListener("orientationchange", nudge);
      window.visualViewport?.removeEventListener("resize", nudge);
      map.remove();
      mapRef.current = null;
      (window as any).__aegisMap = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /* --------------------------------------------------------- click routing */
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !layersReady) return;

    const onClick = (e: maplibregl.MapMouseEvent) => {
      if (aoiMode) {
        setPending({ lat: e.lngLat.lat, lon: e.lngLat.lng });
        return;
      }
      /* Prioridad de clic: un elemento concreto (avión, tren, cámara, barco,
         satélite) manda sobre un cúmulo de sucesos. Antes el cúmulo se comía
         el clic de un tren que estaba justo debajo. Se consulta una caja de
         4 px para exigir que se pulse el icono, no su entorno. */
      const caja: [[number, number], [number, number]] = [
        [e.point.x - 4, e.point.y - 4],
        [e.point.x + 4, e.point.y + 4],
      ];
      const puntoConcreto = (capas: string[]): any => {
        try {
          const f = map.queryRenderedFeatures(caja, { layers: capas });
          return f.length ? f[0] : null;
        } catch {
          return null;
        }
      };
      const aero = puntoConcreto(["aircraft-points", "aircraft-motion-layer"]);
      if (aero) { onActorSelect?.("aircraft", String((aero.properties as any).id)); return; }
      const tren = puntoConcreto(["train-points", "train-motion-layer"]);
      if (tren) { onActorSelect?.("trains", String((tren.properties as any).id)); return; }
      const camara = puntoConcreto(["camera-points"]);
      if (camara) { onCameraSelect?.(String((camara.properties as any).id)); return; }
      const satelite = puntoConcreto(["sat-points"]);
      if (satelite) {
        onSatelliteSelect?.(Number((satelite.properties as any).norad));
        onActorSelect?.("satellites", String((satelite.properties as any).norad));
        return;
      }
      const buque = puntoConcreto(["vessel-points", "vessel-motion-layer"]);
      if (buque) {
        onActorSelect?.("vessels", String((buque.properties as any).id ?? (buque.properties as any).mmsi));
        return;
      }

      // OJO: las teselas pintadas pueden ser de un barrido anterior del índice
      // (el mapa se repinta después de cada sondeo). Preguntamos al índice,
      // que es la única fuente de verdad, qué cúmulo hay EXACTAMENTE bajo el
      // cursor: así el desglose siempre coincide con el número pinchado.
      const index = eventIndex.current;
      let cid: number | null = null;
      let center: [number, number] | null = null;
      let clusterCount = 0;
      if (index) {
        // el centroide del cúmulo puede estar a unos metros del punto pulsado:
        // se consulta una ventana de ~1 píxel y se elige el cúmulo más cercano
        const z = Math.min(Math.floor(map.getZoom()), 13);
        const rad = 360 / (512 * Math.pow(2, z)) * 24;   // 24 px de margen
        const hits = index.getClusters(
          [e.lngLat.lng - rad, e.lngLat.lat - rad, e.lngLat.lng + rad, e.lngLat.lat + rad],
          z
        );
        const clusters = hits.filter((h: any) => h.properties?.cluster);
        let best: any = null;
        let bestD = Infinity;
        for (const h of clusters) {
          const c = (h.geometry as any).coordinates as [number, number];
          const d = (c[0] - e.lngLat.lng) ** 2 + (c[1] - e.lngLat.lat) ** 2;
          if (d < bestD) { bestD = d; best = h; }
        }
        if (best) {
          cid = best.properties.cluster_id;
          clusterCount = best.properties.point_count;
          center = (best.geometry as any).coordinates as [number, number];
        }
      }
      if (cid === null) {
        // respaldo: si el índice aún no está listo, se usa lo pintado
        const painted = map.queryRenderedFeatures(e.point, { layers: ["event-clusters"] });
        if (painted.length) {
          const f: any = painted[0];
          cid = f.properties.cluster_id;
          clusterCount = f.properties.point_count;
          center = (f.geometry as any).coordinates as [number, number];
        }
      }
      if (cid !== null && center) {
        const cidFinal = cid;
        const centerFinal = center;
        const zoom = index?.getClusterExpansionZoom(cidFinal) ?? map.getZoom() + 2;
        map.easeTo({ center: centerFinal, zoom: Math.min(zoom + 0.2, 13.5), duration: 520 });
        // El número del cúmulo se despliega en la lista de SUS elementos.
        if (onBreakdownCluster && index) {
          const leaves = index.getLeaves(cidFinal, clusterCount) as any[];
          const items = leaves.map(eventFeatureToItem).filter((i) => !!i.id);
          onBreakdownCluster(items, () =>
            map.easeTo({ center: centerFinal, zoom: Math.min(zoom + 1.6, 14), duration: 620 })
          );
        }
        return;
      }
      const areas = map.queryRenderedFeatures(e.point, { layers: ["event-areas-fill", "event-areas-line"] });
      if (areas.length) {
        const f = areas[0] as any;
        onSelect({
          type: "Feature",
          geometry: f.geometry,
          properties: hydrateProps(f.properties),
        } as EventFeature);
        return;
      }
      const points = map.queryRenderedFeatures(e.point, { layers: ["event-points"] });
      if (points.length) {
        const f = points[0] as any;
        onSelect({
          type: "Feature",
          geometry: f.geometry,
          properties: hydrateProps(f.properties),
        } as EventFeature);
        return;
      }
      // secondary layers -> popup
      const sat = map.queryRenderedFeatures(e.point, { layers: ["sat-points", "sat-dots"] });
      if (sat.length) {
        const p: any = sat[0].properties;
        onSatelliteSelect?.(Number(p.norad));
        onActorSelect?.("satellites", String(p.norad));
        return;
      }
      const ac = map.queryRenderedFeatures(e.point, { layers: ["aircraft-points", "aircraft-motion-layer"] });
      if (ac.length) {
        onActorSelect?.("aircraft", String((ac[0].properties as any).id));
        return;
      }
      // igual que con los eventos: manda el índice, no lo ya pintado
      const camIdx = camIndex.current;
      const camPainted = map.queryRenderedFeatures(e.point, { layers: ["camera-clusters"] });
      let camCid: number | null = null;
      let camCount = 0;
      let camCenter: [number, number] | null = null;
      if (camIdx) {
        const z = Math.min(Math.floor(map.getZoom()), 13);
        const rad = 360 / (512 * Math.pow(2, z)) * 24;
        const hits = camIdx.getClusters(
          [e.lngLat.lng - rad, e.lngLat.lat - rad, e.lngLat.lng + rad, e.lngLat.lat + rad],
          z
        );
        const clusters = hits.filter((h: any) => h.properties?.cluster);
        let best: any = null;
        let bestD = Infinity;
        for (const h of clusters) {
          const c = (h.geometry as any).coordinates as [number, number];
          const d = (c[0] - e.lngLat.lng) ** 2 + (c[1] - e.lngLat.lat) ** 2;
          if (d < bestD) { bestD = d; best = h; }
        }
        if (best) {
          camCid = best.properties.cluster_id;
          camCount = best.properties.point_count;
          camCenter = (best.geometry as any).coordinates as [number, number];
        }
      }
      if (camCid === null && camPainted.length) {
        const f: any = camPainted[0];
        camCid = f.properties.cluster_id;
        camCount = f.properties.point_count;
        camCenter = (f.geometry as any).coordinates as [number, number];
      }
      if (camCid !== null && camCenter && camIdx) {
        const cid = camCid;
        const center = camCenter;
        const zoom = camIdx.getClusterExpansionZoom(cid) ?? map.getZoom() + 2;
        map.easeTo({ center, zoom: Math.min(zoom + 0.2, 13), duration: 520 });
        if (onBreakdownCluster) {
          const leaves = camIdx.getLeaves(cid, camCount) as any[];
          const items = leaves.map((leaf: any) => ({
            id: String(leaf.properties?.id),
            title: String(leaf.properties?.name ?? leaf.properties?.id),
            sub: [leaf.properties?.network_label, leaf.properties?.kind, leaf.properties?.place]
              .filter(Boolean).join(" · "),
            color: "#b388ff",
            lat: leaf.geometry?.coordinates?.[1],
            lon: leaf.geometry?.coordinates?.[0],
          }));
          onBreakdownCluster(items, () =>
            map.easeTo({ center, zoom: Math.min(zoom + 1.6, 13.5), duration: 620 })
          );
        }
        return;
      }
      const camHit = map.queryRenderedFeatures(e.point, { layers: ["camera-points"] });
      if (camHit.length) {
        const props: any = camHit[0].properties;
        onCameraSelect?.(String(props.id));
        return;
      }
      const trainHit = map.queryRenderedFeatures(e.point, { layers: ["train-points", "train-motion-layer"] });
      if (trainHit.length) {
        const props = trainHit[0].properties || {};
        onActorSelect?.("trains", String(props.id));
        return;
      }

      const airHit = map.queryRenderedFeatures(e.point, { layers: ["air-points"] });
      if (airHit.length) {
        const props: any = airHit[0].properties;
        onActorSelect?.("air", String(props.id));
        return;
      }
      const vs = map.queryRenderedFeatures(e.point, { layers: ["vessel-points", "vessel-motion-layer"] });
      if (vs.length) {
        onActorSelect?.("vessels", String((vs[0].properties as any).id ?? (vs[0].properties as any).mmsi));
        return;
      }
      // núcleo urbano: la ficha del lugar hereda el nombre de la ciudad
      const town = map.queryRenderedFeatures(e.point, { layers: ["places"] });
      if (town.length) {
        const props: any = town[0].properties;
        onPlaceSelect?.({
          lat: e.lngLat.lat,
          lon: e.lngLat.lng,
          name: String(props.NAME ?? props.name ?? props.NAMEPAR ?? "") || undefined,
          zoom: map.getZoom(),
        });
        return;
      }
      // zona vacía: igualmente abre la ficha de lo que hay en ese punto
      onPlaceSelect?.({ lat: e.lngLat.lat, lon: e.lngLat.lng, zoom: map.getZoom() });
    };

    map.on("click", onClick);
    return () => {
      map.off("click", onClick);
    };
  }, [aoiMode, layersReady, onSelect, onSatelliteSelect, onActorSelect, onBreakdownCluster, onCameraSelect, onPlaceSelect]);

  /* ----------------------------------------------------- supercluster sync */
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !layersReady || !events) return;
    const index = new Supercluster({
      radius: 62,
      maxZoom: 13,
      minPoints: 2,
      extent: 512,
      map: (props: any) => ({
        category: props.category,
        severity_label: props.severity_label,
        sources_count: props.sources_count,
      }),
      reduce: (acc: any, props: any) => {
        acc.sources_count = Math.max(acc.sources_count || 0, props.sources_count || 0);
      },
    });
    // Supercluster solo indexa puntos; las áreas van a su propia capa
    const pointFeatures = (events.features as any[]).filter(
      (f) => (f.geometry?.type ?? "Point") === "Point"
    );
    const areaFeatures = (events.features as any[]).filter(
      (f) => (f.geometry?.type ?? "Point") !== "Point"
    );
    index.load(pointFeatures);
    const areaSource = map.getSource("event-areas") as any;
    if (areaSource) {
      areaSource.setData({ type: "FeatureCollection", features: areaFeatures });
    }
    eventIndex.current = index;
    renderEvents();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [events, layersReady]);

  function bboxOf(map: MlMap): [number, number, number, number] {
    const b = map.getBounds();
    return [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()];
  }

  function queryClusters(index: any, map: MlMap) {
    const zoom = Math.min(Math.floor(map.getZoom()), 13);
    const [w, s, e, n] = bboxOf(map);
    const south = Math.max(-85, s);
    const north = Math.min(85, n);
    const boxes: [number, number, number, number][] = [];
    if (e - w >= 360) {
      boxes.push([-180, south, 180, north]);
    } else {
      // split across the antimeridian when the viewport wraps
      if (w < -180) boxes.push([w + 360, south, 180, north]);
      if (e > 180) boxes.push([-180, south, e - 360, north]);
      boxes.push([Math.max(-180, w), south, Math.min(180, e), north]);
    }
    const seen = new Set<string>();
    const out: any[] = [];
    for (const box of boxes) {
      if (box[0] >= box[2]) continue;
      for (const f of index.getClusters(box, zoom)) {
        const c = f.geometry?.coordinates ?? [];
        const key = f.properties?.cluster ? `c${f.properties.cluster_id}` : `p${c[0]},${c[1]},${f.properties?.id}`;
        if (seen.has(key)) continue;
        seen.add(key);
        out.push(f);
      }
    }
    return out;
  }

  function renderEvents() {
    const map = mapRef.current;
    const index = eventIndex.current;
    if (!map || !index) return;
    const src = map.getSource("events") as any;
    if (!src) return;
    src.setData({ type: "FeatureCollection", features: queryClusters(index, map).filter((f: any) => !!f) });
  }

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !layersReady) return;
    const handler = () => {
      renderEvents();
      // las cámaras se re-clusterizan con el viewport (índice propio)
      const camSrc = map.getSource("cameras") as any;
      if (camSrc && camIndex.current) {
        camSrc.setData({ type: "FeatureCollection", features: queryClusters(camIndex.current, map) });
      }
    };
    map.on("moveend", handler);
    map.on("zoomend", handler);
    return () => {
      map.off("moveend", handler);
      map.off("zoomend", handler);
    };
  }, [layersReady]);

  /* --------------------------------------------------------- live layers */
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !layersReady) return;
    const src = map.getSource("aircraft") as any;
    if (!src) return;
    if (!aircraft) {
      src.setData(EMPTY_FC);
      return;
    }
    // Sin agrupar: TODOS los aviones se dibujan siempre (allow-overlap) y su
    // icono escala con el zoom. Antes se agrupaban y en el cúmulo «desaparecían»
    // decenas de aeronaves dentro de un solo icono.
    src.setData(aircraft as any);
  }, [aircraft, layersReady]);

  /* fondo de mapa: una capa ráster activa a la vez; al elegir teselas se
     ocultan los rellenos vectoriales propios para no taparlas */
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !layersReady) return;
    const raster = basemap && basemap !== "vectorial";
    // pares base + etiquetas + red de transporte: la red de carreteras y
    // ferrocarril acompaña SIEMPRE al fondo, sea cual sea el elegido
    const pair: Record<string, string[]> = {
      // elegido suelto: fondo mínimo + red viaria/ferroviaria y derrotas
      vectorial: ["transporte", "oceanoref"],
      transporte: ["transporte", "oceanoref"],
      calles: ["calles", "transporte"],
      oscuro: ["oscuro", "oscuro_ref", "transporte"],
      claro: ["claro", "claro_ref", "transporte"],
      satelite: ["satelite", "transporte"],
    };
    const active = pair[basemap ?? ""] ?? [];
    for (const id of ["calles", "oscuro", "claro", "satelite", "oscuro_ref", "claro_ref", "transporte", "oceanoref"]) {
      const layer = map.getLayer(`base-${id}-raster`);
      if (!layer) continue;
      map.setLayoutProperty(
        `base-${id}-raster`,
        "visibility",
        active.includes(id) ? "visible" : "none"
      );
    }
    // En el fondo vectorial propio las teselas se insertaron DEBAJO del relleno
    // de tierra (para que este las tape si están apagadas). Si se pide la red
    // de transporte, hay que subirla por encima del relleno para verla.
    if (map.getLayer("base-transporte-raster") && map.getLayer("countries-fill")) {
      try {
        if (!map.getLayoutProperty("base-transporte-raster", "visibility")) {
          // sin propiedad fijada aún: colocarla donde corresponde una vez
          map.moveLayer("base-transporte-raster", "coastline");
        }
      } catch { /* la capa aún no existe en este estilo */ }
    }
    // las capas superpuestas no tapan la base: opacidad según para qué son
    if (map.getLayer("base-transporte-raster")) {
      map.setPaintProperty(
        "base-transporte-raster",
        "raster-opacity",
        // el callejero ya trae la red: se refuerza poco; sobre grises y
        // ortofoto se pinta con más cuerpo para que se lea
        basemap === "calles" ? 0.55 : 0.85
      );
    }
    // derrotas marítimas de Esri: solo cuando el fondo es oscuro (su paleta
    // clara sobre el claro no se distingue y duplicaría nuestras sealanes)
    if (map.getLayer("base-oceanoref-raster")) {
      map.setLayoutProperty(
        "base-oceanoref-raster",
        "visibility",
        basemap === "oscuro" || basemap === "claro" || basemap === "transporte"
          ? "visible"
          : "none"
      );
      map.setPaintProperty("base-oceanoref-raster", "raster-opacity", 0.55);
    }
    const showVector = !raster;
    for (const id of ["land-fill", "countries-fill"]) {
      if (map.getLayer(id)) {
        map.setLayoutProperty(id, "visibility", showVector ? "visible" : "none");
      }
    }
    // con ortofoto o callejero, las fronteras quedan como línea fina
    if (map.getLayer("countries-line")) {
      map.setPaintProperty("countries-line", "line-opacity", raster ? 0.25 : 0.55);
    }
    if (map.getLayer("graticule")) {
      map.setPaintProperty("graticule", "line-opacity", raster ? 0.12 : 0.35);
    }
    if (map.getLayer("coastline")) {
      map.setPaintProperty("coastline", "line-opacity", raster ? 0.3 : 0.55);
    }
  }, [basemap, layersReady]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !layersReady) return;
    const src = map.getSource("trains") as any;
    if (!src) return;
    src.setData(visible.trains === false ? EMPTY_FC : trains ?? EMPTY_FC);
  }, [trains, visible.trains, layersReady]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !layersReady) return;
    const src = map.getSource("air") as any;
    if (!src) return;
    // una capa apagada no retiene 4.000 sensores en memoria
    src.setData(visible.air === false ? EMPTY_FC : air ?? EMPTY_FC);
  }, [air, visible.air, layersReady]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !layersReady) return;
    const src = map.getSource("cameras") as any;
    if (!src) return;
    if (!cameras || visible.cameras === false) {
      src.setData(EMPTY_FC);
      return;
    }
    if (!camIndex.current) {
      camIndex.current = new Supercluster({
        // maxZoom alto = cada cámara se separa de su cúmulo antes (a partir del
        // 13 se dibujan todas sueltas) y radio menor = menos agrupación espuria
        radius: 38, maxZoom: 9, minPoints: 2,
        map: (props: any) => ({ online: props.online, network: props.network }),
      });
    }
    // La firma evita reindexar 8 800 cámaras en cada sondeo de 20 s cuando el
    // catálogo no ha cambiado (antes se hacía siempre y costaba CPU y memoria).
    const firma = `${cameras.features.length}:${(cameras as any).updated_at ?? (cameras as any).stats?.updated_at ?? ""}`;
    const yaCargado = (camIndex.current as any).__firma === firma;
    if (!yaCargado) {
      camIndex.current.load(cameras.features as any);
      (camIndex.current as any).__firma = firma;
    }
    src.setData({ type: "FeatureCollection", features: queryClusters(camIndex.current, map) });
  }, [cameras, visible.cameras, layersReady]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !layersReady) return;
    const src = map.getSource("vessels") as any;
    if (!src) return;
    if (!vessels) {
      src.setData(EMPTY_FC);
      return;
    }
    src.setData(vessels as any);
  }, [vessels, layersReady]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !layersReady) return;
    const src = map.getSource("satellites") as any;
    if (!src) return;
    src.setData(satellites ?? EMPTY_FC);
  }, [satellites, layersReady]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !layersReady) return;
    const src = map.getSource("fences") as any;
    if (!src) return;
    src.setData(fences ?? EMPTY_FC);
  }, [fences, layersReady]);

  /* ---------------------------------------------------- layer visibility */
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !layersReady) return;
    const toggle = (id: string, on: boolean) => {
      if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", on ? "visible" : "none");
    };
    toggle("aircraft-points", visible.aircraft !== false);
    toggle("vessel-points", visible.vessels !== false);
    toggle("sat-points", visible.satellites !== false);
    toggle("sat-dots", visible.satellites !== false);
    toggle("train-points", visible.trains !== false);
    toggle("train-labels", visible.trains !== false);
    toggle("air-halo", visible.air !== false);
    toggle("air-points", visible.air !== false);
    toggle("camera-points", visible.cameras !== false);
    toggle("camera-clusters", visible.cameras !== false);
    toggle("camera-cluster-labels", visible.cameras !== false);
    toggle("orbit-line", visible.satellites !== false);
    toggle("event-clusters", visible.events !== false);
    toggle("event-cluster-labels", visible.events !== false);
    toggle("event-points", visible.events !== false);
    toggle("event-areas-fill", visible.events !== false);
    toggle("event-areas-line", visible.events !== false);
    toggle("event-halo", visible.events !== false);
    toggle("fence-fill", visible.fences !== false);
    toggle("fence-line", visible.fences !== false);
    toggle("places", visible.places !== false);
    toggle("graticule", visible.graticule !== false);
  }, [visible, layersReady]);

  /* ------------------------------------------------------------ selection */
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !layersReady) return;
    if (map.getLayer("event-halo")) {
      map.setFilter("event-halo", ["all", ["!", ["has", "point_count"]], ["==", ["get", "id"], selectedId ?? "__none__"]]);
    }
  }, [selectedId, layersReady, events]);

  /* ------------------------------------------------------------ aoi draft */
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !layersReady) return;
    const src = map.getSource("aoi") as any;
    if (!src) return;
    if (!pending) {
      src.setData(EMPTY_FC);
      return;
    }
    src.setData({
      type: "FeatureCollection",
      features: [{
        type: "Feature",
        properties: {},
        geometry: { type: "Polygon", coordinates: [circleRing(pending.lat, pending.lon, aoiRadiusKm)] },
      }],
    });
  }, [pending, aoiRadiusKm, layersReady]);

  useEffect(() => {
    if (!aoiMode) setPending(null);
  }, [aoiMode]);

  /* ------------------------------------------------------------- terrain */
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    if (terrain) {
      try {
        if (!map.getSource("dem")) {
          map.addSource("dem", {
            type: "raster-dem",
            tiles: ["https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"],
            encoding: "terrarium",
            tileSize: 256,
            maxzoom: 12,
          });
        }
        map.setTerrain({ source: "dem", exaggeration: 1.25 });
        if (!map.getLayer("hillshade")) {
          map.addLayer({
            id: "hillshade", type: "hillshade", source: "dem",
            paint: { "hillshade-exaggeration": 0.25, "hillshade-shadow-color": "#000000" },
          });
        }
      } catch (err) {
        console.warn("terrain unavailable", err);
      }
    } else {
      try {
        map.setTerrain(null as any);
      } catch {}
    }
  }, [terrain, ready]);

  // ---------------------------------------------------------------- animación
  // 1) trayectoria del elemento seleccionado, con guion animado
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !layersReady) return;
    const src = map.getSource("trail") as maplibregl.GeoJSONSource | undefined;
    if (!src) return;
    // MapLibre revienta al calcular el guion de una línea nula o de menos de
    // dos puntos distintos: se filtra antes de publicar la estela.
    const raw = track?.geometry?.coordinates ?? [];
    const coords: [number, number][] = [];
    for (const c of raw) {
      if (!Array.isArray(c) || !Number.isFinite(c[0]) || !Number.isFinite(c[1])) continue;
      const last = coords[coords.length - 1];
      if (last && Math.abs(last[0] - c[0]) < 1e-6 && Math.abs(last[1] - c[1]) < 1e-6) continue;
      coords.push([c[0], c[1]]);
    }
    if (coords.length < 2) {
      src.setData(EMPTY_FC as any);
      return;
    }
    src.setData({
      type: "Feature",
      properties: { kind: selectedActor?.kind || "aircraft" },
      geometry: { type: "LineString", coordinates: coords },
    } as any);

    // un punto luminoso recorre la estela: sensación de movimiento sin tocar
    // el guion (MapLibre falla al recalcularlo en líneas degeneradas)
    const headSrc = map.getSource("trail-head") as maplibregl.GeoJSONSource | undefined;
    const legs: number[] = [];
    let total = 0;
    for (let i = 1; i < coords.length; i++) {
      const d = Math.abs(coords[i][0] - coords[i - 1][0]) + Math.abs(coords[i][1] - coords[i - 1][1]);
      legs.push(d);
      total += d;
    }
    let raf = 0;
    const t0 = performance.now();
    const tick = () => {
      if (headSrc && total > 0) {
        const phase = ((performance.now() - t0) / 2600) % 1;      // 2,6 s por recorrido
        let target = phase * total;
        let i = 0;
        while (i < legs.length - 1 && target > legs[i]) { target -= legs[i]; i++; }
        const a = coords[i] ?? coords[0];
        const b = coords[i + 1] ?? a;
        const k = legs[i] ? Math.min(1, target / legs[i]) : 0;
        try {
          headSrc.setData({
            type: "Feature", properties: {},
            geometry: { type: "Point", coordinates: [a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k] },
          } as any);
        } catch {}
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => { cancelAnimationFrame(raf); try { headSrc?.setData(EMPTY_FC as any); } catch {} };
  }, [track, layersReady, selectedActor?.kind]);

  const collectionFor = (kind?: string | null) =>
    kind === "aircraft" ? aircraft
      : kind === "vessels" ? vessels
        : kind === "trains" ? trains
          : kind === "air" ? air
            : satellites;

  // 2) halo pulsante sobre el elemento seleccionado
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !layersReady) return;
    const src = map.getSource("selection") as maplibregl.GeoJSONSource | undefined;
    if (!src) return;
    const col: any = collectionFor(selectedActor?.kind);
    const hit = (col?.features || []).find((x: any) =>
      String(x.properties?.id ?? x.properties?.mmsi ?? x.properties?.norad) === String(selectedActor?.id)
    );
    if (hit?.geometry?.type === "Point") selectionPos.current = hit.geometry.coordinates as [number, number];
    const c = selectionPos.current;
    if (!selectedActor || !c) {
      src.setData(EMPTY_FC as any);
      return;
    }
    src.setData({
      type: "Feature", properties: {},
      geometry: { type: "Point", coordinates: c },
    } as any);
    let raf = 0;
    const t0 = performance.now();
    const tick = () => {
      const t = (performance.now() - t0) / 1000;
      const k = (Math.sin(t * 2.2) + 1) / 2;
      try {
        map.setPaintProperty("selection-halo", "circle-radius", 14 + k * 12);
        map.setPaintProperty("selection-halo", "circle-opacity", 0.85 - k * 0.45);
        map.setPaintProperty("selection-halo", "circle-blur", 0.2 + k * 0.4);
      } catch {}
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [selectedActor, layersReady, selectedActor?.id, aircraft, vessels, satellites, trains, air]);

  // 3) cámara de seguimiento (se suelta en cuanto el usuario mueve el mapa)
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !follow) return;
    const release = (e: any) => { if (e?.originalEvent) onBreakFollow?.(); };
    map.on("dragstart", release);
    map.on("zoomstart", release);
    const id = setInterval(() => {
      const c = selectionPos.current;
      if (c) map.easeTo({ center: c, duration: 1400, essential: true });
    }, 2200);
    return () => {
      clearInterval(id);
      map.off("dragstart", release);
      map.off("zoomstart", release);
    };
  }, [follow, onBreakFollow]);

  // 4) interpolación continua de posiciones entre sondeos
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !layersReady) return;
    const kinds: { key: "aircraft" | "vessels" | "satellites" | "trains"; src: string; dur: number; minZoom: number; get: (f: any) => [number, number] | null }[] = [
      { key: "aircraft", src: "aircraft-motion", dur: 8000, minZoom: 5, get: (f) => (f.geometry?.type === "Point" ? f.geometry.coordinates : null) },
      { key: "vessels", src: "vessel-motion", dur: 30000, minZoom: 4, get: (f) => (f.geometry?.type === "Point" ? f.geometry.coordinates : null) },
      { key: "trains", src: "train-motion", dur: 20000, minZoom: 4, get: (f) => (f.geometry?.type === "Point" ? f.geometry.coordinates : null) },
      { key: "satellites", src: "satellites", dur: 5000, minZoom: 0, get: (f) => (f.geometry?.type === "Point" ? f.geometry.coordinates : null) },
    ];
    let raf = 0;
    const targets = targetsRef.current;

    const lastData = (window as any).__aegisLastData || {};
    (window as any).__aegisLastData = lastData;

    /* Firma del contenido, no de la referencia: el sondeo puede devolver el
       mismo estado y no por ello debe reiniciarse la interpolación. */
    const contentSig = (feats: any[], get: (f: any) => [number, number] | null) => {
      let h = feats.length;
      for (let i = 0; i < feats.length; i += Math.max(1, Math.floor(feats.length / 60))) {
        const f = feats[i];
        const c = get(f);
        if (!c) continue;
        h = (h * 31 + Math.round(c[0] * 1e4) + Math.round(c[1] * 1e4)) % 2147483647;
      }
      return String(h);
    };

    const prepare = (force = false) => {
      for (const k of kinds) {
        const data: any =
          k.key === "aircraft" ? aircraft
          : k.key === "vessels" ? vessels
          : k.key === "trains" ? trains
          : satellites;
        const feats: any[] = data?.features || [];
        const cs = k.key + ":" + contentSig(feats, k.get);
        // los sondeos de otras capas (o repetidos) no reinician la interpolación
        if (!force && lastData[k.key] === cs) continue;
        lastData[k.key] = cs;
        const src = map.getSource(k.src) as maplibregl.GeoJSONSource | undefined;
        if (!src) continue;
        const prev = prevPos.current[k.key] || new Map();
        const next = new Map<string, [number, number]>();
        for (let i = 0; i < feats.length; i++) {
          const f = feats[i];
          const c = k.get(f);
          const id = String(f.properties?.id ?? f.properties?.mmsi ?? f.properties?.norad ?? i);
          if (c) next.set(id, c);
        }
        prevPos.current[k.key] = next;
        targets[k.key] = { feats, from: prev, t0: performance.now(), dur: k.dur };
      }
    };
    prepare();
    const g = ((window as any).__aegisAnim ||= { frames: 0, prepares: 0, writes: 0, lastPrepare: 0, kinds: [] });
    g.prepares += 1; g.lastPrepare = performance.now(); g.kinds = Object.keys(targets);

    const blank: Record<string, boolean> = {};
    const sig: Record<string, number> = {};
    const lastWrite: Record<string, number> = {};
    /* La fuente se reescribe solo cuando el desplazamiento ya es visible: a poca
       ampliación un satélite avanza centésimas de píxel por segundo, así que
       volcar miles de posiciones cada fotograma solo llena la cola del worker
       (y con ella la memoria del navegador) sin cambiar nada en pantalla. */
    // Cada escritura re-tesela la fuente entera: se hace menos a menudo de lo
    // que se pinta (el ojo no distingue 0,4 s de deriva en un avión de 40 px).
    const writeInterval = (z: number) => (z < 6 ? 1200 : z < 8 ? 800 : 500);
    // el tren avanza metros por segundo: una escritura por segundo sobra para
    // que la sensación de movimiento sea continua (su deriva es de 20 s)
    const writeIntervalFor = (key: string, z: number) =>
      key === "trains" ? Math.max(1000, writeInterval(z)) : writeInterval(z);

    const tick = () => {
      const now = performance.now();
      const zoom = map.getZoom();
      const b = map.getBounds();
      const w = b.getWest() - 2, e0 = b.getEast() + 2, so = b.getSouth() - 2, no = b.getNorth() + 2;
      const g2 = (window as any).__aegisAnim;
      if (g2) g2.frames++;
      if (typeof document !== "undefined" && document.hidden) {
        raf = requestAnimationFrame(tick);
        return;
      }
      // vista planetaria: el movimiento es subpíxel y solo consume fotogramas
      if (zoom < 3.2) {
        for (const k of kinds) {
          const src0 = map.getSource(k.src) as maplibregl.GeoJSONSource | undefined;
          if (src0 && !blank[k.key]) { blank[k.key] = true; try { src0.setData(EMPTY_FC as any); } catch {} }
        }
        raf = requestAnimationFrame(tick);
        return;
      }
      for (const k of kinds) {
        const t: any = targets[k.key];
        const src = map.getSource(k.src) as maplibregl.GeoJSONSource | undefined;
        if (!t || !src) continue;
        // a poca ampliación el movimiento es subpíxel: se deja el dato en reposo
        if (zoom < k.minZoom) {
          if (!blank[k.key]) {
            blank[k.key] = true;
            try { src.setData(EMPTY_FC as any); } catch {}
          }
          continue;
        }
        blank[k.key] = false;
        if (now - (lastWrite[k.key] ?? 0) < writeIntervalFor(k.key, zoom)) continue;
        const at = Math.min(1, (now - t.t0) / t.dur);
        const ez = at < 0.5 ? 2 * at * at : 1 - Math.pow(-2 * at + 2, 2) / 2; // smoothstep
        // objetos reutilizados: cero reservas por fotograma (solo se mueven coords)
        const wrappers: any[] = t.wrap || (t.wrap = t.feats.map((f: any) => ({
          type: "Feature", properties: f.properties,
          geometry: { type: "Point", coordinates: [0, 0] },
        })));
        // tope conservador: reencuadrar el mundo entero con miles de iconos
        // en un solo fotograma es lo que dejaba la pestaña sin memoria
        const cap = zoom < k.minZoom + 1.5 ? 400 : zoom < k.minZoom + 3 ? 1200 : Infinity;
        // escala de píxeles: 512·2^zoom px cubren los 360° de longitud
        const degPerPx = 360 / (512 * Math.pow(2, zoom));
        const buf: [number, number, number][] = (t.buf ||= []);
        let n = 0, maxPx = 0;
        for (let i = 0; i < t.feats.length; i++) {
          const f = t.feats[i];
          const c = k.get(f);
          if (!c) continue;
          // solo lo visible: mantener el fotograma barato con miles de actores
          if (c[0] < w || c[0] > e0 || c[1] < so || c[1] > no) continue;
          let px = c[0], py = c[1];
          if (ez < 1) {
            const id = String(f.properties?.id ?? f.properties?.mmsi ?? f.properties?.norad ?? "");
            const p = t.from.get(id);
            if (p) {
              const dLon = ((c[0] - p[0] + 540) % 360) - 180;
              px = p[0] + dLon * ez;
              py = p[1] + (c[1] - p[1]) * ez;
            }
          } else {
            // sin sondeo nuevo todavía: el icono sigue avanzando con su rumbo
            // y velocidad reales (navegación a estima) en vez de congelarse.
            // La velocidad se cachea en el actor: recalcularla cada fotograma
            // para miles de elementos bloqueaba el hilo principal al ampliar.
            let v = (f.properties as any).__drift;
            if (v === undefined) {
              v = driftVelocity(f);
              try { (f.properties as any).__drift = v; } catch { /* congelado */ }
            }
            if (v) {
              const extra = Math.min(90, Math.max(0, (now - t.t0 - t.dur) / 1000));
              if (extra > 0) { px = c[0] + v[0] * extra; py = c[1] + v[1] * extra; }
            }
          }
          const slot = buf[n] || (buf[n] = [0, 0, 0]);
          slot[0] = i; slot[1] = px; slot[2] = py;
          n++;
          // desplazamiento respecto a lo ya publicado, en píxeles
          const g = wrappers[i].geometry.coordinates;
          const dpx = Math.abs(px - g[0]) / degPerPx;
          const dpy = Math.abs(py - g[1]) / degPerPx;
          const d = dpx > dpy ? dpx : dpy;
          if (d > maxPx) maxPx = d;
          if (n >= cap) break;
        }
        if (g2) (g2.byKind ||= {})[k.key] = {
          out: n, feats: t.feats.length, at: +at.toFixed(2), ez: +ez.toFixed(2),
          px: +maxPx.toFixed(2),
          extra: +((now - t.t0 - t.dur) / 1000).toFixed(1),
        };
        if (!n) continue;                     // nunca vaciar una capa con datos
        // por debajo de medio píxel el movimiento no se ve: no se vuelca nada
        if (maxPx < 0.5) continue;
        // array nuevo por volcado: MapLibre puede retener la referencia
        const visible: any[] = [];
        let hash = 17 + n;
        for (let j = 0; j < n; j++) {
          const slot = buf[j];
          const g = wrappers[slot[0]].geometry.coordinates;
          g[0] = slot[1]; g[1] = slot[2];
          visible.push(wrappers[slot[0]]);
          hash = (hash * 31 + Math.round(slot[1] * 1e5) + Math.round(slot[2] * 1e5)) % 2147483647;
        }
        if (hash === sig[k.key]) continue;     // la vista ya está quieta
        sig[k.key] = hash;
        lastWrite[k.key] = now;
        if (g2) g2.writes++;
        try {
          src.setData({ type: "FeatureCollection", features: visible } as any);
        } catch {}
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [aircraft, vessels, satellites, trains, layersReady]);

  /* ------------------------------------------------- vías (carga por ventana)
     El ferrocarril mundial son 25 000 líneas: si se envían todas, el motor del
     mapa tiene que teselarlas y se queda sin memoria. El servidor devuelve solo
     las que caen en la vista (y a escala continental, solo las troncales). */
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !layersReady) return;
    let ultima = "";
    let abort: AbortController | null = null;
    const cargar = () => {
      // a escala mundial las redes no se leen (los trazos se funden) y teselar
      // 45 000 puntos cuesta fotogramas: se cargan al acercarse a una región
      if (map.getZoom() < 6) {
        const r = map.getSource("roads") as maplibregl.GeoJSONSource | undefined;
        const v = map.getSource("railways") as maplibregl.GeoJSONSource | undefined;
        r?.setData({ type: "FeatureCollection", features: [] } as any);
        v?.setData({ type: "FeatureCollection", features: [] } as any);
        ultima = "";
        return;
      }
      const b = map.getBounds();
      const w = Math.max(-180, b.getWest() - 2), e = Math.min(180, b.getEast() + 2);
      const s0 = Math.max(-85, b.getSouth() - 2), n = Math.min(85, b.getNorth() + 2);
      const key = [w.toFixed(1), s0.toFixed(1), e.toFixed(1), n.toFixed(1), Math.floor(map.getZoom())].join(",");
      if (key === ultima) return;
      ultima = key;
      abort?.abort();
      abort = new AbortController();
      // a escala continental solo las troncales: el resto no se distingue y
      // multiplica el teselado en el hilo principal del navegador
      const major = map.getZoom() < 4.5 ? 1 : 0;
      const incluir = "roads,rail";
      fetch(
        `/api/basemap/infra_view?bbox=${w.toFixed(2)},${s0.toFixed(2)},${e.toFixed(2)},${n.toFixed(2)}` +
          `&major=${major}&include=${incluir}`,
        { signal: abort.signal },
      )
        .then((r) => (r.ok ? r.json() : null))
        .then((data) => {
          if (!data) return;
          const rail = map.getSource("railways") as maplibregl.GeoJSONSource | undefined;
          const roads = map.getSource("roads") as maplibregl.GeoJSONSource | undefined;
          const parts = data.parts || {};
          if (incluir.includes("roads") && roads && parts.roads) roads.setData(parts.roads);
          if (rail && parts.rail) rail.setData(parts.rail);
        })
        .catch(() => {});
    };
    // derrotas marítimas: conjunto pequeño, se pide una sola vez
    const src = map.getSource("sealanes") as maplibregl.GeoJSONSource | undefined;
    if (src) {
      fetch(apiUrl("/api/basemap/sealanes")).then((r) => (r.ok ? r.json() : null)).then((d) => d && src.setData(d)).catch(() => {});
    }
    cargar();
    map.on("moveend", cargar);
    return () => {
      abort?.abort();
      map.off("moveend", cargar);
    };
  }, [layersReady]);

  // posición viva del elemento seleccionado (para el halo y la cámara)
  useEffect(() => {
    if (!selectedActor) return;
    const col: any = collectionFor(selectedActor.kind);
    const f = (col?.features || []).find((x: any) =>
      String(x.properties?.id ?? x.properties?.mmsi ?? x.properties?.norad) === String(selectedActor.id)
    );
    if (f?.geometry?.type === "Point") selectionPos.current = f.geometry.coordinates as [number, number];
  }, [selectedActor, aircraft, vessels, satellites, trains, air]);

  return (
    <div className="map-wrap">
      <div ref={containerRef} className="map-canvas" />

      {hover && (
        <div className="map-overlay" style={{ top: 12, left: 12, pointerEvents: "none", letterSpacing: "0.06em" }}>
          <span className="mono tiny faint">{hover.toUpperCase()}</span>
        </div>
      )}

      {aoiMode && (
        <div className="map-hint">
          {pending
            ? `Centro fijado en ${pending.lat.toFixed(3)}, ${pending.lon.toFixed(3)} · radio ${aoiRadiusKm} km — pulsa CREAR ZONA`
            : "Haz clic en el mapa para fijar el centro del área de vigilancia"}
        </div>
      )}

      {pending && aoiMode && (
        <div className="map-overlay" style={{ bottom: 42, left: "50%", transform: "translateX(-50%)", display: "flex", gap: 8 }}>
          <button className="btn primary" onClick={() => { onCreateAoi(pending.lat, pending.lon, aoiRadiusKm); setPending(null); }}>
            Crear zona
          </button>
          <button className="btn ghost" onClick={() => setPending(null)}>Cancelar</button>
        </div>
      )}

      {glError && (
        <div className="map-gl-error">
          <div>
            <strong>Este navegador no puede iniciar WebGL.</strong>
            <div className="tiny faint" style={{ marginTop: 4 }}>
              El globo 3D necesita aceleración gráfica. Prueba con otro navegador,
              activa la aceleración por hardware, o abre el <em>snapshot</em> estático.
            </div>
            <div className="mono tiny" style={{ marginTop: 6, opacity: 0.7 }}>{glError}</div>
          </div>
        </div>
      )}

      <div className="map-legend" title="Color de cada tipo de suceso. El tamaño del punto crece con la magnitud.">
        <div className="ml-title">Tipo de suceso</div>
        {Object.entries(CAT_COLORS).map(([cat, color]) => (
          <div className="legend-row" key={cat}>
            <span className="legend-dot" style={{ background: color, color }} />
            <span>{categoryMeta(cat).label}</span>
          </div>
        ))}
        <div className="ml-title" style={{ marginTop: 6 }}>Otros elementos</div>
        <div className="legend-row">
          <span className="legend-dot" style={{ background: "#a5e8ff", color: "#a5e8ff" }} />
          <span>Aeronave</span>
        </div>
        <div className="legend-row">
          <span className="legend-dot" style={{ background: "#57d9c3", color: "#57d9c3" }} />
          <span>Buque</span>
        </div>
        <div className="legend-row">
          <span className="legend-dot" style={{ background: "#b388ff", color: "#b388ff" }} />
          <span>Cámara</span>
        </div>
        <div className="legend-row">
          <span className="legend-dot" style={{ background: "#ffb454", color: "#ffb454" }} />
          <span>Tren (Renfe y Amtrak)</span>
        </div>
        <div className="legend-row">
          <span className="legend-dot" style={{ background: "#ffcf8b", color: "#ffcf8b", borderRadius: 1, height: 2 }} />
          <span>Vía ferroviaria</span>
        </div>
        <div className="legend-row">
          <span className="legend-dot" style={{ background: "#3aa6ff", color: "#3aa6ff", borderRadius: 1, height: 2 }} />
          <span>Derrota marítima (AIS)</span>
        </div>
        <div className="legend-row">
          <span className="legend-dot" style={{ background: "#9fc4d8", color: "#9fc4d8" }} />
          <span>Ciudad (pulsable)</span>
        </div>
      </div>
    </div>
  );
}
