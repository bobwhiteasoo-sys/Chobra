import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";

import { Providers } from "@/components/Providers";

import "@/styles/globals.css";

export const metadata: Metadata = {
  title: { default: "Chobra", template: "%s · Chobra" },
  description: "Испытание правил мотивации в исполняемых средах с ИИ участниками",
  applicationName: "Chobra",
  manifest: "/manifest.webmanifest",
};

export const viewport: Viewport = { themeColor: "#070511", colorScheme: "dark", width: "device-width", initialScale: 1, viewportFit: "cover" };

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="ru">
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
