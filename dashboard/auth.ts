import NextAuth from "next-auth";
import Google from "next-auth/providers/google";
import type { JWT } from "next-auth/jwt";

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";
const INTERNAL_AUTH_SECRET = process.env.INTERNAL_AUTH_SECRET ?? "";

// Module augmentation of next-auth's subpath exports (`next-auth/jwt`,
// `@auth/core/types`) doesn't reliably merge under this project's
// `moduleResolution: "bundler"` - a local intersection type sidesteps that
// entirely instead of fighting it.
type LoopwireToken = JWT & { loopwireUserId?: string };

/** Creates (or fetches) the Postgres user row on first sign-in and returns
 * our own user id (as a string, matching NextAuth's own User.id convention)
 * - session.user.id is always *our* id, never Google's `sub`, so the rest
 * of the app never has to think about Google. */
async function upsertUser(email: string, googleId: string): Promise<string | null> {
  try {
    const res = await fetch(`${BACKEND_URL}/api/auth/upsert-user`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Internal-Secret": INTERNAL_AUTH_SECRET,
      },
      body: JSON.stringify({ email, google_id: googleId }),
      cache: "no-store",
    });
    if (!res.ok) return null;
    const data = await res.json();
    return String(data.id);
  } catch {
    return null;
  }
}

export const { handlers, signIn, signOut, auth } = NextAuth({
  providers: [Google],
  session: { strategy: "jwt" },
  pages: {
    signIn: "/signin",
  },
  callbacks: {
    async jwt({ token, account, profile }) {
      const t = token as LoopwireToken;
      // account/profile are only present on the initial sign-in request,
      // not on subsequent token refreshes - upsert exactly once per login.
      if (account && profile?.sub && t.email) {
        const userId = await upsertUser(t.email, profile.sub);
        if (userId !== null) {
          t.loopwireUserId = userId;
        }
      }
      return t;
    },
    async session({ session, token }) {
      const t = token as LoopwireToken;
      // session.user's static type is a big intersection covering both the
      // "jwt" and "database" session strategies - this app only ever uses
      // "jwt" (configured above), so a cast here is safe.
      if (t.loopwireUserId && session.user) {
        (session.user as { id?: string }).id = t.loopwireUserId;
      }
      return session;
    },
  },
});
