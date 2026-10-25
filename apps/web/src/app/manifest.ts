import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "Chobra",
    short_name: "Chobra",
    description: "Испытание правил мотивации в исполняемых средах с ИИ участниками",
    start_url: "/",
    display: "standalone",
    background_color: "#070511",
    theme_color: "#070511",
    lang: "ru",
    icons: [
      { src: "/brand/chobra-192.png", sizes: "192x192", type: "image/png" },
      { src: "/brand/chobra-512.png", sizes: "512x512", type: "image/png" },
      { src: "/brand/chobra-maskable-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
    ],
  };
}
