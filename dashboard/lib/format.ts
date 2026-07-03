export function formatDispatchTimestamp(iso: string): string {
  const d = new Date(iso);
  const day = d.getUTCDate().toString().padStart(2, "0");
  const month = d.toLocaleString("en-US", { month: "short", timeZone: "UTC" }).toUpperCase();
  const year = d.getUTCFullYear();
  const hh = d.getUTCHours().toString().padStart(2, "0");
  const mm = d.getUTCMinutes().toString().padStart(2, "0");
  return `${day} ${month} ${year}, ${hh}:${mm}Z`;
}

export function dispatchNumber(id: number): string {
  // № falls back to system font in IBM Plex Mono — use "No." instead so the
  // entire heading stays in the loaded monospace face.
  return `No.${id.toString().padStart(3, "0")}`;
}

export const TYPE_LABEL: Record<string, string> = {
  article: "Article",
  youtube: "YouTube",
  reddit: "Reddit",
  github: "GitHub",
  hn: "Hacker News",
  pdf: "PDF",
  unsupported: "Link",
};

export function relativeTime(iso: string): string {
  const diffMs = Date.now() - new Date(iso).getTime();
  const minutes = Math.round(diffMs / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  if (days < 7) return `${days}d ago`;
  return formatDispatchTimestamp(iso);
}

export const STATUS_META: Record<string, { label: string; tone: "wire" | "signal" | "alert" | "ok" }> = {
  pending: { label: "queued", tone: "wire" },
  extracted: { label: "extracting", tone: "signal" },
  extraction_failed: { label: "couldn't extract", tone: "alert" },
  summarized: { label: "ready", tone: "ok" },
  sent: { label: "sent", tone: "wire" },
};

// `status` tracks processing state (pending/extracted/summarized/
// extraction_failed) and is never itself "sent" - whether an item actually
// went out is tracked separately via loopwire_send_id. Combine both so the
// UI shows "sent" instead of "ready" forever after delivery.
export function effectiveStatus(status: string, loopwireSendId: number | null): string {
  return loopwireSendId ? "sent" : status;
}
