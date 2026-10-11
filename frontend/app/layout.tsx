import type { Metadata, Viewport } from "next";
import "./globals.css";
import Providers from "./providers";
import { PRODUCT } from "@/lib/brand";

export const metadata: Metadata = {
  title: PRODUCT.name,
  description: "Multi-tenant legal practice management: files, AI research, drafting, billing.",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
