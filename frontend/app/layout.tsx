import type { Metadata, Viewport } from "next";
import localFont from "next/font/local";
import "./globals.css";

// Tipografía de interfaz densa: Inter para texto y JetBrains Mono para datos.
// Los woff2 viven en `app/fonts` (subset latino, OFL): el build no depende de
// Google, así que CI y Pages compilan igual sin red hacia fonts.googleapis.com.
const inter = localFont({
  src: [
    { path: "./fonts/inter-latin-400-normal.woff2", weight: "400", style: "normal" },
    { path: "./fonts/inter-latin-500-normal.woff2", weight: "500", style: "normal" },
    { path: "./fonts/inter-latin-600-normal.woff2", weight: "600", style: "normal" },
    { path: "./fonts/inter-latin-700-normal.woff2", weight: "700", style: "normal" },
  ],
  variable: "--font-sans",
  display: "swap",
  fallback: ["system-ui", "-apple-system", "Segoe UI", "Roboto", "Arial", "sans-serif"],
});
const mono = localFont({
  src: [
    { path: "./fonts/jetbrains-mono-latin-400-normal.woff2", weight: "400", style: "normal" },
    { path: "./fonts/jetbrains-mono-latin-600-normal.woff2", weight: "600", style: "normal" },
  ],
  variable: "--font-mono",
  display: "swap",
  fallback: ["ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "monospace"],
});

// GitHub Pages sirve el sitio en /<repo>/: manifest e iconos tienen que colgar
// de ese prefijo o el navegador pide /manifest.webmanifest y recibe un 404.
const BASE_PATH = process.env.NEXT_PUBLIC_BASE_PATH || "";
const asset = (path: string) => `${BASE_PATH}${path}`;

export const metadata: Metadata = {
  title: "AEGIS · OSINT Super App",
  description:
    "Telemetría global en tiempo real, inteligencia geopolítica y desastres naturales sobre un globo 3D.",
  manifest: asset("/manifest.webmanifest"),
  applicationName: "AEGIS",
  appleWebApp: { capable: true, title: "AEGIS", statusBarStyle: "black-translucent" },
  icons: { icon: [{ url: asset("/icon.svg"), type: "image/svg+xml" }], apple: asset("/icon.svg") },
};

export const viewport: Viewport = {
  themeColor: "#070b11",
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="es" className={`${inter.variable} ${mono.variable}`}>
      <body>{children}</body>
    </html>
  );
}
