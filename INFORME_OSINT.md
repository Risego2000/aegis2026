# AEGIS — Qué le falta para ser el OSINT más completo de su campo

**Informe de producto y prioridades · 27 de noviembre de 2026**

Este documento compara AEGIS con las plataformas de referencia —Bellingcat,
Maltego, Palantir Gotham/Foundry, Recorded Future, Liveuamap, MISP, OpenCTI,
IMF PortWatch— y propone las funciones concretas que lo llevarían al nivel de
una herramienta de agencia. Está ordenado por **impacto operativo frente a
esfuerzo**, no por lucimiento.

---

## 1. Dónde estamos (lo que ya hacemos mejor que la media)

| Capacidad | AEGIS hoy | Referencia del sector |
|---|---|---|
| Mapa multi-dominio en vivo | eventos, aviones ADS-B, buques AIS, trenes GTFS-RT, satélites SGP4, cámaras, aire, tráfico DGT | Liveuamap (solo eventos), MarineTraffic (solo barcos) |
| Fusión de fuentes | 15 fuentes abiertas con deduplicación y multi-fuente por evento | Recorded Future (de pago) |
| Detalle de actor | ficha con foto real, itinerario de tren estación a estación, órbita de satélite | Flightradar24 / MarineTraffic (silo) |
| Coste y despliegue | 0 €, sin claves, un proceso, SQLite | todas las demás, suscripción o implementación |
| Exportación | CSV y GeoJSON de todo lo filtrado | Maltego (grafo), i2 (casos) |

**Lo que nos separa de "nivel agencia"**, por orden de relevancia:
no hay **análisis de relaciones**, ni **línea de tiempo por entidad**,
ni **alertas automáticas de patrón**, ni **gestión de casos con evidencia**,
ni **verificación de imagen por satélite**, ni **informes exportables**.

---

## 2. Funciones que nos pondrían por delante (propuesta priorizada)

### A. Inteligencia de patrones (lo que ninguna app gratuita hace bien)

1. **Alertas de comportamiento anómalo** *(impacto muy alto, esfuerzo medio)*
   Reglas sobre series ya presentes en la BD:
   - avión que apaga el transpondedor estando en zona de conflicto (`seen_pos`
     alto + cambio de emergencia),
   - buque que se detiene en mitad del mar o cambia rumbo hacia un cierre
     (lo que el sector llama *AIS gap* o *rendezvous*),
   - tren con retraso > 20 min repetido en la misma línea,
   - salto de magnitud en el número de focos térmicos FIRMS de una provincia.
   Ya existe el motor de geofences y el canal `/ws/alerts`: es donde encajan.

2. **Análisis de líneas de tiempo por entidad** *(alto, bajo)*
   Ficha de un avión/buque con su histórico de 24 h (posición, altitud,
   velocidad) dibujado como gráfica y sobre el mapa como estela completa.
   Guardamos posiciones: solo hay que exponerlas con `/api/live/{kind}/{id}/track`
   ampliado y una gráfica.

3. **Grafo de vínculos (estilo Maltego / i2, pero abierto)** *(muy alto, medio-alto)*
   Entidad → relaciones ya inferibles con los datos actuales:
   aeronave ↔ aeropuerto (salidas), buque ↔ puerto, tren ↔ línea ↔ estación,
   evento ↔ actor ↔ lugar, fuente ↔ evento. Vista de grafo navegable
   (Cytoscape o vis-network) y export a GraphML para Maltego. Es **la** función
   que convierte un visor en herramienta de investigación.

4. **Puntuación de credibilidad por evento** *(alto, bajo-medio)*
   Hoy contamos `sources_count`. El siguiente paso es una fórmula pública
   (fuentes independientes, antigüedad, coincidencia geográfica < 25 km,
   categoría) que se muestre como semáforo. Bellingcat y Recorded Future lo
   venden como producto; nosotros podemos dar la fórmula.

### B. Verificación y evidencia (lo que exige una agencia)

5. **Imagen satelital verificada en el punto** *(alto, medio)*
   Botón "ver por satélite" en cada evento que abre la tesela Esri ya pasada
   por nuestro proxy (sin clave) y la compara con la imagen de hace 30 días;
   con Sentinel-2 (10 m, gratuito) se puede añadir índice NDVI/calor.
   Es el flujo que recomienda cualquier guía OSINT 2026: *evento → imagen*.

6. **Gestión de casos con cadena de custodia** *(muy alto, alto)*
   Carpeta de caso con: eventos fijados, capturas con hora y fuente, notas del
   analista, etiquetas MITRE-style y export a PDF/informe. Bellingcat Pro lo
   cobra; lo diferencia un **hash SHA-256 por evidencia** y un registro
   append-only en SQLite — barato y da credibilidad legal.

7. **Informe diario autogenerado** *(alto, medio-bajo)*
   Plantilla en español con (a) lo nuevo por categoría, (b) los 10 eventos de
   mayor credibilidad, (c) movimiento de actores en zonas vigiladas,
   (d) incidencias de servicio. Exportable a PDF/Markdown con marca AEGIS.

### C. Cobertura y fuentes (lo que nos hace "completos")

8. **Más AIS fuera de Finlandia** *(alto, medio)*
   Digitraffic solo cubre aguas finesas (~890 buques). Añadir GPS del Estrecho,
   Gibraltar y Canarias ampliaría el interés para España sin claves:
   fuentes candidatas: `aisstream.io` (requiere clave gratuita),
   MarineTraffic Open (limitado), AISHub (reciprocidad). Con una clave gratuita
   de aisstream el salto es cualitativo.

9. **Más trenes y más países** *(medio, bajo)*
   Renfe + Amtrak ya dan 300-360 trenes. Siguientes feeds abiertos:
   NS/DSB (Países Bajos, Dinamarca) publican GTFS-RT sin clave; el índice GTFS
   ya está montado y se reutiliza.

10. **Vuelos militares y de Estado** *(muy alto en defensa, medio)*
    Filtrar por indicativos conocidos (RCH, IFC, SAM…) y por tipos (KC-135,
    C-17, E-3, P-8) sobre el ADS-B que ya recibimos. Es la función que hace
    famoso a ADS-B Exchange y aquí sale casi gratis: solo un filtro y un
    icono distinto.

11. **Tráfico marítimo de rutas y densidad** *(medio, bajo)*
    Ya integradas las derrotas IMF PortWatch; el paso siguiente es colorear
    la densidad con el histórico de posiciones (mapa de calor por celdas).

### D. Inteligencia de fuentes y ciber (puente a CTI)

12. **Monitor de fuentes OSINT de texto** *(alto, medio)*
    RSS/Telegram públicos de medios y organismos → eventos con geocodificación
    por nombre de lugar (ya tenemos 7 342 núcleos NE para resolver topónimos).
13. **Enriquecimiento de dominio/IP** *(medio, medio)*
    WHOIS/RDAP, certificados (crt.sh), ASN — sin clave y en una ficha de grafo.
    Convierte AEGIS en útil también para investigación de desinformación.
14. **Integración MISP/OpenCTI** *(medio, alto)*
    Exportar eventos como objetos STIX 2.1. Es el puente natural a un SOC.

### E. Producto y confianza

15. **Modo sala de operaciones (wall board)** *(medio, bajo)*
    Vista sin menús, tipografía grande, rotación automática entre zonas.
16. **Reproducción histórica («time machine»)** *(alto, alto)*
    Reproducir las últimas 24 h con un deslizador: eventos, aviones, barcos.
    La BD ya guarda `event_time`; para actores hace falta una tabla compacta de
    posiciones (una fila por actor y minuto, podada a 24 h).
17. **Transparencia de fuentes** *(alto, muy bajo)*
    Página pública con latencia, cobertura y tasa de error de cada fuente,
    calculada de `ingest_runs`. Ninguna plataforma comercial lo enseña;
    para una agencia es el argumento de confianza.

---

## 3. Hoja de ruta recomendada

| Fase | Semanas | Entregables |
|---|---|---|
| **1. Analítica** | 1-2 | líneas de tiempo por entidad, puntuación de credibilidad, alertas de anomalía (avión/buque/tren) |
| **2. Investigación** | 3-4 | grafo de vínculos + export GraphML, imagen satelital en el evento, informe diario PDF |
| **3. Evidencia** | 5-6 | casos con cadena de custodia, reproducción histórica 24 h, página de transparencia |
| **4. Cobertura** | 7-8 | vuelos militares, AIS del Estrecho, más GTFS europeos, RSS/Telegram |

Todo con las mismas reglas: **sin claves de pago, sin inventar datos, en
español y por debajo de 128 MB de persistencia**.

---

## 4. Tres funciones que nos harían únicos

1. **Grafo de vínculos abierto sobre datos en vivo** — Maltego es de escritorio
   y sin datos vivos; nosotros lo tendríamos sobre ADS-B/AIS/trenes al minuto.
2. **Credibilidad auditable** — fórmula publicada y verificable en cada evento.
3. **Cadena de custodia con hash** — evidencia citable en un informe, gratis.

Con esas tres, AEGIS deja de ser «otro mapa» y pasa a ser una herramienta de
investigación con la que se puede firmar un informe.

---

### Fuentes consultadas para este informe

- Y2 Blog, *Best OSINT Platforms for Real-Time Global Intelligence (2026)*.
- ransomnews.com, *Best OSINT tools 2026: what analysts actually run*.
- freedom251.com / positioniseverything.net, *Best Maltego Alternatives (2026)*.
- gitnux.org, *Best Intelligence Analyst Software (2026)* (Bellingcat Pro,
  Maltego, Palantir Foundry, Recorded Future, OpenCTI, MISP).
- adriadefense.com, *10 Free OSINT Tools Every Defence Analyst Should Be Using
  (2026)*: Liveuamap, ADS-B Exchange, MarineTraffic, Copernicus Browser.
- lyrasense.com, *Best GEOINT Tools (2026)*: Sentinel Hub, QGIS.
- offnadir-delta.com, *Best OSINT Satellite Imagery Tools (2026)*.
- Medium (@hobin_rood_uk), *OSINT, Mapping software and keeping the Ukrainian
  public informed*: flujo Liveuamap / ISW StoryMap / ACLED.
