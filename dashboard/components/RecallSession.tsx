"use client";

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { reviewRecall } from "@/lib/actions";
import type { RecallCard, RecallReviewResult, RecallVerdict } from "@/lib/api";

const VERDICT_STYLE: Record<RecallVerdict, { label: string; tone: string }> = {
  correct: { label: "Got it", tone: "text-ok border-ok bg-ok/10" },
  partial: { label: "Partly", tone: "text-signal border-signal bg-signal/10" },
  incorrect: { label: "Not this time", tone: "text-alert border-alert bg-alert/10" },
};

export default function RecallSession({ card }: { card: RecallCard }) {
  const router = useRouter();
  const [answer, setAnswer] = useState("");
  const [revealed, setRevealed] = useState(false);
  const [result, setResult] = useState<RecallReviewResult | null>(null);
  const [error, setError] = useState("");
  const [pending, startTransition] = useTransition();

  function submit(input: { answer: string } | { self_verdict: RecallVerdict }) {
    setError("");
    startTransition(async () => {
      const res = await reviewRecall(card.card_id, input);
      if (res) setResult(res);
      else setError("Couldn’t record that — try again.");
    });
  }

  return (
    <section className="paper-sheet p-6 sm:p-8">
      <p className="text-[12px] font-semibold text-ink/50">
        {card.due_count} due · from{" "}
        <a href={card.source_url} className="underline decoration-ink/20 hover:text-signal">
          {card.source_title}
        </a>
      </p>
      <h2 className="mt-3 font-mono text-xl font-semibold leading-snug tracking-[-0.03em] sm:text-2xl">{card.question}</h2>

      {!result && !revealed && (
        <form
          className="mt-5"
          onSubmit={(e) => {
            e.preventDefault();
            if (answer.trim()) submit({ answer });
          }}
        >
          <label htmlFor="recall-answer" className="sr-only">
            Your answer
          </label>
          <textarea
            id="recall-answer"
            value={answer}
            onChange={(e) => setAnswer(e.target.value)}
            rows={3}
            placeholder="Answer in your own words…"
            className="w-full resize-y rounded-xl border border-ink/15 bg-black/5 px-4 py-3 text-[15px] leading-relaxed focus:border-signal focus:outline-none"
          />
          <div className="mt-3 flex flex-wrap gap-3">
            <button
              type="submit"
              disabled={pending || !answer.trim()}
              className="min-h-11 rounded-xl bg-ink-deep px-4 text-[13px] font-semibold text-white transition-colors hover:bg-signal disabled:opacity-50"
            >
              {pending ? "Checking…" : "Check my answer"}
            </button>
            <button
              type="button"
              onClick={() => setRevealed(true)}
              className="min-h-11 rounded-xl border border-ink/15 px-4 text-[13px] font-semibold text-ink/70 hover:border-signal hover:text-signal"
            >
              Just reveal it
            </button>
          </div>
        </form>
      )}

      {revealed && !result && (
        <div className="mt-5">
          <p className="text-[12px] font-semibold text-ink/50">How did you do?</p>
          <div className="mt-2 flex flex-wrap gap-2">
            {(Object.keys(VERDICT_STYLE) as RecallVerdict[]).map((v) => (
              <button
                key={v}
                type="button"
                disabled={pending}
                onClick={() => submit({ self_verdict: v })}
                className={`min-h-11 rounded-xl border px-4 text-[13px] font-semibold ${VERDICT_STYLE[v].tone}`}
              >
                {VERDICT_STYLE[v].label}
              </button>
            ))}
          </div>
        </div>
      )}

      {result && (
        <div className="mt-5 flex flex-col gap-3">
          <p className={`w-fit rounded-full border px-3 py-1 text-[12px] font-semibold ${VERDICT_STYLE[result.verdict].tone}`}>
            {VERDICT_STYLE[result.verdict].label}
          </p>
          {result.feedback && <p className="text-[15px] leading-relaxed text-ink/80">{result.feedback}</p>}
          <p className="text-[15px] leading-relaxed">
            <span className="font-semibold">Answer: </span>
            {result.reference_answer}
          </p>
          <blockquote className="border-l-2 border-mint pl-4 text-[13px] italic leading-relaxed text-ink/60">
            “{result.evidence_quote}”
          </blockquote>
          <p className="text-[12px] text-ink/50">
            {result.retired
              ? "Mastered — this one won’t come back."
              : result.next_due_at
                ? `Next review ${new Date(result.next_due_at).toLocaleDateString(undefined, { month: "short", day: "numeric" })}.`
                : ""}
          </p>
          <button
            type="button"
            onClick={() => router.refresh()}
            className="mt-1 min-h-11 w-fit rounded-xl bg-ink-deep px-4 text-[13px] font-semibold text-white hover:bg-signal"
          >
            Next question
          </button>
        </div>
      )}
      {error && (
        <p role="alert" className="mt-3 text-[13px] text-alert">
          {error}
        </p>
      )}
    </section>
  );
}
