import "./globals.css";
import type { ReactNode } from "react";

export const metadata = {
  title: "Imagen Campaign Studio",
  description: "Upload campaign JSON and images, generate ad creatives."
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
