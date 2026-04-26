import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Meta-Harness Dashboard",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="h-full overflow-hidden">
      <head>
        <link
          href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600;700&display=swap"
          rel="stylesheet"
        />
      </head>
      <body className="antialiased h-full overflow-hidden">{children}</body>
    </html>
  );
}
