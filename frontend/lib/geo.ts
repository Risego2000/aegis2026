/** Geolocalización del navegador con un único camino y avisos claros.
 *
 *  La ubicación se pide solo al pulsar, nunca al cargar, y no sale del
 *  navegador: el servidor no la recibe. El resultado se publica como evento
 *  global (`aegis:me`) para que la ficha de Lugar y el mapa hagan lo suyo.
 */

const GEO_ERROR_EVENT = "aegis:geo-error";

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
