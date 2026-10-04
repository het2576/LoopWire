import EmptyState from "@/components/EmptyState";
import SignalBar from "@/components/SignalBar";
import { getStats } from "@/lib/api";

export default async function SignalPage() {
  const stats = await getStats();
  const entries = stats ? Object.entries(stats) : [];

  return (
    <div>
      <div className="mb-8 sm:mb-10"><p className="page-kicker">Your reading patterns</p><h1 className="page-title mt-3">What keeps you reading.</h1><p className="page-intro mt-4">A simple view of what caught your attention. This will shape future briefings when there is enough signal.</p></div>

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
