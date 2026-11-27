/** @type {import('next').NextConfig} */
const isDev = process.env.NODE_ENV !== "production";

const nextConfig = {
  // Production: static export -> FastAPI serves frontend/out from the same
  // origin as /api and /ws (single port, no CORS, no Node runtime).
  ...(isDev ? {} : { output: "export" }),
  images: { unoptimized: true },
  reactStrictMode: true,
  trailingSlash: false,
  // GitHub Pages sirve el sitio en /<repo>/, así que las rutas de los assets
  // necesitan ese prefijo. Sin la variable (backend propio, raíz del dominio)
  // no hay prefijo y todo sigue igual.
  basePath: process.env.NEXT_BASE_PATH || "",
  assetPrefix: process.env.NEXT_BASE_PATH || "",
  // El prefijo se incrusta también en el código del cliente: manifest, icono,
  // service worker y `runtime-config.json` cuelgan de él, no de la raíz.
  env: { NEXT_PUBLIC_BASE_PATH: process.env.NEXT_BASE_PATH || "" },
  eslint: { ignoreDuringBuilds: true },
  // Los tipos se comprueban aparte con `./node_modules/.bin/tsc --noEmit`
  // (dentro de `make check`): el paso de tipos del build lanza un worker que el
  // entorno de 2 GB mata por falta de memoria, así que aquí no se duplica.
  typescript: { ignoreBuildErrors: true },
  // Dev-only proxy so `next dev` can talk to the FastAPI backend.
  async rewrites() {
    if (!isDev) return [];
    return [
      { source: "/api/:path*", destination: "http://127.0.0.1:8000/api/:path*" },
      { source: "/ws/:path*", destination: "http://127.0.0.1:8000/ws/:path*" },
    ];
  },
};

export default nextConfig;
