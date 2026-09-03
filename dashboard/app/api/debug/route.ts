import { auth } from "@/auth";
import { NextResponse } from "next/server";

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";
const INTERNAL_AUTH_SECRET = process.env.INTERNAL_AUTH_SECRET ?? "";

export async function GET() {
  const session = await auth();

  // Check 1: Environment variables
  const envCheck = {
    NEXT_PUBLIC_BACKEND_URL: BACKEND_URL,
    INTERNAL_AUTH_SECRET_SET: !!INTERNAL_AUTH_SECRET && INTERNAL_AUTH_SECRET.length > 0,
    INTERNAL_AUTH_SECRET_LENGTH: INTERNAL_AUTH_SECRET.length,
    AUTH_SECRET_SET: !!(process.env.AUTH_SECRET || process.env.NEXTAUTH_SECRET),
  };

  // Check 2: Session
  const sessionCheck = {
    isSignedIn: !!session?.user?.id,
    userId: session?.user?.id ?? null,
    email: session?.user?.email ?? null,
  };

  // Check 3: Backend reachability
  let backendHealth: { reachable: boolean; status?: number; body?: unknown; error?: string } = { reachable: false };
  try {
    const res = await fetch(`${BACKEND_URL}/health`, { cache: "no-store" });
    let body: unknown = null;
    try { body = await res.json(); } catch { /* ignore */ }
    backendHealth = { reachable: res.ok, status: res.status, body };
  } catch (err) {
    backendHealth = { reachable: false, error: String(err) };
  }

  // Check 4: Test the connect-code endpoint (if signed in)
  let connectCodeCheck: { attempted: boolean; status?: number; body?: string; error?: string } = { attempted: false };
  if (session?.user?.id && INTERNAL_AUTH_SECRET) {
    connectCodeCheck = { attempted: true };
    try {
      const res = await fetch(`${BACKEND_URL}/api/connect-code`, {
        method: "POST",
        headers: {
          "X-Internal-Secret": INTERNAL_AUTH_SECRET,
          "X-User-Id": String(session.user.id),
        },
        cache: "no-store",
      });
      let body = "(unreadable)";
      try { body = await res.text(); } catch { /* ignore */ }
      connectCodeCheck = { attempted: true, status: res.status, body };
    } catch (err) {
      connectCodeCheck = { attempted: true, error: String(err) };
    }
  }

  return NextResponse.json({
    env: envCheck,
    session: sessionCheck,
    backendHealth,
    connectCodeCheck,
    timestamp: new Date().toISOString(),
  });
}
