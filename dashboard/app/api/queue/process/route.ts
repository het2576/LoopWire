import { auth } from "@/auth";
import { NextResponse } from "next/server";

const BACKEND_URL = (process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000").replace(/\/+$/, "");
const INTERNAL_AUTH_SECRET = process.env.INTERNAL_AUTH_SECRET ?? "";

export async function POST() {
  const session = await auth();
  if (!session?.user?.id) {
    return NextResponse.json({ error: "Sign in again to process your queue." }, { status: 401 });
  }
  if (!INTERNAL_AUTH_SECRET) {
    return NextResponse.json({ error: "The dashboard is missing its backend credential." }, { status: 503 });
  }

  try {
    const response = await fetch(`${BACKEND_URL}/api/items/process`, {
      method: "POST",
      headers: {
        "X-Internal-Secret": INTERNAL_AUTH_SECRET,
        "X-User-Id": String(session.user.id),
      },
      cache: "no-store",
      signal: AbortSignal.timeout(90_000),
    });
    const body = await response.text();
    if (!response.ok) {
      console.error(`[Queue processing] ${response.status} ${response.statusText}: ${body}`);
      return NextResponse.json({ error: "Loopwire could not process the queue. Please try again shortly." }, { status: response.status });
    }

    return new NextResponse(body, {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  } catch (error) {
    console.error("[Queue processing] request failed:", error);
    return NextResponse.json({ error: "Processing took too long. Please try again shortly." }, { status: 504 });
  }
}
