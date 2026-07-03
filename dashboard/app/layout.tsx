import type { Metadata } from "next";
import { IBM_Plex_Mono, IBM_Plex_Sans } from "next/font/google";
import Nav from "@/components/Nav";
import "./globals.css";

const plexMono = IBM_Plex_Mono({
  variable: "--font-plex-mono",
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
});

const plexSans = IBM_Plex_Sans({
  variable: "--font-plex-sans",
  subsets: ["latin"],
  weight: ["400", "500", "600"],
});

export const metadata: Metadata = {
  title: "Loopwire",
  description: "Your saved links, wired back to you as a Loopwire send.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={`${plexMono.variable} ${plexSans.variable} h-full antialiased`}>
      <body className="min-h-full flex flex-col bg-ink text-paper">
        <Nav />
        <main className="mx-auto w-full max-w-2xl flex-1 px-5 py-10 sm:px-8">{children}</main>
        <footer className="mx-auto w-full max-w-2xl px-5 pb-10 font-mono text-[11px] tracking-widest text-wire/70 sm:px-8">
          END OF TRANSMISSION
        </footer>
      </body>
    </html>
  );
}
