/**
 * Iconos característicos del mapa, dibujados a mano en canvas.
 *
 * No se usan imágenes externas ni emoji: cada categoría de suceso y cada tipo
 * de elemento tiene su propia silueta, de modo que se distinguen de un vistazo
 * sin leer. Todos son SDF (`sdf: true` en MapLibre), así que el color lo pone
 * la capa y el icono se ve nítido a cualquier zoom.
 *
 * Coordenadas en un lienzo de 24×24 con origen arriba a la izquierda.
 */

type Ctx = CanvasRenderingContext2D;

const SIZE = 24;

function makeCanvas(draw: (g: Ctx) => void, size = SIZE): ImageData {
  const cv = document.createElement("canvas");
  cv.width = size;
  cv.height = size;
  const g = cv.getContext("2d")!;
  g.clearRect(0, 0, size, size);
  // Un contorno blanco alrededor del icono ayuda a que se lea sobre el mapa
  // oscuro; el relleno es la única parte que MapLibre recolorea en modo SDF
  // (el SDF trabaja con la cobertura alfa, así que dibujamos en blanco).
  g.strokeStyle = "rgba(255,255,255,0.28)";
  g.lineWidth = 2.6;
  g.lineJoin = "round";
  draw(g);
  g.stroke();
  g.fillStyle = "#ffffff";
  g.strokeStyle = "#ffffff";
  g.lineWidth = 1.5;
  draw(g);
  g.fill();
  return g.getImageData(0, 0, size, size);
}

const PI = Math.PI;

/** Avión comercial: fuselaje con alas en flecha y estabilizador. */
function drawPlane(g: Ctx) {
  g.beginPath();
  g.moveTo(12, 1.6);
  g.lineTo(14, 6.4);
  g.lineTo(14, 9.6);
  g.lineTo(22.4, 15);
  g.lineTo(22.4, 17);
  g.lineTo(14, 13.6);
  g.lineTo(14, 18.4);
  g.lineTo(16.6, 20.6);
  g.lineTo(16.6, 22.2);
  g.lineTo(12, 21);
  g.lineTo(7.4, 22.2);
  g.lineTo(7.4, 20.6);
  g.lineTo(10, 18.4);
  g.lineTo(10, 13.6);
  g.lineTo(1.6, 17);
  g.lineTo(1.6, 15);
  g.lineTo(10, 9.6);
  g.lineTo(10, 6.4);
  g.closePath();
}

/** Avión militar: ala delta y morro afilado (silueta de caza). */
function drawMilitaryPlane(g: Ctx) {
  g.beginPath();
  g.moveTo(12, 1.4);
  g.lineTo(13.6, 7);
  g.lineTo(22.8, 17.4);
  g.lineTo(22.8, 19.4);
  g.lineTo(13.6, 15.2);
  g.lineTo(13.4, 19);
  g.lineTo(16.4, 21.6);
  g.lineTo(16.4, 22.8);
  g.lineTo(12, 21.6);
  g.lineTo(7.6, 22.8);
  g.lineTo(7.6, 21.6);
  g.lineTo(10.6, 19);
  g.lineTo(10.4, 15.2);
  g.lineTo(1.2, 19.4);
  g.lineTo(1.2, 17.4);
  g.lineTo(10.4, 7);
  g.closePath();
}

/** Avión oficial / Estado: ala recta y doble motor (claramente distinto). */
function drawStatePlane(g: Ctx) {
  g.beginPath();
  g.moveTo(12, 2);
  g.lineTo(13.4, 7);
  g.lineTo(22.6, 11.4);
  g.lineTo(22.6, 13.4);
  g.lineTo(13.4, 12.4);
  g.lineTo(13.4, 17.6);
  g.lineTo(16.2, 20.2);
  g.lineTo(16.2, 21.8);
  g.lineTo(12, 20.6);
  g.lineTo(7.8, 21.8);
  g.lineTo(7.8, 20.2);
  g.lineTo(10.6, 17.6);
  g.lineTo(10.6, 12.4);
  g.lineTo(1.4, 13.4);
  g.lineTo(1.4, 11.4);
  g.lineTo(10.6, 7);
  g.closePath();
}

/** Helicóptero: cabina + rotor principal + patín. */
function drawHeli(g: Ctx) {
  g.beginPath();
  g.ellipse(12, 14, 5.2, 4.2, 0, 0, 2 * PI);
  g.moveTo(6.8, 14);
  g.lineTo(1.2, 14);
  g.lineTo(1.2, 15.6);
  g.lineTo(6.8, 15.6);
  g.closePath();
  g.rect(3, 3.4, 18, 1.8);
  g.rect(11.2, 4.6, 1.6, 5.6);
  g.rect(8.6, 18, 7, 1.6);
}

/** Buque: casco con proa y dos palos. */
function drawShip(g: Ctx) {
  g.beginPath();
  g.moveTo(2, 13);
  g.lineTo(22, 13);
  g.lineTo(18.6, 19.6);
  g.lineTo(5.4, 19.6);
  g.closePath();
  g.rect(11, 4, 2.2, 9);
  g.rect(4.6, 7, 1.6, 6);
  g.rect(17.8, 7, 1.6, 6);
}

/** Satélite: cuerpo central, paneles solares y antena. */
function drawSatellite(g: Ctx) {
  g.beginPath();
  g.rect(9.4, 9.4, 5.2, 5.2);
  g.rect(1.4, 10.2, 6.4, 3.6);
  g.rect(16.2, 10.2, 6.4, 3.6);
  g.moveTo(12, 9.2);
  g.lineTo(12, 5.6);
  g.lineTo(9.4, 2.4);
  g.lineTo(10.8, 1.6);
  g.lineTo(12.9, 4.4);
  g.lineTo(15, 1.6);
  g.lineTo(16.4, 2.4);
  g.lineTo(13.8, 5.6);
  g.lineTo(13.8, 9.2);
  g.closePath();
}

/** Tren: locomotora con ventanas y ruedas. */
function drawTrain(g: Ctx) {
  g.beginPath();
  g.moveTo(4, 5);
  g.lineTo(20, 5);
  g.lineTo(21.6, 9);
  g.lineTo(21.6, 17);
  g.lineTo(2.4, 17);
  g.lineTo(2.4, 9);
  g.closePath();
  g.rect(5.2, 7.2, 4.4, 3.6);
  g.rect(14.4, 7.2, 4.4, 3.6);
  g.arc(7.2, 18.4, 1.9, 0, 2 * PI);
  g.arc(16.8, 18.4, 1.9, 0, 2 * PI);
}

/** Metro / cercanías: tren redondeado, distinto del de larga distancia. */
function drawMetro(g: Ctx) {
  g.beginPath();
  g.moveTo(12, 3.2);
  g.arc(12, 10.4, 7.2, PI * 1.15, PI * 1.85);
  g.lineTo(19.2, 16.4);
  g.lineTo(4.8, 16.4);
  g.closePath();
  g.rect(6.4, 19.2, 3.4, 1.8);
  g.rect(14.2, 19.2, 3.4, 1.8);
  g.rect(5.6, 8.6, 3.6, 3.2);
  g.rect(14.8, 8.6, 3.6, 3.2);
}

/** Cámara de tráfico: caja con objetivo y soporte. */
function drawCamera(g: Ctx) {
  g.beginPath();
  g.rect(3.4, 6.6, 13.6, 9);
  g.moveTo(17, 9.2);
  g.lineTo(21.4, 7);
  g.lineTo(21.4, 15.2);
  g.lineTo(17, 13);
  g.closePath();
  g.rect(8.4, 15.6, 2.4, 5.4);
  g.rect(5.4, 20.6, 8.4, 1.8);
}

/* ------------------------------------------------------------------ */
/* Sucesos: un icono por categoría                                     */
/* ------------------------------------------------------------------ */

/** Terremoto: epicentro con ondas concéntricas y grieta. */
function drawEarthquake(g: Ctx) {
  g.beginPath();
  g.moveTo(12, 1.8);
  g.lineTo(14.4, 8.4);
  g.lineTo(19.4, 4.6);
  g.lineTo(17.6, 10.4);
  g.lineTo(22.4, 10.6);
  g.lineTo(18.2, 13.8);
  g.lineTo(20.8, 17.4);
  g.lineTo(15, 15.6);
  g.lineTo(16.6, 22.2);
  g.lineTo(12, 17.6);
  g.lineTo(7.4, 22.2);
  g.lineTo(9, 15.6);
  g.lineTo(3.2, 17.4);
  g.lineTo(5.8, 13.8);
  g.lineTo(1.6, 10.6);
  g.lineTo(6.4, 10.4);
  g.lineTo(4.6, 4.6);
  g.lineTo(9.6, 8.4);
  g.closePath();
}

/** Desastre natural: ciclón (espiral de dos brazos). */
function drawCyclone(g: Ctx) {
  g.beginPath();
  g.arc(12, 12, 2.6, 0, 2 * PI);
  g.moveTo(12, 4.6);
  g.bezierCurveTo(18.4, 4.6, 21.4, 9.4, 21.4, 12);
  g.bezierCurveTo(21.4, 15.6, 18, 18.4, 14.4, 18.4);
  g.bezierCurveTo(11.4, 18.4, 9.4, 16.2, 9.4, 14);
  g.lineTo(11.6, 14);
  g.bezierCurveTo(11.6, 15.2, 12.6, 16.2, 14.2, 16.2);
  g.bezierCurveTo(16.4, 16.2, 19, 14.6, 19, 12);
  g.bezierCurveTo(19, 10.2, 17, 6.9, 12, 6.9);
  g.closePath();
  g.moveTo(12, 19.4);
  g.bezierCurveTo(5.6, 19.4, 2.6, 14.6, 2.6, 12);
  g.bezierCurveTo(2.6, 8.4, 6, 5.6, 9.6, 5.6);
  g.bezierCurveTo(12.6, 5.6, 14.6, 7.8, 14.6, 10);
  g.lineTo(12.4, 10);
  g.bezierCurveTo(12.4, 8.8, 11.4, 7.8, 9.8, 7.8);
  g.bezierCurveTo(7.6, 7.8, 5, 9.4, 5, 12);
  g.bezierCurveTo(5, 13.8, 7, 17.1, 12, 17.1);
  g.closePath();
}

/** Incendio: llama. */
function drawFire(g: Ctx) {
  g.beginPath();
  g.moveTo(12, 1.6);
  g.bezierCurveTo(13.6, 6, 18.4, 8.2, 18.4, 14);
  g.bezierCurveTo(18.4, 18.8, 15.4, 22, 12, 22);
  g.bezierCurveTo(8.6, 22, 5.6, 18.8, 5.6, 14);
  g.bezierCurveTo(5.6, 10.4, 8.2, 9, 9.2, 5.4);
  g.bezierCurveTo(10.2, 7.4, 10.8, 9.2, 10.8, 10.8);
  g.bezierCurveTo(11.8, 9.4, 12.4, 6, 12, 1.6);
  g.closePath();
}

/** Conflicto: explosión de ocho puntas con núcleo. */
function drawConflict(g: Ctx) {
  g.beginPath();
  for (let i = 0; i < 16; i++) {
    const a = (i / 16) * 2 * PI - PI / 2;
    const r = i % 2 === 0 ? 11 : 4.2;
    const x = 12 + Math.cos(a) * r;
    const y = 12 + Math.sin(a) * r;
    if (i === 0) g.moveTo(x, y);
    else g.lineTo(x, y);
  }
  g.closePath();
}

/** Protesta: silueta de multitud con pancarta. */
function drawProtest(g: Ctx) {
  g.beginPath();
  g.rect(4, 3, 16, 7);
  g.rect(11.2, 10, 1.6, 12.4);
  g.arc(7.4, 14.6, 2.2, 0, 2 * PI);
  g.arc(12, 13.8, 2.4, 0, 2 * PI);
  g.arc(16.6, 14.6, 2.2, 0, 2 * PI);
  g.rect(5.6, 17.4, 3.6, 3.4);
  g.rect(10.2, 16.6, 3.6, 4.2);
  g.rect(14.8, 17.4, 3.6, 3.4);
}

/** Militar (suceso): estrella de cinco puntas con aro. */
function drawMilitary(g: Ctx) {
  g.beginPath();
  for (let i = 0; i < 10; i++) {
    const a = (i / 10) * 2 * PI - PI / 2;
    const r = i % 2 === 0 ? 10.4 : 4.4;
    const x = 12 + Math.cos(a) * r;
    const y = 12.6 + Math.sin(a) * r;
    if (i === 0) g.moveTo(x, y);
    else g.lineTo(x, y);
  }
  g.closePath();
}

/** Diplomacia: dos banderas cruzadas simplificadas. */
function drawDiplomacy(g: Ctx) {
  g.beginPath();
  g.rect(5.2, 2.4, 1.6, 19.2);
  g.rect(17.2, 2.4, 1.6, 19.2);
  g.moveTo(6.8, 4);
  g.lineTo(13.6, 4);
  g.lineTo(12, 7.6);
  g.lineTo(6.8, 7.6);
  g.closePath();
  g.moveTo(17.2, 4);
  g.lineTo(10.4, 4);
  g.lineTo(12, 7.6);
  g.lineTo(17.2, 7.6);
  g.closePath();
}

/** Economía: barras ascendentes. */
function drawEconomy(g: Ctx) {
  g.beginPath();
  g.rect(2.6, 14, 4.6, 7.4);
  g.rect(9.7, 9.4, 4.6, 12);
  g.rect(16.8, 3.6, 4.6, 17.8);
}

/** Suceso de interés general (noticias): «!» dentro de un rombo. */
function drawNews(g: Ctx) {
  g.beginPath();
  g.moveTo(12, 1.6);
  g.lineTo(22.4, 12);
  g.lineTo(12, 22.4);
  g.lineTo(1.6, 12);
  g.closePath();
}

/** Tráfico: cono de obra. */
function drawTraffic(g: Ctx) {
  g.beginPath();
  g.moveTo(12, 2.6);
  g.lineTo(18.6, 19.4);
  g.lineTo(5.4, 19.4);
  g.closePath();
  g.rect(3.4, 20.2, 17.2, 1.9);
}

/** Otros / transporte: maleta con asa. */
function drawGeneric(g: Ctx) {
  g.beginPath();
  g.rect(2.8, 7.4, 18.4, 12.6);
  g.rect(8.6, 3.6, 6.8, 3.8);
}

/** Punto genérico (marcador) para lo que no tenga icono propio. */
function drawPin(g: Ctx) {
  g.beginPath();
  g.arc(12, 9, 5.6, 0, 2 * PI);
  g.moveTo(8.2, 13.2);
  g.lineTo(12, 22.4);
  g.lineTo(15.8, 13.2);
  g.closePath();
}

const DRAWERS: Record<string, (g: Ctx) => void> = {
  plane: drawPlane,
  milPlane: drawMilitaryPlane,
  statePlane: drawStatePlane,
  heli: drawHeli,
  ship: drawShip,
  sat: drawSatellite,
  train: drawTrain,
  metro: drawMetro,
  cam: drawCamera,
  earthquake: drawEarthquake,
  cyclone: drawCyclone,
  fire: drawFire,
  conflict: drawConflict,
  protest: drawProtest,
  military: drawMilitary,
  diplomacy: drawDiplomacy,
  economy: drawEconomy,
  news: drawNews,
  traffic: drawTraffic,
  generic: drawGeneric,
  pin: drawPin,
};

/** Devuelve el ImageData listo para `map.addImage(nombre, data, { sdf: true })`. */
export function categoryIconData(name: string): ImageData {
  const draw = DRAWERS[name] || DRAWERS.pin;
  return makeCanvas(draw);
}

/** Nombre de icono de un suceso a partir de su categoría. */
export function iconForCategory(cat?: string | null): string {
  switch ((cat || "").toLowerCase()) {
    case "earthquake": return "earthquake";
    case "disaster": return "cyclone";
    case "wildfire": return "fire";
    case "conflict": return "conflict";
    case "protest": return "protest";
    case "military": return "military";
    case "diplomacy": return "diplomacy";
    case "economy": return "economy";
    case "traffic":
    case "trafico": return "traffic";
    case "transport":
    case "transporte": return "train";
    case "news": return "news";
    default: return "news";
  }
}
