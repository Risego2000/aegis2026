import type { Metadata, Viewport } from "next";
import "./globals.css";

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
  themeColor: "#04070d",
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="es">
      <body>{children}</body>
    </html>
  );
}
