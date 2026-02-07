import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "DEEPSTACK TRADER v2.0",
  description: "Real-time trading dashboard for Kalshi multi-strategy bot",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className="bg-terminal-black text-terminal-green font-mono antialiased">
        {children}
      </body>
    </html>
  );
}
