"use client";

import { useEffect } from "react";
import { Icon } from "@/components/Icon";

type Props = {
  open: boolean;
  onClose: () => void;
  onOpenLayers: () => void;
  hours: number;
};

/** Guía rápida: explica la app entera en español, sin jerga. */
export default function Help({ open, onClose, onOpenLayers, hours }: Props) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="help-scrim" role="dialog" aria-modal="true" aria-label="Guía de uso" onClick={onClose}>
      <div className="help" onClick={(e) => e.stopPropagation()}>
        <div className="help-head">
          <div>
            <div className="help-title">Cómo funciona AEGIS</div>
            <div className="help-sub">
              Inteligencia de fuentes abiertas en tiempo real · todo lo que ves viene de datos públicos, sin claves ni pagos
            </div>
          </div>
          <button className="icon-btn" onClick={onClose} aria-label="Cerrar la guía"><Icon name="close" size={16} /></button>
        </div>

        <div className="help-body">
          <h3>En diez segundos</h3>
          <div className="help-grid">
            <div className="help-card">
              <h4><Icon name="grid" size={17} /> El mapa</h4>
              <p>
                Cada punto es un elemento real: un <b>suceso</b> (sismo, incendio, conflicto, protesta),
                una <b>aeronave</b>, un <b>buque</b>, un <b>satélite</b>, una <b>cámara</b> o un{" "}
                <b>sensor de aire</b>. El color indica el tipo y el tamaño, la magnitud.
              </p>
              <p>Pulsa <b>cualquier</b> punto y se abre su ficha a la derecha.</p>
            </div>
            <div className="help-card">
              <h4><Icon name="event" size={17} /> Las fichas</h4>
              <p>
                Cada ficha dice <b>qué</b> ha pasado, <b>dónde</b> (país y región), <b>cuándo</b> (hora
                local y UTC), con qué <b>gravedad</b> y qué <b>fuentes</b> lo confirman.
              </p>
              <p>Si pulsas el mapa en un punto sin nada, verás todo lo que hay alrededor.</p>
            </div>
            <div className="help-card">
              <h4><Icon name="layers" size={17} /> Capas y filtros</h4>
              <p>
                La barra <b>Explorar</b>, sobre el mapa, cambia entre vistas y enciende o apaga capas al
                instante: sucesos, aeronaves, buques, trenes, cámaras, satélites, aire, lugares y zonas.
              </p>
              <p>
                El botón de arriba a la izquierda abre el <b>centro de control</b> completo: capas (con
                el número de elementos de cada una), categorías, periodo, fondo del mapa y zonas vigiladas.
                Pulsa cualquier número para ver la lista de lo que cuenta.
              </p>
            </div>
            <div className="help-card">
              <h4><Icon name="bell" size={17} /> Alertas</h4>
              <p>
                Dibuja una <b>zona vigilada</b> y la app te avisa en cuanto una aeronave, un buque o un
                suceso entra o sale de ella. Sin configuración previa.
              </p>
            </div>
            <div className="help-card">
              <h4><Icon name="plane" size={17} /> Aeronaves y buques</h4>
              <p>
                Las aeronaves muestran el <b>recorrido</b> (aeropuerto de origen y de destino) cuando la
                ruta es pública. Los buques muestran su <b>puerto de destino</b> y la hora estimada de
                llegada; el AIS no transmite el puerto de salida.
              </p>
            </div>
            <div className="help-card">
              <h4><Icon name="camera" size={17} /> Cámaras de tráfico</h4>
              <p>
                Solo aparecen las redes que publican <b>imagen abierta sin clave</b>: País Vasco, Londres,
                California, Nueva York y Finlandia.
              </p>
              <p>
                En otros países (España incluida) no hay cámaras de tráfico públicas accesibles, así que
                no se inventan: el mapa muestra aviso explícito de cobertura.
              </p>
            </div>
          </div>

          <h3>Qué significa cada cifra</h3>
          <div className="help-kv">
            <span>Eventos vista</span><span>sucesos dentro del trozo de mapa que estás mirando</span>
            <span>Archivo</span><span>sucesos guardados en total (últimos 30 días)</span>
            <span>Aeronaves</span><span>aviones con señal ADS-B recibida ahora</span>
            <span>Buques</span><span>barcos con señal AIS recibida ahora</span>
            <span>Satélites</span><span>satélites calculados con órbitas públicas</span>
            <span>Cámaras</span><span>cámaras indexadas (con o sin imagen en este instante)</span>
            <span>Aire</span><span>sensores de calidad del aire consultados</span>
            <span>Fuentes</span><span>servicios de datos que han respondido en el último ciclo</span>
          </div>

          <h3>Gestión del tiempo</h3>
          <p className="dim" style={{ fontSize: 12, lineHeight: 1.6, margin: "0 0 10px" }}>
            El periodo elegido ({hours >= 24 ? `${Math.round(hours / 24)} días` : `${hours} horas`}) filtra
            los sucesos. El tráfico aéreo, marítimo y las cámaras son siempre el último dato disponible. La
            barra inferior muestra la distribución de sucesos en el tiempo; pasa el ratón por una barra para
            ver cuándo ocurrió.
          </p>

          <h3>Atajos</h3>
          <div className="help-kv">
            <span>?</span><span>abrir esta guía</span>
            <span>Esc</span><span>cerrar ficha, lista o ventana</span>
            <span>+ / −</span><span>acercar y alejar el mapa</span>
            <span>doble clic</span><span>acercar en ese punto</span>
          </div>

          <h3>Límites, dichos sin rodeos</h3>
          <p className="dim" style={{ fontSize: 12, lineHeight: 1.6, margin: 0 }}>
            Las fuentes son abiertas, así que la cobertura es desigual: la red sísmica y los incendios son
            mundiales; el tráfico aéreo depende de dónde haya receptores; el AIS abierto cubre sobre todo el
            Báltico; las cámaras, cinco redes. Cuando no hay datos de una zona, la app lo dice en lugar de
            rellenar el hueco.
          </p>
        </div>

        <div className="help-foot">
          <span>Todo en español · datos abiertos · sin claves</span>
          <div className="btn-row">
            <button className="btn" onClick={onOpenLayers}>Abrir capas y filtros</button>
            <button className="btn primary" onClick={onClose}>Entendido</button>
          </div>
        </div>
      </div>
    </div>
  );
}
