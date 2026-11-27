# Enlaces públicos de AEGIS

> **Estado comprobado el 27 de noviembre de 2026, 10:15 UTC: no hay backend
> público.** Los dos túneles están caídos, así que el mapa de GitHub Pages
> (`https://risego2000.github.io/aegis2026/`) carga la interfaz y muestra el
> aviso de que la API no responde. El workflow ya escribe `AEGIS_API` en
> `runtime-config.json` y se niega a publicar si `/api/health` no responde; lo
> único que falta es un motor público vivo al que apuntar.

| Vía | Enlace | Estado |
|---|---|---|
| Cloudflare (principal) | https://teams-generic-nvidia-noted.trycloudflare.com | **caído** — el subdominio ya no resuelve (cambia al reconectar) |
| SSH localhost.run (respaldo) | https://b9ea8f314b9197.app.lhr.life | **caído** — HTTP 502 en `/` y en `/api/health` |
| Sitio estático | https://risego2000.github.io/aegis2026/ | publicado, sin datos |

### Cómo recuperarlo

1. Levanta el backend donde toque (`bash scripts/dev.sh` o `make backend` +
   `make build`, o un túnel nuevo con `bash scripts/tunnel.sh`).
2. Publica esa URL para todo el mundo: ponla en
   *Settings → Secrets and variables → Actions → Variables → `AEGIS_API`* y
   lanza **AEGIS · Pages**. El workflow la escribe en `runtime-config.json`,
   comprueba `/api/health` y aborta si no responde. Para una publicación
   puntual, usa **Run workflow → `api_url`** sin cambiar la variable.
3. Si solo quieres probar en tu navegador sin desplegar, abre
   `https://risego2000.github.io/aegis2026/?api=https://tu-backend`.
4. Comprueba que responde con `BASE=https://tu-backend python3 scripts/smoke.py`.
   El workflow **AEGIS · salud de lo publicado** lee el `runtime-config.json`
   publicado y prueba la API real del sitio cada 30 minutos, así que una URL
   vacía o muerta se ve en Actions en vez de descubrirse por casualidad.

### Revisión de punta a punta (27 nov, 04:20 UTC)
- **Trenes animados**: avanzan por la vía entre refrescos (20 s de deriva, la
  misma que recalcula el cliente con `speed_kmh`); el icono gira según el rumbo
  de la vía (`track`). Por debajo de z4 se ve la capa fija.
- **Toda la capa de tráfico verificada en navegador real**: aviones (todos, sin
  agrupar), buques, trenes, vías (`railways-line`), derrotas (`sealanes`),
  cámaras.
- **Cúmulo de sucesos**: clic exacto comprobado (349 = 349).
- **Ficha de Lugar**: ventanas 24 h / 7 días / 30 días en una sola fila.
- **Cámaras**: imagen real servida por el proxy propio (`/api/cameras/{id}/frame`).
- **`/api/cameras`** negocia gzip.

### Ampliación de alcance (27 nov, 05:25 UTC)

- **Aeronaves militares y oficiales**: capa `adsb-mil` + clasificación propia por
  indicativo y tipo ICAO.
- **Trenes por tipo de servicio**: cercanías, media, larga distancia, alta
  velocidad y bajo coste, con el GTFS real de Renfe. 512 trenes en vivo.
- **Red viaria y ferroviaria** desde z6, recortada a la ventana visible.
- **Iconos característicos**: 16 dibujados a mano, proporcionales al zoom.
- **Fotografía real** en la ficha de cada elemento.
- **Amenazas para la población**: `/api/events/priority`, 0-10 y con el motivo.
- **Fluidez medida** (Chromium software, 2 vCPU): 60 fps global, 34 fps a z5.5,
  19-34 fps de cerca con todas las capas.

## Qué incluye esta versión

### Datos
- **Sucesos OSINT** de 10 fuentes: USGS, EMSC, GDACS, EONET, NASA FIRMS, GDELT,
  NWS, DGT, Renfe y cámaras.
- **Tráfico de la DGT** (DATEX II): ~800 incidencias por ciclo.
- **Trenes de Renfe** con índice GTFS real: 1.505 paradas, 140.002 viajes y 946
  líneas.
- **Cámaras**: 8.798 de 8 redes públicas.

### En vivo
- **Un solo canal** (`/api/poll`, long-polling) en lugar de diez temporizadores.
- **Eventos incrementales** cada 15 s (`?since=`) y chip «AHORA».
- **Avisos del sistema** con la pestaña cerrada cuando salta una zona vigilada.

### Uso
- **Compartir vista** (botón ⤴): el enlace guarda encuadre, periodo, categorías
  y búsqueda.
- **Descargar lo que se ve** en CSV o GeoJSON.
- **PWA**: se instala y abre aunque el túnel parpadee.

### Robustez
- `make check`: tipos, lint y 17 tests de backend sin red.
- `scripts/smoke.py`: 29 comprobaciones, también contra una URL pública.
- `scripts/guardian.py`: vigila los enlaces, escribe `data/health_links.json` y
  hace una copia diaria comprimida de la base.
- `POST /api/ingest/*` cerrado fuera de localhost salvo que definas `AEGIS_TOKEN`.
- Tope de peticiones por IP en exportaciones, IA, fotogramas y fichas.
- Retención 7 días, poda + `VACUUM` diario.

## Por qué cambian las URLs

Los túneles gratuitos sin cuenta no garantizan nombre fijo: si el proceso muere,
el proveedor asigna un subdominio nuevo. Para un enlace permanente hace falta un
**túnel con nombre de Cloudflare** (cuenta gratuita + dominio propio) o un
servidor propio. Mientras tanto, `runtime-config.json` evita tener que recompilar
el sitio cada vez que cambie.
