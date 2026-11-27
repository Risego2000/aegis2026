/** Geolocalización del navegador con un único camino y avisos claros.
 *
 *  La ubicación se pide solo al pulsar, nunca al cargar, y no sale del
 *  navegador: el servidor no la recibe. El resultado se publica como evento
 *  global (`aegis:me`) para que la ficha de Lugar y el mapa hagan lo suyo.
 */

const GEO_ERROR_EVENT = "aegis:geo-error";

/** Distancia ortodrómica en kilómetros (haversine). */
export function distanceKm(lat1: number, lon1: number, lat2: number, lon2: number): number {
  const rad = (v: number) => (v * Math.PI) / 180;
  const dLat = rad(lat2 - lat1);
  const dLon = rad(lon2 - lon1);
  const a = Math.sin(dLat / 2) ** 2
    + Math.cos(rad(lat1)) * Math.cos(rad(lat2)) * Math.sin(dLon / 2) ** 2;
  return 2 * 6371 * Math.asin(Math.min(1, Math.sqrt(a)));
}

function emitError(message: string) {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent(GEO_ERROR_EVENT, { detail: { message } }));
}

function messageFor(err: GeolocationPositionError): string {
  if (err.code === err.PERMISSION_DENIED) {
    return "El navegador bloqueó el acceso a tu ubicación. Permítelo en el candado de la barra de direcciones y vuelve a intentarlo.";
  }
  if (err.code === err.POSITION_UNAVAILABLE) {
    return "No hay una ubicación disponible ahora mismo (sin GPS ni referencia de red).";
  }
  return "La ubicación tardó demasiado en responder. Vuelve a intentarlo.";
}

export function locateMe(
  onFound?: (lat: number, lon: number) => void,
  onError?: () => void,
): void {
  if (typeof navigator === "undefined" || !navigator.geolocation) {
    emitError("Este navegador no ofrece geolocalización.");
    onError?.();
    return;
  }
  navigator.geolocation.getCurrentPosition(
    (pos) => {
      const { latitude, longitude } = pos.coords;
      window.dispatchEvent(new CustomEvent("aegis:me", { detail: { lat: latitude, lon: longitude } }));
      onFound?.(latitude, longitude);
    },
    (err) => {
      emitError(messageFor(err));
      onError?.();
    },
    { enableHighAccuracy: true, timeout: 12000, maximumAge: 30000 },
  );
}
