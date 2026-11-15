"use server";

import { auth } from "@/auth";
import { apiFetch, type RecallReviewResult, type RecallVerdict } from "@/lib/api";

// Server Functions are reachable by direct POST, so each one re-checks the
// session (the backend additionally scopes every call to this user id).
async function requireUser() {
  const session = await auth();
  if (!session?.user?.id) throw new Error("Unauthorized");
}

export async function submitFeedback(itemId: number, vote: "up" | "down"): Promise<boolean> {
  await requireUser();
  const res = await apiFetch<{ ok: boolean }>(`/api/items/${itemId}/feedback`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ vote }),
  });
  return !!res?.ok;
}

export async function reviewRecall(
  cardId: number,
  input: { answer: string } | { self_verdict: RecallVerdict },
): Promise<RecallReviewResult | null> {
  await requireUser();
  return apiFetch<RecallReviewResult>(`/api/recall/${cardId}/review`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
}
