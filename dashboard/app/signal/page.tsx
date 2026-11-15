import EmptyState from "@/components/EmptyState";
import SignalBar from "@/components/SignalBar";
import { getRecallStats, getStats } from "@/lib/api";

export default async function SignalPage() {
  const [stats, recall] = await Promise.all([getStats(), getRecallStats()]);
  const entries = stats ? Object.entries(stats) : [];

  return (
    <div>
      <div className="mb-8 sm:mb-10"><p className="page-kicker">Your reading patterns</p><h1 className="page-title mt-3">What keeps you reading.</h1><p className="page-intro mt-4">What caught your attention — and, more importantly, what stuck.</p></div>

      {recall && recall.reviews > 0 && (
        <section className="paper-sheet mb-6 p-6 sm:p-7">
          <p className="font-mono text-base font-semibold">Retention</p>
          <p className="mt-1 text-[13px] text-ink/55">How much of what you read you could still recall when quizzed.</p>
          <div className="mt-5 grid grid-cols-2 gap-4 sm:grid-cols-4">
            {[
              ["Retention", recall.retention_rate !== null ? `${Math.round(recall.retention_rate * 100)}%` : "–"],
              ["Reviews", String(recall.reviews)],
              ["Active cards", String(recall.cards_active)],
              ["Mastered", String(recall.cards_retired)],
            ].map(([label, value]) => (
              <div key={label}>
                <div className="font-mono text-2xl font-semibold">{value}</div>
                <div className="text-[12px] text-ink/50">{label}</div>
              </div>
            ))}
          </div>
        </section>
      )}

      {entries.length === 0 ? (
        <EmptyState>No dispatches sent yet — engagement stats will show up here once you have some.</EmptyState>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2">
          {entries.map(([type, bucket]) => (
            <div key={type} className="paper-sheet p-6 sm:p-7">
              <div className="mb-4 flex items-baseline justify-between">
                <div className="font-mono text-base font-semibold capitalize">{type}</div>
                <div className="rounded-full bg-white/8 px-2.5 py-1 text-[11px] font-semibold text-mint">{bucket.total_sent} sent</div>
              </div>
              <div className="flex flex-col gap-3">
                <SignalBar label="Rated 👍" value={bucket.total_sent ? bucket.feedback_up / bucket.total_sent : 0} tone="ok" />
                <SignalBar
                  label="Clicked source"
                  value={bucket.total_sent ? bucket.clicked_source / bucket.total_sent : 0}
                  tone="signal"
                />
                <SignalBar
                  label="Skipped"
                  value={bucket.total_sent ? bucket.skipped / bucket.total_sent : 0}
                  tone="wire"
                />
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
