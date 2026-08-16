import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

export const metadata: Metadata = {
  title: "Meta-Harness Dashboard",
  description: "Mission control for autonomous harness evolution",
};

const sans = Geist({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-geist-sans",
});

const mono = Geist_Mono({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-geist-mono",
});

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${sans.variable} ${mono.variable} h-full overflow-hidden`}>
      <body className="antialiased h-full overflow-hidden bg-void text-ink">
        <div className="atmosphere" aria-hidden="true" />
        <div className="relative z-10 h-full">{children}</div>
      </body>
    </html>
  );
}
