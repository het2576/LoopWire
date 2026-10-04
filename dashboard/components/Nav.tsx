import Link from "next/link";
import { auth, signOut } from "@/auth";
import NavLinks from "@/components/NavLinks";
import ThemeToggle from "@/components/ThemeToggle";

export default async function Nav() {
  const session = await auth();

  return (
    <header className="app-header sticky top-0 z-40 h-[68px] sm:h-[76px]">
      <div className="mx-auto flex h-full max-w-[1280px] items-center justify-between px-4 sm:px-8 lg:px-12">
        <Link
          href="/"
          className="brand-mark"
        >
          <span className="brand-orbit" aria-hidden />
          Loopwire
        </Link>

        {session?.user ? (<>
          <div className="hidden sm:block"><NavLinks /></div>
          <div className="flex items-center gap-4">
            <ThemeToggle />
            <span className="hidden items-center gap-2 font-display text-[12px] font-semibold text-ok sm:flex"><span className="signal-dot h-2 w-2 rounded-full bg-ok" /> Synced</span>
            <form
              action={async () => {
                "use server";
                await signOut({ redirectTo: "/signin" });
              }}
            >
              <button type="submit" className="hidden font-display text-[12px] font-semibold text-wire transition-colors hover:text-alert sm:block">
                Sign out
              </button>
            </form>
          </div>
          <div className="sm:hidden"><NavLinks /></div>
        </>) : <div className="flex items-center gap-3"><span className="hidden font-display text-sm font-medium text-wire sm:block">Your personal reading space</span><ThemeToggle /></div>}
      </div>
    </header>
  );
}
