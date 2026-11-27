import type { Alert } from "./types";

/**
 * Clave estable de un aviso. El mismo aviso puede llegar por el WebSocket y
 * por el long-polling, y además estar ya guardado en el histórico: se usa una
 * huella con los campos que identifican la entrada para no duplicarla.
 */
export function alertKey(a: Partial<Alert> | null | undefined): string {
  if (!a) return "";
  return [
    a.ts ?? "",
    a.fence_id ?? "",
    a.actor_id ?? "",
    a.actor_type ?? "",
    a.event_type ?? "",
    a.title ?? "",
  ].join("|");
}

function stamp(a: Alert): number {
  const t = Date.parse(String(a.ts ?? ""));
  return Number.isFinite(t) ? t : 0;
}

/**
 * Fusiona histórico y avisos en vivo conservando ambos. Lo nuevo va delante;
 * los repetidos se sustituyen por la versión más reciente del mismo aviso.
 */
export function mergeAlerts(current: Alert[], incoming: Alert[]): Alert[] {
  const byKey = new Map<string, Alert>();
  for (const alert of current) {
    const key = alertKey(alert);
    if (key) byKey.set(key, alert);
  }
  for (const alert of incoming) {
    const key = alertKey(alert);
    if (key) byKey.set(key, alert);
  }
  return [...byKey.values()]
    .sort((a, b) => stamp(b) - stamp(a))
    .slice(0, 250);
}
