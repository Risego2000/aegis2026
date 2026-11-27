# Enlaces públicos de AEGIS

> Si un enlace da **Error 1033**, el túnel está en el hueco de reconexión (10-20 s):
> recarga. Los dos llevan a la misma aplicación; usa el segundo si el primero falla.
> El vigilante comprueba ambos cada minuto y guarda el resultado en `/api/links`.

| Vía | Enlace | Estado |
|---|---|---|
| Cloudflare (principal) | https://teams-generic-nvidia-noted.trycloudflare.com | activo |
| SSH localhost.run (respaldo) | https://b9ea8f314b9197.app.lhr.life | limitado por la capa gratuita |
| Preview de Arena (puerto 8000) | panel lateral del workspace | siempre disponible |

Actualizado: 2026-11-27 05:28 UTC

### Revisión de punta a punta (27 nov, 04:20 UTC)
- **Trenes animados**: ahora avanzan por la vía entre refrescos (20 s de deriva,
  misma deriva que se recalcula en el cliente con `speed_kmh`); el icono gira
  según el rumbo de la vía (`track`). Por debajo de z4 se ve la capa fija.
- **Toda la capa de tráfico verificada en navegador real**: aviones (todos, sin
  agrupar), buques, trenes, vías (`railways-line`), derrotas (`sealanes`),
  cámaras (con burbujas hasta z9 y puntos a partir de ahí).
- **Cúmulo de sucesos**: clic exacto comprobado — el desglose abría con el mismo
  recuento del cúmulo (349 = 349).
- **Ficha de Lugar**: ventanas 24 h / 7 días / 30 días en una sola fila;
  contadores de eventos, aeronaves, buques, satélites, cámaras y trenes.
- **Cámaras**: imagen real servida por el proxy propio (`/api/cameras/{id}/frame`).
- **`/api/cameras`** negocia gzip: navegador comprimido, scripts con JSON plano.
- Reproductor de vídeo: la ventana negra a las 04:17 era el fotograma nocturno.

### Ampliación de alcance (27 nov, 05:25 UTC)

**Todo en tiempo real, con iconos y foto en la ficha**

- **Aeronaves militares y oficiales**: capa nueva `adsb-mil` (lista mundial
  `/v2/mil` del agregador, sin clave) + clasificación propia por indicativo
  (RCH, SAM, IFC…), tipo ICAO (C-17, KC-135, E-3, P-8, drones, helicópteros) y
  `dbFlags`. Icono de caza para militares, ala recta para vuelos de Estado y
  helicóptero cuando corresponde. **38 militares** en el último barrido.
- **Trenes por tipo de servicio**: cercanías, media distancia, larga distancia,
  alta velocidad y bajo coste, clasificados con el GTFS real de Renfe (no por
  el nombre del fichero). **512 trenes** en vivo; color e icono distintos por
  servicio (metro para cercanías, tren clásico para el resto).
- **Red viaria y ferroviaria de todos los países visibles**: Natural Earth 1:10m
  (56 600 carreteras) recortado a la ventana del mapa en `/api/basemap/infra_view`.
  Carretera en **línea continua azul** y ferrocarril en **discontinua ámbar**.
  Se cargan desde z6 (antes z2, donde no se leen y cuestan fotogramas).
- **Iconos característicos**: 16 iconos dibujados a mano (terremoto, ciclón,
  llama, explosión, multitud, estrella militar, banderas, barras, aviso, cono,
  satélite con paneles, tren, metro, cámara, barco, caza). Todos escalan con el
  zoom en las 10 capas.
- **Fotografía real en la ficha de cada elemento**: avión (Planespotters por
  hex/matrícula), buque, tren (material rodante real), satélite (Wikimedia
  Commons) y cámara (fotograma en vivo). Los sucesos muestran la **escena de
  satélite Esri del punto exacto** donde se detectó el incendio, la imagen
  oficial de NASA/JRC o el `og:image` del medio que informó.
- **Amenazas para la población**: `/api/events/priority` puntúa cada suceso
  0-10 (categoría, gravedad, corroboración y palabras de riesgo del titular) y
  lo explica. Pestaña **Amenazas** en el panel, ordenada, con filtros de
  ventana (24 h / 7 d / 30 d) y umbral (media / alta / crítica).
- **Mi ubicación**: botón ◎ en el mapa y en el buscador. Centra el mapa, deja un
  pulso azul y abre la ficha de Lugar con lo que hay alrededor. Escribir
  «cerca» en el buscador hace lo mismo. La posición **no sale del navegador**.
- **Fluidez medida** (Chromium software, 2 vCPU): vista global **60 fps** en
  régimen, z5.5 **34 fps**, z7-10 **19-34 fps**. Claves del arreglo: el halo de
  los iconos era una expresión por dato (obligaba a regenerar el SDF de cada
  icono en cada fotograma), y las escrituras de la animación se han espaciado
  (1,2 s lejos / 0,8 s cerca / 1 s para trenes). Antes: 2-9 fps.
- **Clic preciso**: un elemento concreto (avión, tren, cámara, barco, satélite)
  tiene prioridad sobre un cúmulo de sucesos que lo tape.

## Qué incluye esta versión

### Datos
- **Sucesos OSINT** de 10 fuentes: USGS, EMSC, GDACS, EONET, NASA FIRMS, GDELT, NWS, **DGT (tráfico)**, **Renfe (avisos)** y cámaras.
- **Tráfico de la DGT en tiempo real** (DATEX II): ~800 incidencias por ciclo con carretera, punto kilométrico, municipio, provincia y sentido. Categorías nuevas «Tráfico» y «Transporte».
- **Trenes de Renfe** con índice GTFS real: **1.505 paradas con nombre, 140.002 viajes y 946 líneas**. La ficha muestra destino, próxima parada por su nombre, itinerario completo con posición de cada estación y el aviso de servicio que afecte a la línea.
- **Aeronaves y buques con su fotografía** (Planespotters / Wikimedia, servidas por proxy propio).
- **Cámaras**: 8.798 de 8 redes públicas.

### En vivo
- **Un solo canal** (`/api/poll`, long-polling) en lugar de diez temporizadores: el servidor avisa cuando cambia una capa y el cliente recarga solo esa. Latencia de 1-4 s.
- **Eventos incrementales** cada 15 s (`?since=`) y chip «AHORA» para los últimos 15 minutos.
- **Avisos del sistema** (botón 🔔 de la cabecera): notificaciones del navegador con la pestaña cerrada cuando salta una zona vigilada.

### Uso
- **Compartir vista** (botón ⤴): el enlace guarda encuadre, periodo, categorías y búsqueda.
- **Descargar lo que se ve** en **CSV** (Excel, separador «;») o **GeoJSON** (QGIS).
- **PWA**: la app se instala y abre aunque el túnel parpadee (service worker + manifest).

### Robustez
- `scripts/smoke.py`: 29 comprobaciones en **1 s** (también contra la URL pública).
- `scripts/guardian.py`: vigila los dos enlaces cada minuto, escribe `data/health_links.json` y hace **una copia diaria comprimida** de la base.
- `POST /api/ingest/*` cerrado fuera de localhost salvo que definas `AEGIS_TOKEN`.
- Retención 7 días, poda + `VACUUM` diario: la base queda en ~49 MB y el proyecto entero en ~79 MB (tope: 128 MB).

### Programas en marcha
- `AEGIS · backend` (`uvicorn` en :8000)
- `AEGIS · túnel Cloudflare` y `AEGIS · túnel SSH (respaldo)`
- `AEGIS · guardián de enlaces`

## Por qué cambian las URLs

Los túneles gratuitos sin cuenta no garantizan nombre fijo: si el proceso
muere, el proveedor asigna un subdominio nuevo. Para un enlace permanente hace
falta un **túnel con nombre de Cloudflare** (cuenta gratuita + dominio propio).
