import type { ReactNode } from "react";

/** Pictogramas propios de AEGIS: retícula de 24 px, trazo de 1,75 px y extremos redondos. */
const SHAPES = {
  aegis: <><path d="M12 2 20 6v6c0 5-3.4 8.2-8 10-4.6-1.8-8-5-8-10V6z"/><path d="M12 5v13M6.5 12h11M8.3 8.3l7.4 7.4M15.7 8.3l-7.4 7.4"/></>,
  search: <><circle cx="10.8" cy="10.8" r="6.3"/><path d="m15.5 15.5 5 5"/></>,
  close: <path d="M5 5 19 19M19 5 5 19"/>,
  locate: <><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.2"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3"/></>,
  target: <><circle cx="12" cy="12" r="8.5"/><circle cx="12" cy="12" r="4.5"/><path d="M12 1v4M12 19v4M1 12h4M19 12h4"/></>,
  pin: <><path d="M19 10c0 5-7 12-7 12S5 15 5 10a7 7 0 1 1 14 0Z"/><circle cx="12" cy="10" r="2.4"/></>,
  layers: <><path d="m12 3 9 5-9 5-9-5zM3 12l9 5 9-5M3 16l9 5 9-5"/></>,
  panel: <><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16M13 9h5M13 13h5"/></>,
  menu: <path d="M4 6h16M4 12h16M4 18h16"/>,
  help: <><circle cx="12" cy="12" r="9"/><path d="M9.5 9a2.7 2.7 0 0 1 5.3.7c0 2-2.8 2.5-2.8 4.3M12 17.5h.01"/></>,
  share: <><path d="M12 15V3m0 0-4 4m4-4 4 4"/><path d="M5 13v6a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-6"/></>,
  external: <><path d="M13 4h7v7M20 4l-9 9"/><path d="M19 14v5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h5"/></>,
  plus: <path d="M12 4v16M4 12h16"/>,
  bell: <><path d="M18 8a6 6 0 0 0-12 0c0 7-3 8-3 9h18c0-1-3-2-3-9ZM10 21h4"/></>,
  bellOff: <><path d="M4 4 20 20M8 5.4A6 6 0 0 1 18 8c0 3.4.7 5.5 1.6 7M6 9c0 5-3 7-3 8h14M10 21h4"/></>,
  warning: <><path d="m12 3 10 18H2z"/><path d="M12 9v5M12 17.5h.01"/></>,
  event: <><path d="m12 2 9 10-9 10L3 12z"/><circle cx="12" cy="12" r="2"/></>,
  camera: <><rect x="3" y="6" width="14" height="12" rx="2"/><circle cx="10" cy="12" r="3"/><path d="m17 10 4-2v8l-4-2"/></>,
  report: <><path d="M6 2h9l4 4v16H6zM15 2v5h4M9 11h7M9 15h7M9 19h5"/></>,
  sources: <><circle cx="5" cy="6" r="2"/><circle cx="19" cy="6" r="2"/><circle cx="12" cy="19" r="2"/><path d="m7 7 4 10M17 7l-4 10M7 6h10"/></>,
  analyst: <><path d="M3 20V4M3 20h18M6 16l4-5 4 2 5-7"/><circle cx="19" cy="6" r="1"/></>,
  plane: <><path d="m12 2 2 8 7 4v2l-7-2v5l2 2v1l-4-1-4 1v-1l2-2v-5l-7 2v-2l7-4z"/></>,
  ship: <><path d="M3 14h18l-3 6H6zM8 14V7h8v7M10 7V4h4v3M3 22c2-1 4-1 6 0 2-1 4-1 6 0 2-1 4-1 6 0"/></>,
  satellite: <><rect x="9" y="9" width="6" height="6" rx="1"/><path d="m9 10-5-3-3 5 5 3 3-5Zm6 4 5 3 3-5-5-3-3 5ZM12 9V5m-2-2 2 2 2-2"/></>,
  train: <><rect x="5" y="3" width="14" height="16" rx="4"/><path d="M5 11h14M8 7h3M13 7h3M8 19l-2 3M16 19l2 3"/><circle cx="9" cy="15" r=".7"/><circle cx="15" cy="15" r=".7"/></>,
  air: <><path d="M3 8h11a3 3 0 1 0-3-3M2 12h17a2.5 2.5 0 1 1-2.5 2.5M4 16h7a3 3 0 1 1-3 3"/></>,
  city: <><path d="M3 21V9h7v12M10 21V4h7v17M17 21v-9h4v9M6 12h1M6 16h1M13 8h1M13 12h1M13 16h1"/></>,
  grid: <><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c-5 5-5 13 0 18M12 3c5 5 5 13 0 18"/></>,
  map: <><path d="M9 4 3 6v15l6-2 6 2 6-2V4l-6 2-6-2Z"/><path d="M9 4v15M15 6v15"/></>,
  sun: <><circle cx="12" cy="12" r="4"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9 7 7M17 17l2.1 2.1M19.1 4.9 17 7M7 17l-2.1 2.1"/></>,
  terrain: <><path d="m2 20 7-12 4 6 3-4 6 10zM9 8l2 3M16 10l2 3"/></>,
  download: <><path d="M12 3v13m0 0-5-5m5 5 5-5M4 18v3h16v-3"/></>,
  check: <path d="m4 12 5 5L20 6"/>,
  copy: <><rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h3"/></>,
  refresh: <><path d="M20 11a8 8 0 0 0-14-5L4 8M4 4v4h4M4 13a8 8 0 0 0 14 5l2-2m0 4v-4h-4"/></>,
  follow: <><circle cx="12" cy="12" r="7"/><circle cx="12" cy="12" r="2"/><path d="M12 1v4M12 19v4M1 12h4M19 12h4"/></>,
  earthquake: <><circle cx="12" cy="12" r="2"/><path d="M12 3v4M12 17v4M3 12h4M17 12h4M5.6 5.6l2.8 2.8m7.2 7.2 2.8 2.8M18.4 5.6l-2.8 2.8m-7.2 7.2-2.8 2.8"/></>,
  disaster: <><path d="M12 3c6 0 9 4 9 9s-4 9-9 9-9-4-9-9 4-9 9-9Z"/><path d="M6 11c3-5 7-3 8 0 1 4-4 6-6 2M18 13c-3 5-7 3-8 0-1-4 4-6 6-2"/></>,
  wildfire: <path d="M12 2c1 4 6 5 6 11a6 6 0 0 1-12 0c0-3 2-5 3-7 .5 2 1 3 2 4 1-2 1-5 1-8ZM12 12c-1 2-2 3-2 5a2 2 0 0 0 4 0c0-2-1-3-2-5Z"/>,
  conflict: <><path d="m5 5 14 14M19 5 5 19M7 3l4 4M17 3l-4 4M3 17l4-4M21 17l-4-4"/></>,
  protest: <><path d="M4 4h16v7H4zM12 11v10M6 20h12M6 15h.01M18 15h.01"/></>,
  military: <><path d="m12 2 3 6 7 1-5 5 1 7-6-3-6 3 1-7-5-5 7-1z"/></>,
  diplomacy: <><path d="M5 21V3h11l-2 4 2 4H5M19 21V5M16 5h5"/></>,
  economy: <><path d="M4 20V12h4v8M10 20V8h4v12M16 20V4h4v16M3 20h18"/></>,
  news: <><rect x="3" y="4" width="18" height="16" rx="1"/><path d="M7 8h5M7 12h5M7 16h10M15 8h3v4h-3z"/></>,
  health: <path d="M9 3h6v6h6v6h-6v6H9v-6H3V9h6z"/>,
  weather: <><path d="M4 16a4 4 0 0 1 1-8 6 6 0 0 1 12-1 4.5 4.5 0 1 1 1 9zM8 19l-1 3M13 19l-1 3M18 19l-1 3"/></>,
  flood: <><path d="M12 3c-3 4-6 7-6 11a6 6 0 0 0 12 0c0-4-3-7-6-11ZM3 19c2-1 4-1 6 0 2-1 4-1 6 0 2-1 4-1 6 0"/></>,
  volcano: <><path d="m3 21 6-11 3 3 3-3 6 11zM10 6l2-4 2 4M7 3l-1 2M17 3l1 2"/></>,
  cyber: <><rect x="4" y="7" width="16" height="12" rx="2"/><path d="M9 7V5a3 3 0 0 1 6 0v2M8 12l2 2-2 2M12 16h4"/></>,
  traffic: <><path d="m12 3 8 18H4zM9 10h6M7 16h10M4 21h16"/></>,
  transport: <><rect x="5" y="3" width="14" height="16" rx="3"/><path d="M5 11h14M9 19l-2 3M15 19l2 3M9 15h.01M15 15h.01"/></>,
  network: <><circle cx="5" cy="6" r="2"/><circle cx="19" cy="6" r="2"/><circle cx="5" cy="18" r="2"/><circle cx="19" cy="18" r="2"/><path d="M7 6h10M5 8v8M19 8v8M7 18h10M7 8l10 8"/></>,
} satisfies Record<string, ReactNode>;

export type IconName = keyof typeof SHAPES;

export function Icon({ name, size = 18, className, strokeWidth = 1.75 }: {
  name: IconName; size?: number; className?: string; strokeWidth?: number;
}) {
  return <svg aria-hidden="true" focusable="false" className={`aegis-icon ${className ?? ""}`}
    width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">
    {SHAPES[name]}
  </svg>;
}
