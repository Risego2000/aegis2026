/** @type {import('next').NextConfig} */
const isDev = process.env.NODE_ENV !== "production";

const nextConfig = {
  // Production: static export -> FastAPI serves frontend/out from the same
  // origin as /api and /ws (single port, no CORS, no Node runtime).
  ...(isDev ? {} : { output: "export" }),
  images: { unoptimized: true },
  reactStrictMode: true,
  trailingSlash: false,
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
