# Backend permanente

El problema del sitio publicado en GitHub Pages era simple: **Pages solo sirve
ficheros estáticos**, así que el cliente no tenía a quién preguntar. La solución
no es un parche en el cliente, es ejecutar la API de verdad y apuntar el cliente
a ella. Este documento es el «cómo», sin cuentas inventadas y sin depender de
que un túnel siga vivo.

## Qué se despliega

Un único contenedor con las dos mitades:

| Capa | Qué es | Dónde |
|---|---|---|
| API | FastAPI + Uvicorn, 17 fuentes de ingesta, SQLite | `:8000/api/*` |
| Cliente | Next.js exportado a estático (`frontend/out`) | `:8000/*` |
| Datos | `aegis.sqlite` + tablas de analista | volumen `/data` |

Un proceso, un puerto, sin Redis ni Postgres. La base se poda cada 24 h
(`RETENTION_DAYS=7`) y las posiciones se recortan cada 5 min (`PLAYBACK_HOURS=6`),
así que el disco se queda en decenas de MB.

## Opción 1 · Local o servidor propio (30 s)

```bash
docker compose up --build      # http://localhost:8000
```

El volumen `aegis-data` conserva la base entre reinicios.

## Opción 2 · Fly.io (recomendada: sale casi gratis)

```bash
fly launch --no-deploy --copy-config --name aegis-osint
fly volumes create aegis_data --size 1
fly deploy
fly open
```

`fly.toml` ya trae `auto_stop_machines = "suspend"`: sin tráfico la máquina se
duerme y no consume. Con 512 MB va sobrado.

Claves opcionales (nunca en el repo):

```bash
fly secrets set AISSTREAM_API_KEY=... FIRMS_MAP_KEY=... OPENAI_API_KEY=...
```

## Opción 3 · Render Free

`render.yaml` es un blueprint: New → Blueprint → repo → Render construye el
`Dockerfile` y pone el healthcheck en `/api/health`. El plan gratuito ofrece
una URL HTTPS estable, pero duerme el servicio tras un periodo sin tráfico;
el primer acceso posterior puede tardar. No admite discos persistentes:
SQLite vive en `/tmp` y se pierde al reiniciar o redesplegar. Es útil para
poner el mapa en marcha gratis, no para conservar casos o histórico.

## Opción 4 · Oracle Cloud Always Free (la caja del proyecto)

```bash
git clone https://github.com/Risego2000/aegis2026 && cd aegis2026
docker compose up -d --build
```

Abre el puerto 8000 en la lista de seguridad de la VCN y, si quieres HTTPS,
pon Caddy o Cloudflare delante. En esa instancia conviene `RETENTION_DAYS=7`.

## Imagen ya construida

El workflow `.github/workflows/docker.yml` publica en cada tag:

```
ghcr.io/risego2000/aegis2026:latest
```

Sirve para desplegar sin compilar: `docker run -p 8000:8000 -v aegis:/data ghcr.io/risego2000/aegis2026:latest`.

## Apuntar el cliente de Pages al backend

El cliente resuelve la API en cascada, **sin recompilar**:

1. `?api=https://mi-backend.example` en la URL, solo para ese navegador.
2. `runtime-config.json` del propio sitio:
   ```json
   { "api": "https://mi-backend.example" }
   ```
3. `NEXT_PUBLIC_AEGIS_API` en tiempo de compilación.
4. Mismo origen (cuando API y cliente se sirven juntos, como en el contenedor).

En GitHub Pages no edites el fichero a mano: el workflow **AEGIS · Pages** lo
reescribe con `vars.AEGIS_API` (o el input `api_url`) y advierte si
`/api/health` no responde. Después verifica que el `runtime-config.json`
dentro de `frontend/out` lleva esa URL. El cliente se publica incluso si la
API está caída, y muestra el aviso de desconexión hasta recuperarla.

## Variables de entorno

| Variable | Por defecto | Para qué |
|---|---|---|
| `HOST` / `PORT` | `0.0.0.0` / `8000` | escucha |
| `SQLITE_PATH` | `data/osint.db` | base (en contenedor: `/data/aegis.sqlite`) |
| `FRONTEND_DIR` | `frontend/out` | cliente estático |
| `RETENTION_DAYS` | `7` | poda de sucesos |
| `PLAYBACK_ENABLED` / `PLAYBACK_INTERVAL` / `PLAYBACK_HOURS` | `true` / `300` / `6` | reproducción |
| `TLP` | `CLEAR` | marca por defecto de los productos |
| `AEGIS_WEBHOOK_URL` | vacío | avisos de watchlists (Slack, n8n…) |
| `ENABLE_IODA` | `true` | cortes de internet (sin clave) |
| `AISSTREAM_API_KEY`, `FIRMS_MAP_KEY`, `OPENAI_API_KEY` | vacías | opcionales |

## Endpoints de analista

| Ruta | Qué devuelve |
|---|---|
| `/api/events` | sucesos con `admiralty`, `tlp`, `grading` |
| `/api/gnss` | calidad GNSS por celda de 1° (NIC/NACp) |
| `/api/anomalies` | huecos AIS, velocidades imposibles, buques parados |
| `/api/watchlists` (GET/POST/DELETE) | reglas de vigilancia + `/hits` |
| `/api/cases` … `/report` … `/verify` | casos con cadena SHA-256 |
| `/api/graph`, `/api/graph/export?fmt=graphml` | grafo de vínculos |
| `/api/playback?ts=…` | posiciones históricas muestreadas |
| `/api/country/{ISO3}` | perfil PMESII + índice de estabilidad |
| `/api/report/sitrep` | SITREP en Markdown |
| `/api/export/stix` | bundle STIX 2.1 |
| `/api/sources/transparency` | tasa de acierto, latencia y volumen reales por fuente |

Todas estas funciones se usan desde la pestaña **Analista** del panel derecho:
SITREP, patrones (GNSS + AIS), casos con verificación de cadena, grafo con
descarga GraphML, reproducción con deslizador y transparencia de fuentes. Los
patrones también llegan solos a `/ws/alerts` (squawk de emergencia, posición
estancada, buque que se apaga, tren con retraso, repunte de focos, celda GNSS
degradada), con 30 min de enfriamiento por patrón y sujeto.

## MCP (que un modelo consulte el archivo)

`scripts/mcp_server.py` habla MCP por stdio y solo usa la stdlib:

```json
{"mcpServers": {"aegis": {"command": "python3",
  "args": ["scripts/mcp_server.py"],
  "env": {"AEGIS_API": "https://mi-backend.example"}}}}
```

Herramientas: `aegis_events`, `aegis_sitrep`, `aegis_country`,
`aegis_anomalies`, `aegis_gnss`, `aegis_graph`.

## Lo que sigue sin poder hacer yo

- **Publicar**: no tengo tus credenciales de Fly/Render/Oracle ni de GitHub. El
  `push` y el `deploy` los lanzas tú; todo lo demás está listo.
- **Cuentas de pago**: nada de esto las necesita.
