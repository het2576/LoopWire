import { auth } from "@/auth";
import { NextResponse } from "next/server";

// Next.js 16 renamed the middleware.ts convention to proxy.ts - same
// runtime behavior, just a different file/export name.
export default auth((req) => {
  const isSignedIn = !!req.auth;
  const isSignInPage = req.nextUrl.pathname === "/signin";

  if (!isSignedIn && !isSignInPage) {
    const signInUrl = new URL("/signin", req.nextUrl.origin);
    return NextResponse.redirect(signInUrl);
  }

  if (isSignedIn && isSignInPage) {
    return NextResponse.redirect(new URL("/", req.nextUrl.origin));
  }
});

export const config = {
  // Everything except NextAuth's own routes and static assets - the sign-in
  // page itself is handled above (redirect logic, not a matcher exclusion),
  // since it still needs the session check to bounce already-signed-in users.
  matcher: ["/((?!api/auth|_next/static|_next/image|favicon.ico).*)"],
};
