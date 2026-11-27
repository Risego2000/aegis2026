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
| **Trenes** | cercanías, media y larga distancia, alta velocidad y bajo coste | Renfe GTFS-RT, FGC GTFS-RT, Amtrak |
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
# 1. dependencias: backend en un entorno virtual propio y cliente con el lockfile
make install          # crea .venv, instala requirements y hace npm ci

# 2. datos geográficos que no se versionan (red viaria y ferrocarril)
make geo              # o: python3 scripts/fetch_geo.py

# 3. backend (puerto 8000) y cliente de desarrollo (puerto 3001)
make backend          # cd backend && .venv/bin/python -m uvicorn app.main:app
make frontend
```

El cliente de desarrollo llama a `/api/*` (rewrite de Next a `127.0.0.1:8000`);
en producción se sirve el export estático (`frontend/out` o `frontend/site`)
desde el propio backend.

> El backend no se instala con `pip install` global: en Debian/Ubuntu con Python
> «gestionado por el sistema» (PEP 668) eso falla. `make install` usa `.venv`,
> que ya está en `.gitignore`. Las versiones de `backend/requirements.txt` están
> fijadas: el CI instala exactamente las mismas.

### Variables de entorno

Todas son opcionales: la aplicación funciona sin ninguna. Ver `.env.example`.

### Comprobaciones

```bash
make check     # tipos (tsc), lint (ESLint) y tests de backend, sin red
make smoke     # 29 comprobaciones contra un servidor en marcha
```

- `backend/tests/` (pytest): contrato HTTP con las fuentes apagadas y SQLite
  temporal, así que no depende de que USGS o GDELT respondan. El workflow
  `AEGIS · CI` ejecuta los tests, `tsc`, ESLint y el export estático en cada
  push y en cada PR.
- `scripts/smoke.py`: 29 comprobaciones contra una instancia real (capas, GTFS,
  fotograma de cámara, exportaciones y guarda de ingesta).
- `AEGIS · salud de lo publicado` lee el `runtime-config.json` del sitio y
  sondea cada 30 minutos la API a la que apunta; se pone en rojo si el fichero
  está vacío o la API no responde.

### Repuntar la API sin recompilar

El cliente resuelve el origen de la API en este orden:

1. `?api=https://mi-backend` en la URL del mapa — cambio inmediato, sin desplegar
   (sirve para recuperar el sitio publicado mientras se arregla el túnel).
2. `frontend/public/runtime-config.json` → `{ "api": "https://mi-backend" }` — se
   lee en tiempo de ejecución; no hay que recompilar el JavaScript.
3. `NEXT_PUBLIC_AEGIS_API` en tiempo de compilación (lo que usa el workflow de
   Pages).
4. Nada: rutas relativas contra el mismo origen.

En el fichero, `"api": ""` significa «sin opinión» y se respeta el valor de
compilación. En GitHub Pages el workflow **AEGIS · Pages** reescribe ese fichero
con `AEGIS_API` antes de compilar, comprueba que `/api/health` responde y no
publica si la URL falta o está muerta. También acepta el input manual `api_url`
para repuntar una publicación sin cambiar la variable. El prefijo del sitio
(`NEXT_BASE_PATH`) se aplica también al manifest, al icono y al service worker,
que antes se pedían a la raíz y daban 404 en GitHub Pages.

## Despliegue

| Pieza | Dónde | Cómo |
|---|---|---|
| **Cliente** (mapa) | GitHub Pages · `https://risego2000.github.io/aegis2026/` | workflow `AEGIS · Pages`, se compila con `NEXT_BASE_PATH=/aegis2026` y escribe `runtime-config.json` desde `AEGIS_API`; se puede repuntar con `?api=` o relanzando el workflow con `api_url` |
| **API** (motor OSINT) | tu servidor o un túnel | `cd backend && python3 -m uvicorn app.main:app --port 8000` |

El cliente publicado necesita saber dónde está la API: se configura en
*Settings → Secrets and variables → Actions → **Variables** → `AEGIS_API`* con la
URL pública del backend (por ejemplo `https://tu-tunel.trycloudflare.com`). Al
cambiar la variable, lanza el workflow **AEGIS · Pages** (`workflow_dispatch`) y
el sitio se recompila apuntando a la nueva URL: el workflow escribe esa URL en
`runtime-config.json` y verifica que la API responde antes de publicar. Para una
publicación puntual, el mismo workflow acepta el input **`api_url`**, que tiene
prioridad sobre la variable sin tocar la configuración del repositorio. Si el
backend cambia de sitio sin querer recompilar, un `?api=` en la URL lo repunta
solo para ese navegador. Sin una URL viva, Pages no publica una versión nueva y
la salud de lo publicado se pone en rojo.

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
  api/limits.py        tope de peticiones por IP en las rutas caras
  tests/               pytest: contrato HTTP y lógica pura, sin red
  ingest/              un módulo por fuente (usgs, firms, adsb, ais, trains, gtfs…)
  storage/sqlite.py    SQLite + R-Tree (eventos, deduplicación, pruner)
  live.py              capas vivas (aeronaves, buques, trenes, satélites)
frontend/
  components/MapView.tsx   motor del mapa (MapLibre), capas e iconos
  components/RightPanel.tsx fichas: suceso, elemento, cámara, lugar, amenazas
  lib/api.ts            cliente HTTP y origen de la API en tiempo de ejecución
  lib/mapIcons.ts           siluetas de capas y categorías dibujadas en canvas
  public/runtime-config.json  origen de la API (Pages lo reescribe desde AEGIS_API)
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

## Backend permanente

El sitio de GitHub Pages es solo el cliente: para que el mapa tenga datos hace
falta ejecutar la API. `Dockerfile`, `docker-compose.yml`, `fly.toml` y
`render.yaml` la empaquetan en un contenedor (FastAPI + cliente estático +
SQLite en un volumen). El workflow de Pages escribe la URL en
`frontend/public/runtime-config.json` antes de compilar y no publica si esa API
no responde; para una prueba inmediata, `?api=` repunta solo tu navegador.

Guía completa, variables y endpoints nuevos: [DEPLOY.md](DEPLOY.md).

## Panel de analista

La pestaña **⌘ Analista** del panel derecho reúne lo que hasta ahora solo estaba
en la API: SITREP descargable, patrones (calidad GNSS y anomalías AIS), casos
con cadena de custodia SHA-256 y verificación, grafo de vínculos con export
GraphML, reproducción histórica con deslizador y transparencia de fuentes.

Además, el servidor emite **alertas de patrón** por el canal en vivo (no solo de
geovalla): squawk de emergencia, posición estancada, buque que se apaga o salta,
tren con más de 20 min de retraso, repunte de focos térmicos y celdas con varias
aeronaves degradadas. Cada patrón tiene 30 min de enfriamiento.

Para comprobar IODA en tu servidor (la API no responde desde todas las redes):
`python3 scripts/check_ioda.py`.
