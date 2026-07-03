import Link from "next/link";
import EmptyState from "@/components/EmptyState";
import { dispatchNumber, formatDispatchTimestamp } from "@/lib/format";
import { listLoopwireSends } from "@/lib/api";

export default async function LogPage() {
  const sends = await listLoopwireSends();

  if (!sends || sends.length === 0) {
    return <EmptyState>No dispatches sent yet — they&apos;ll be logged here once the first one goes out.</EmptyState>;
  }

  return (
    <div>
      <h1 className="mb-8 font-mono text-2xl font-bold tracking-tight text-signal">THE LOG</h1>
      <ul className="divide-y divide-white/10 border-y border-white/10">
        {sends.map((send) => (
          <li key={send.id}>
            <Link
              href={`/log/${send.id}`}
              className="flex items-center justify-between gap-4 py-4 transition-colors hover:bg-ink-raised/60"
            >
              <div>
                <div className="font-mono text-sm font-semibold text-paper">
                  DISPATCH {dispatchNumber(send.id)}
                </div>
                <div className="mt-1 font-mono text-[11px] tracking-wide text-wire">
                  {formatDispatchTimestamp(send.sent_at)}
                </div>
              </div>
              <div className="font-mono text-xs text-wire">
                {send.item_count} item{send.item_count === 1 ? "" : "s"} →
              </div>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
