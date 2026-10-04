"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

type State = "idle" | "loading" | "success" | "error";

export default function ProcessQueueButton() {
  const router = useRouter();
  const [state, setState] = useState<State>("idle");
  const [message, setMessage] = useState("");

  async function processQueue() {
    setState("loading");
    setMessage("");
    try {
      const response = await fetch("/api/queue/process", { method: "POST" });
      const result = await response.json() as { processed?: number; summarized?: number; failed?: number; error?: string };
      if (!response.ok) throw new Error(result.error ?? "Could not process the queue.");

      const completed = (result.summarized ?? 0) + (result.failed ?? 0);
      setState("success");
      setMessage(completed ? `Queue updated — ${completed} item${completed === 1 ? "" : "s"} completed.` : "Nothing new was waiting to be processed.");
      router.refresh();
    } catch (error) {
      setState("error");
      setMessage(error instanceof Error ? error.message : "Could not process the queue.");
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-3">
      <button
        type="button"
        onClick={processQueue}
        disabled={state === "loading"}
        className="min-h-11 rounded-full border border-ink/15 bg-paper px-4 text-[12px] font-semibold text-ink transition-colors hover:border-signal hover:text-signal disabled:cursor-wait disabled:opacity-65"
      >
        {state === "loading" ? "Processing queue…" : "Process queue now"}
      </button>
      {message && <p role="status" className={`text-[12px] ${state === "error" ? "text-alert" : "text-ok"}`}>{message}</p>}
    </div>
  );
}
