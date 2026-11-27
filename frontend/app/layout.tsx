import type { Metadata, Viewport } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "AEGIS · OSINT Super App",
  description:
    "Telemetría global en tiempo real, inteligencia geopolítica y desastres naturales sobre un globo 3D.",
  manifest: "/manifest.webmanifest",
  applicationName: "AEGIS",
  appleWebApp: { capable: true, title: "AEGIS", statusBarStyle: "black-translucent" },
  icons: { icon: [{ url: "/icon.svg", type: "image/svg+xml" }], apple: "/icon.svg" },
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
