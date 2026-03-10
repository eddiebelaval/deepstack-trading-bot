import type { Metadata } from "next";
import Nav from "@/components/Nav";
import "./globals.css";

export const metadata: Metadata = {
  title: "DAE — DeepStack Autonomous Engine",
  description: "Real-time trading dashboard for Kalshi multi-strategy bot",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className="bg-terminal-bg text-terminal-green font-mono antialiased">
        <div className="flex flex-col h-screen overflow-hidden">
          <Nav />
          <main className="flex-1 overflow-auto">
            {children}
          </main>
        </div>
      </body>
    </html>
  );
}
