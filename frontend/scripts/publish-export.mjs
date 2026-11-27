// `next build` con output:"export" escribe en ./out, un directorio que muchos
// artefactos/snapshots ignoran por convención. Mantenemos una copia en ./site
// para que el servidor estático siga funcionando aunque out/ no se conserve.
import { cpSync, existsSync, rmSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const src = join(root, "out");
const dst = join(root, "site");

if (!existsSync(src)) {
  console.error("publish-export: no existe out/, ¿falló el build?");
  process.exit(1);
}
rmSync(dst, { recursive: true, force: true });
cpSync(src, dst, { recursive: true });
console.log(`publish-export: out/ -> site/ (${dst})`);
