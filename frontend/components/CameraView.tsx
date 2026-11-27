"use client";

/**
 * Visor de cámara pública en vivo.
 *
 * La imagen se pide al backend (`/api/cameras/{id}/frame`), que a su vez la
 * descarga del operador: así no hay contenido mixto, ni CORS, ni fugas de
 * referrer, y varios analistas pueden mirar la misma cámara sin castigar al
 * origen. Se refresca sola con el intervalo elegido.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api } from "@/lib/api";
import { fmtNumber, timeAgo } from "@/lib/format";

type Props = {
  cameraId: string;
  onClose: () => void;
  onFocus?: (lat: number, lon: number) => void;
  onFly?: (lat: number, lon: number) => void;
};

const INTERVALS = [
  { s: 2, label: "2 s" },
  { s: 5, label: "5 s" },
  { s: 15, label: "15 s" },
  { s: 60, label: "1 min" },
];

export default function CameraView({ cameraId, onClose, onFly }: Props) {
  const [camera, setCamera] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [cadence, setCadence] = useState(5);
  const [tick, setTick] = useState(0);
  const [loadedAt, setLoadedAt] = useState<number>(0);
  const [imgError, setImgError] = useState(false);
  const [paused, setPaused] = useState(false);
  // algunos operadores (Bilbao, Vitoria…) bloquean IP de centro de datos pero
  // sirven la imagen a un navegador normal: si el proxy falla, se pide directa
  const [direct, setDirect] = useState(false);
  const boxRef = useRef<HTMLDivElement | null>(null);

  /* ficha de la cámara */
  useEffect(() => {
    let alive = true;
    setCamera(null);
    setError(null);
    setImgError(false);
    setDirect(false);
    api
      .camera(cameraId)
      .then((r) => {
        if (alive) setCamera(r.camera);
      })
      .catch((err: any) => {
        if (alive) setError(String(err?.message ?? err).slice(0, 160));
      });
    return () => {
      alive = false;
    };
  }, [cameraId]);

  /* refresco de la imagen */
  useEffect(() => {
    if (paused) return;
    const id = setInterval(() => setTick((t) => t + 1), cadence * 1000);
    return () => clearInterval(id);
  }, [cadence, paused, cameraId]);

  const proxied = `/api/cameras/${encodeURIComponent(cameraId)}/frame?t=${tick}`;
  const src = useMemo(
    () => (direct && camera?.image ? `${camera.image}${camera.image.includes("?") ? "&" : "?"
      }t=${tick}` : proxied),
    [direct, camera?.image, proxied, tick]
  );

  const reload = useCallback(() => {
    setImgError(false);
    setTick((t) => t + 1);
  }, []);

  // primer fallo del proxy -> intento directo contra el operador una sola vez
  const handleError = useCallback(() => {
    if (!direct && camera?.image) {
      setDirect(true);
      return;
    }
    setImgError(true);
  }, [direct, camera?.image]);

  const meta: { label: string; value: string }[] = camera
    ? [
        { label: "Red", value: camera.network_label ?? camera.network },
        { label: "Tipo", value: camera.kind ?? "—" },
        { label: "Ubicación", value: camera.place || "—" },
        ...(camera.route ? [{ label: "Vía", value: camera.route }] : []),
        { label: "Operador", value: camera.operator ?? "—" },
        { label: "País", value: camera.country ?? "—" },
        {
          label: "Coordenadas",
          value: `${Number(camera.lat).toFixed(4)}, ${Number(camera.lon).toFixed(4)}`,
        },
        { label: "Estado", value: camera.online ? "en servicio" : "fuera de servicio" },
        ...(camera.updated_at ? [{ label: "Dato", value: String(camera.updated_at) }] : []),
        { label: "Catálogo", value: camera.age_s ? `hace ${timeAgo(new Date(Date.now() - camera.age_s * 1000).toISOString())}` : "—" },
      ]
    : [];

  return (
    <div>
      <div className="section" style={{ display: "flex", alignItems: "flex-start", gap: 8 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div className="section-title" style={{ marginBottom: 3 }}>Cámara en vivo</div>
          <div style={{ fontSize: 13, fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis" }}>
            {camera?.name ?? cameraId}
          </div>
          <div className="tiny faint mono" style={{ marginTop: 2 }}>
            {camera?.network_label ?? ""}{camera?.place ? ` · ${camera.place}` : ""}
          </div>
        </div>
        <button className="panel-close" style={{ display: "grid" }} onClick={onClose} aria-label="Cerrar cámara">
          ✕
        </button>
      </div>

      <div className="section" style={{ paddingTop: 0 }}>
        <div className="camera-frame" ref={boxRef}>
          {error && <div className="camera-msg" style={{ color: "var(--danger)" }}>{error}</div>}
          {!error && imgError && (
            <div className="camera-msg">
              La cámara no devuelve imagen ahora mismo.
              <div style={{ marginTop: 8 }}>
                <button className="btn" onClick={reload}>Reintentar</button>
              </div>
            </div>
          )}
          {!error && (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              key={src}
              src={src}
              alt={`Imagen en vivo de ${camera?.name ?? cameraId}`}
              onLoad={() => { setLoadedAt(Date.now()); setImgError(false); }}
              onError={handleError}
              referrerPolicy="no-referrer"
              style={{ display: imgError ? "none" : "block" }}
            />
          )}
        </div>

        <div className="btn-row" style={{ marginTop: 8, flexWrap: "wrap" }}>
          {INTERVALS.map((it) => (
            <button
              key={it.s}
              className={`chip ${cadence === it.s ? "active" : ""}`}
              onClick={() => setCadence(it.s)}
            >
              {it.label}
            </button>
          ))}
          <button className={`chip ${paused ? "active" : ""}`} onClick={() => setPaused((v) => !v)}>
            {paused ? "▶ reanudar" : "❚❚ pausar"}
          </button>
          <button className="chip" onClick={reload}>↻ ahora</button>
        </div>
        {direct && (
          <div className="tiny faint" style={{ marginTop: 6 }}>
            El proxy del backend no alcanza esta cámara (el operador filtra tráfico de centro de
            datos). Se pide directamente al operador desde tu navegador.
          </div>
        )}
        <div className="tiny faint mono" style={{ marginTop: 6 }}>
          {paused
            ? "refresco en pausa"
            : loadedAt
              ? `último fotograma hace ${timeAgo(new Date(loadedAt).toISOString())} · refresco cada ${cadence} s`
              : "cargando fotograma…"}
        </div>
      </div>

      <div className="section">
        <div className="section-title">Ficha de la cámara</div>
        <dl className="kv">
          {meta.map((row) => (
            <div key={row.label} style={{ display: "contents" }}>
              <dt>{row.label}</dt>
              <dd>{row.value}</dd>
            </div>
          ))}
        </dl>
        <div className="btn-row" style={{ marginTop: 8, flexWrap: "wrap" }}>
          {camera && onFly && (
            <button className="btn" onClick={() => onFly(Number(camera.lat), Number(camera.lon))}>
              ⊕ Centrar
            </button>
          )}
          {camera?.image && (
            <a className="btn" href={camera.image} target="_blank" rel="noreferrer">
              ↗ Original
            </a>
          )}
          {camera?.source_url && (
            <a className="btn" href={camera.source_url} target="_blank" rel="noreferrer">
              ↗ Operador
            </a>
          )}
          <button
            className="btn"
            onClick={() => {
              const url = `${window.location.origin}/api/cameras/${encodeURIComponent(cameraId)}/frame`;
              navigator.clipboard?.writeText(url).catch(() => {});
            }}
            title="Copiar el enlace del fotograma"
          >
            ⧉ Enlace
          </button>
        </div>
        <div className="tiny faint" style={{ marginTop: 8 }}>
          Imagen servida por el operador público ({camera?.operator ?? "red abierta"}) y reenviada por
          el backend de AEGIS para evitar contenido mixto. Sin grabación: solo el fotograma actual.
        </div>
      </div>

      <div className="section" style={{ borderBottom: "none" }}>
        <div className="section-title">Red</div>
        <div className="tiny faint">
          Cámaras abiertas indexadas: <strong className="mono">{fmtNumber(camera?.network_total)}</strong>
          {" "}en total. Pulsa sobre otra cámara del mapa para cambiar de objetivo sin cerrar el visor.
        </div>
      </div>
    </div>
  );
}
