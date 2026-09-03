import { auth } from "@/auth";

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";
const INTERNAL_AUTH_SECRET = process.env.INTERNAL_AUTH_SECRET ?? "";

export type LoopwireItem = {
  item_id: number;
  title: string;
  type: "article" | "youtube" | "reddit" | "github" | "hn" | "pdf" | "unsupported";
  source_url: string;
  read_url: string;
  couldnt_extract: boolean;
  summary: string | null;
  key_takeaway: string | null;
  relevance_note: string | null;
  read_time_minutes: number | null;
};

export type LoopwireSend = {
  id: number;
  period: string;
  sent_at: string;
  item_count: number;
  items: LoopwireItem[];
};

export type LoopwireSendSummary = {
  id: number;
  period: string;
  sent_at: string;
  item_count: number;
};

export type StatsBucket = {
  total_sent: number;
  opened: number;
  clicked_source: number;
  skipped: number;
  engagement_rate: number;
};

export type Stats = Record<string, StatsBucket>;

export type SavedItem = {
  item_id: number;
  title: string;
  url: string;
  type: "article" | "youtube" | "reddit" | "github" | "hn" | "pdf" | "unsupported";
  status: "pending" | "extracted" | "extraction_failed" | "summarized" | "sent";
  extraction_error: string | null;
  added_at: string;
  loopwire_send_id: number | null;
};

export type Me = {
  id: number;
  email: string;
  telegram_chat_id: number | null;
  interest_profile_text: string | null;
};

export type ConnectionCode = {
  code: string;
  expires_in_minutes: number;
};

export type ProfileStatus = {
  engagement_count: number;
  threshold: number;
  is_adaptive: boolean;
};

/** Every backend call authenticates as "this Next.js server, acting on
 * behalf of the currently signed-in user" - see app/auth.py on the backend.
 * Never called from a client component (the secret would leak to the browser). */
async function authHeaders(): Promise<Record<string, string>> {
  const session = await auth();
  if (!session?.user?.id) {
    console.error("[LoopWire API] authHeaders: no session or user id found — user may not be signed in");
    return {};
  }
  if (!INTERNAL_AUTH_SECRET) {
    console.error("[LoopWire API] authHeaders: INTERNAL_AUTH_SECRET env var is not set on this Next.js server");
  }

  return {
    "X-Internal-Secret": INTERNAL_AUTH_SECRET,
    "X-User-Id": String(session.user.id),
  };
}

async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T | null> {
  const url = `${BACKEND_URL}${path}`;
  try {
    const headers = { ...(await authHeaders()), ...(init.headers as Record<string, string>) };
    const res = await fetch(url, { ...init, headers, cache: "no-store" });
    if (!res.ok) {
      let body = "(unreadable)";
      try { body = await res.text(); } catch { /* ignore */ }
      console.error(
        `[LoopWire API] ${init.method ?? "GET"} ${url} → ${res.status} ${res.statusText}\nResponse body: ${body}`
      );
      return null;
    }
    return (await res.json()) as T;
  } catch (err) {
    console.error(`[LoopWire API] ${init.method ?? "GET"} ${url} → network/parse error:`, err);

    return null;
  }
}

export function readUrl(itemId: number): string {
  return `${BACKEND_URL}/r/${itemId}`;
}

export async function markOpened(itemId: number): Promise<void> {
  const headers = await authHeaders();
  fetch(`${BACKEND_URL}/api/items/${itemId}/opened`, { method: "POST", headers, cache: "no-store" }).catch(() => {});
}

export function getLatestLoopwireSend(): Promise<LoopwireSend | null> {
  return apiFetch<LoopwireSend>("/api/loopwire-sends/latest");
}

export function getLoopwireSend(id: number): Promise<LoopwireSend | null> {
  return apiFetch<LoopwireSend>(`/api/loopwire-sends/${id}`);
}

export function listLoopwireSends(): Promise<LoopwireSendSummary[] | null> {
  return apiFetch<LoopwireSendSummary[]>("/api/loopwire-sends");
}

export function getStats(): Promise<Stats | null> {
  return apiFetch<Stats>("/api/stats");
}

export function listItems(status?: string): Promise<SavedItem[] | null> {
  const query = status ? `?status=${encodeURIComponent(status)}` : "";
  return apiFetch<SavedItem[]>(`/api/items${query}`);
}

export function getMe(): Promise<Me | null> {
  return apiFetch<Me>("/api/me");
}

export function getInterestProfile(): Promise<{ profile_text: string | null } | null> {
  return apiFetch("/api/interest-profile");
}

export function updateInterestProfile(profileText: string): Promise<{ profile_text: string | null } | null> {
  return apiFetch("/api/interest-profile", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ profile_text: profileText }),
  });
}

export function createConnectionCode(): Promise<ConnectionCode | null> {
  return apiFetch<ConnectionCode>("/api/connect-code", { method: "POST" });
}

export function getProfileStatus(): Promise<ProfileStatus | null> {
  return apiFetch<ProfileStatus>("/api/profile-status");
}
