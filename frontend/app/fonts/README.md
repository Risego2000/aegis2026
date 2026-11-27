# Fuentes

Autoalojadas para que el build no dependa de Google Fonts y el cliente no haga
peticiones a terceros (mejor privacidad y arranque más rápido).

| Fichero | Familia | Uso | Licencia |
|---|---|---|---|
| `inter-latin-{400,500,600,700}-normal.woff2` | Inter | texto de interfaz | SIL Open Font License 1.1 |
| `jetbrains-mono-latin-{400,600}-normal.woff2` | JetBrains Mono | cifras, coordenadas, códigos | SIL Open Font License 1.1 |

Subset latino (incluye tildes, ñ y signos de apertura). Descargadas del CDN de
Fontsource (`cdn.jsdelivr.net/fontsource/fonts`) y versionadas aquí; se cargan
con `next/font/local` desde `app/layout.tsx`.

- Inter: https://rsms.me/inter/ · OFL
- JetBrains Mono: https://www.jetbrains.com/lp/mono/ · OFL

Si hay que añadir un peso nuevo, se descarga el mismo subset y se declara en
`layout.tsx`; no se usan ficheros variables para no duplicar el coste.
