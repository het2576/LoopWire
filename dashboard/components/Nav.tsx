import Link from "next/link";
import { auth, signOut } from "@/auth";

const LINKS = [
  { href: "/", label: "Latest" },
  { href: "/wire", label: "Wire" },
  { href: "/log", label: "Log" },
  { href: "/signal", label: "Signal" },
  { href: "/settings", label: "Settings" },
];

export default async function Nav() {
  const session = await auth();

  return (
    <header className="sticky top-0 z-20 border-b border-white/10 bg-ink-raised/90 backdrop-blur">
      <div className="mx-auto flex max-w-2xl items-center justify-between px-5 py-4 sm:px-8">
        <Link
          href="/"
          className="flex items-center gap-2 font-mono text-sm font-bold tracking-[0.2em] text-paper"
        >
          <span className="signal-dot inline-block h-1.5 w-1.5 rounded-full bg-ok" aria-hidden />
          LOOPWIRE
        </Link>

        {session?.user && (
          <nav className="flex items-center gap-5 font-mono text-xs tracking-[0.15em] text-wire">
            {LINKS.map((link) => (
              <Link key={link.href} href={link.href} className="transition-colors hover:text-signal">
                {link.label.toUpperCase()}
              </Link>
            ))}
            <form
              action={async () => {
                "use server";
                await signOut({ redirectTo: "/signin" });
              }}
            >
              <button type="submit" className="transition-colors hover:text-alert">
                SIGN OUT
              </button>
            </form>
          </nav>
        )}
      </div>
    </header>
  );
}
