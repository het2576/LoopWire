"use client";

import { useState, useTransition } from "react";
import { submitFeedback } from "@/lib/actions";

export default function FeedbackButtons({ itemId, initial }: { itemId: number; initial: "up" | "down" | null }) {
  const [vote, setVote] = useState(initial);
  const [pending, startTransition] = useTransition();

  function cast(next: "up" | "down") {
    const previous = vote;
    setVote(next);
    startTransition(async () => {
      const ok = await submitFeedback(itemId, next);
      if (!ok) setVote(previous);
    });
  }

  const base =
    "min-h-9 rounded-lg border px-3 text-[12px] font-semibold transition-colors disabled:cursor-wait";
  return (
    <div className="flex items-center gap-2" role="group" aria-label="Rate this item">
      <button
        type="button"
        onClick={() => cast("up")}
        disabled={pending}
        aria-pressed={vote === "up"}
        className={`${base} ${vote === "up" ? "border-ok bg-ok/15 text-ok" : "border-ink/15 text-ink/60 hover:border-ok hover:text-ok"}`}
      >
        👍 More like this
      </button>
      <button
        type="button"
        onClick={() => cast("down")}
        disabled={pending}
        aria-pressed={vote === "down"}
        className={`${base} ${vote === "down" ? "border-alert bg-alert/10 text-alert" : "border-ink/15 text-ink/60 hover:border-alert hover:text-alert"}`}
      >
        👎 Less
      </button>
    </div>
  );
}
