// Materializa la URL pública de la API en runtime-config.json antes del build.
//
// En GitHub Pages no hay backend en el mismo origen: el cliente lee este fichero
// al arrancar. El workflow AEGIS · Pages lo ejecuta con AEGIS_API (variable del
// repositorio o input manual) para que el sitio publicado tenga una URL de API.
// Si esa API está caída, el cliente se publica y muestra el aviso de desconexión.
// En local no se ejecuta: el fichero vacío significa "mismo origen".

import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const target = process.env.RUNTIME_CONFIG_PATH || join(root, "public", "runtime-config.json");
const raw = (process.env.AEGIS_API || "").trim();

function fail(message) {
  console.error(`runtime-config: ${message}`);
  process.exit(1);
}

if (!raw) {
  fail(
    "falta AEGIS_API. Configura Settings → Secrets and variables → Actions → Variables → AEGIS_API " +
      "o lanza el workflow AEGIS · Pages con el input api_url.",
  );
}

let parsed;
try {
  parsed = new URL(raw);
} catch {
  fail(`AEGIS_API no es una URL válida: ${raw}`);
}

if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
  fail(`AEGIS_API debe usar http o https: ${raw}`);
}
if (!parsed.hostname) {
  fail(`AEGIS_API no tiene host: ${raw}`);
}

// Igual que sanitize() en lib/api.ts: origen + ruta, sin barra final.
const api = `${parsed.origin}${parsed.pathname}`.replace(/\/+$/, "");
if (!api) fail(`AEGIS_API no produce un origen utilizable: ${raw}`);

let config;
try {
  config = JSON.parse(readFileSync(target, "utf8"));
} catch (error) {
  fail(`no se pudo leer ${target}: ${error instanceof Error ? error.message : error}`);
}

writeFileSync(target, `${JSON.stringify({ ...config, api }, null, 2)}\n`, "utf8");
console.log(`runtime-config: api=${api} → ${target}`);
