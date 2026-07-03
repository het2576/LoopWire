import EmptyState from "@/components/EmptyState";
import SignalBar from "@/components/SignalBar";
import { getStats } from "@/lib/api";

export default async function SignalPage() {
  const stats = await getStats();
  const entries = stats ? Object.entries(stats) : [];

  return (
    <div>
      <h1 className="mb-2 font-mono text-2xl font-bold tracking-tight text-signal">SIGNAL</h1>
      <p className="mb-8 text-[13px] text-wire">
        Engagement by content type. This is a read-only log — it doesn&apos;t change what gets
        sent to you yet. Using it to adapt future dispatches is a planned upgrade, not built yet.
      </p>

      {entries.length === 0 ? (
        <EmptyState>No dispatches sent yet — engagement stats will show up here once you have some.</EmptyState>
      ) : (
        <div className="flex flex-col gap-8">
          {entries.map(([type, bucket]) => (
            <div key={type} className="slip bg-paper p-6 text-ink sm:p-8">
              <div className="mb-4 flex items-baseline justify-between">
                <div className="font-mono text-sm font-semibold uppercase tracking-wide">{type}</div>
                <div className="font-mono text-xs text-ink/50">{bucket.total_sent} sent</div>
              </div>
              <div className="flex flex-col gap-3">
                <SignalBar label="Opened" value={bucket.total_sent ? bucket.opened / bucket.total_sent : 0} tone="ok" />
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
