# AEGIS — Centro de inteligencia abierta

Mapa en vivo de sucesos, tráfico aéreo y marítimo, trenes, satélites y cámaras
públicas de todo el mundo, construido **sin claves de pago** y con datos abiertos.

**[▶ Ver el mapa publicado](https://risego2000.github.io/aegis2026/)** — cliente
estático en GitHub Pages apuntando a la API desde la variable `AEGIS_API`.

![estado](https://img.shields.io/badge/fuentes-15%20abiertas-35e0d0) ![licencia](https://img.shields.io/badge/licencia-MIT-informational)

## Qué muestra

| Capa | Datos | Fuente |
|---|---|---|
| **Sucesos OSINT** | terremotos, desastres, incendios, conflicto, protestas, diplomacia, economía, tráfico | USGS, EMSC, GDACS, EONET, NASA FIRMS, GDELT, NWS, DGT, Renfe |
| **Aeronaves** | ADS-B, con clase militar/oficial detectada | adsb.lol, adsb.fi |
| **Buques** | AIS | Digitraffic (Finlandia) |
| **Trenes** | cercanías, media y larga distancia, alta velocidad y bajo coste | Renfe GTFS-RT, Amtrak |
| **Satélites** | propagados con SGP4 desde TLE | Celestrak (vía espejo) |
| **Cámaras** | 8 797 cámaras de tráfico de 4 países | DGT, Madrid, Euskadi, SCT, Caltrans, NYC, TfL, Digitraffic |
| **Calidad del aire** | 5 089 sensores | Sensor.Community |
| **Red viaria y ferroviaria** | 56 600 carreteras y 25 413 líneas de ferrocarril | Natural Earth 1:10m |
| **Derrotas marítimas** | 402 rutas derivadas de AIS | IMF PortWatch |

## Funciones destacadas

- **Prioridad de amenaza**: cada suceso recibe una puntuación 0-10 de riesgo para
  la población o alarma social, con el motivo explicado (`/api/events/priority`).
- **Fotografía real en la ficha de cada elemento**: avión (Planespotters por
  hex/matrícula), buque, tren y satélite (Wikimedia Commons), cámara (fotograma
  en vivo) y suceso (escena de satélite Esri del punto exacto, imagen oficial de
  NASA/JRC o `og:image` del medio).
- **Iconos característicos** dibujados a mano, uno por categoría y tipo, todos
  proporcionales al zoom.
- **Mi ubicación**: botón en el mapa y en el buscador; abre la ficha de Lugar con
  lo que hay alrededor. La posición nunca sale del navegador.
- **En vivo de verdad**: canal WebSocket, refresco incremental por marca de agua
  (`?since=`) y guardianes de memoria en el backend.
- **Exportación** a CSV y GeoJSON de todo lo filtrado.

## Arranque

```bash
# 1. dependencias
pip install -r backend/requirements.txt
cd frontend && npm install && cd ..

# 2. datos geográficos que no se versionan (red viaria y ferrocarril)
python3 scripts/fetch_geo.py

# 3. backend (puerto 8000) y frontend (puerto 3000)
cd backend && python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000
cd frontend && npm run dev
```

El frontend de desarrollo llama a `/api/*`; en producción se sirve el export
estático (`frontend/site/`) desde el propio backend.

### Variables de entorno

Todas son opcionales: la aplicación funciona sin ninguna. Ver `.env.example`.

## Despliegue

| Pieza | Dónde | Cómo |
|---|---|---|
| **Cliente** (mapa) | GitHub Pages · `https://risego2000.github.io/aegis2026/` | workflow `AEGIS · Pages`, se compila con `NEXT_BASE_PATH=/aegis2026` |
| **API** (motor OSINT) | tu servidor o un túnel | `cd backend && python3 -m uvicorn app.main:app --port 8000` |

El cliente publicado necesita saber dónde está la API: se configura en
*Settings → Secrets and variables → Actions → **Variables** → `AEGIS_API`* con la
URL pública del backend (por ejemplo `https://tu-tunel.trycloudflare.com`). Al
cambiar la variable, lanza el workflow **AEGIS · Pages** (`workflow_dispatch`) y
el sitio se recompila apuntando a la nueva URL. Sin la variable, el sitio carga
la interfaz y muestra el aviso de que la API no responde.

El backend ya envía `Access-Control-Allow-Origin: *` (configurable con
`CORS_ORIGINS`), así que no hace falta tocar nada más.

Para exponer el backend por HTTPS con un túnel público sin cuenta:

```bash
bash scripts/tunnel.sh        # cloudflared
bash scripts/tunnel_backup.sh # ssh a localhost.run
```

## Estructura

```
backend/app/
  api/routes.py        todos los endpoints (/api/events, /live/*, /basemap/*, /media/*)
  ingest/              un módulo por fuente (usgs, firms, adsb, ais, trains, gtfs…)
  storage/sqlite.py    SQLite + R-Tree (eventos, deduplicación, pruner)
  live.py              capas vivas (aeronaves, buques, trenes, satélites)
frontend/
  components/MapView.tsx   motor del mapa (MapLibre), capas e iconos
  components/RightPanel.tsx fichas: suceso, elemento, cámara, lugar, amenazas
  lib/mapIcons.ts           los 16 iconos dibujados en canvas
scripts/
  fetch_geo.py         descarga y prepara la cartografía base
  smoke.py             29 comprobaciones de humo contra un servidor
  guardian.py          vigilante de enlaces públicos y salud
```

## Fluidez

Medido en Chromium con render por software (2 vCPU): **60 fps** en vista global
en régimen, **34 fps** a escala regional y **19-34 fps** de cerca con todas las
capas encendidas. Lo que importa para no colgar el navegador:

- el halo de los iconos es constante (una expresión por dato obliga a MapLibre
  a regenerar la textura SDF de cada icono **en cada fotograma**);
- las escrituras de la animación se espacian (1,2 s lejos / 0,8 s cerca);
- la cartografía de redes se carga desde z6, recortada a la ventana visible y
  con tope de puntos.

## Licencia

MIT. Los datos pertenecen a sus fuentes y se usan según sus términos abiertos.
