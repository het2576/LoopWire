import type { Metadata } from "next";
import { DM_Sans, Space_Grotesk } from "next/font/google";
import Nav from "@/components/Nav";
import "./globals.css";

const spaceGrotesk = Space_Grotesk({
  variable: "--font-space-grotesk",
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
});

const dmSans = DM_Sans({
  variable: "--font-dm-sans",
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
});

export const metadata: Metadata = {
  title: "Loopwire",
  description: "Your saved links, wired back to you as a Loopwire send.",
};

const themeBootScript = `(() => { try { const saved = localStorage.getItem('loopwire-theme'); const theme = saved === 'dark' || saved === 'light' ? saved : (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'); document.documentElement.dataset.theme = theme; } catch {} })();`;

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning className={`${spaceGrotesk.variable} ${dmSans.variable} h-full antialiased`}>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeBootScript }} />
      </head>
      <body className="min-h-full bg-cloud text-ink">
        <div className="app-shell min-h-screen">
          <Nav />
          <main className="content-frame px-4 pt-7 sm:px-8 sm:pt-14 lg:px-12">
            <div className="mx-auto max-w-[1180px]">{children}</div>
          </main>
        </div>
      </body>
    </html>
  );
}
