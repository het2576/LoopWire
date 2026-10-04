import Link from "next/link";
import EmptyState from "@/components/EmptyState";
import { dispatchNumber, formatDispatchTimestamp } from "@/lib/format";
import { listLoopwireSends } from "@/lib/api";

export default async function LogPage() {
  const sends = await listLoopwireSends();

  return (
    <div>
      <div className="mb-8 sm:mb-10"><p className="page-kicker">Your archive</p><h1 className="page-title mt-3">Briefings, kept.</h1><p className="page-intro mt-4">Every finished digest, ready whenever you want to revisit it.</p></div>
      {!sends || sends.length === 0 ? <EmptyState>No dispatches yet. When the first one is ready, it will be kept here.</EmptyState> : <ul className="grid gap-3 sm:grid-cols-2">
        {sends.map((send) => (
          <li key={send.id}>
            <Link href={`/log/${send.id}`} className="paper-sheet group block p-5 transition-transform hover:-translate-y-0.5 hover:shadow-[0_15px_30px_rgba(31,35,73,0.1)] sm:p-6">
              <div>
                <div className="font-mono text-xl font-semibold tracking-[-0.06em] text-ink">
                  Dispatch {dispatchNumber(send.id)}
                </div>
                <div className="mt-2 text-[12px] text-wire">
                  {formatDispatchTimestamp(send.sent_at)}
                </div>
              </div>
              <div className="mt-7 flex items-center justify-between text-[12px] font-semibold text-wire group-hover:text-signal">
                {send.item_count} item{send.item_count === 1 ? "" : "s"} <span aria-hidden>↗</span>
              </div>
            </Link>
          </li>
        ))}
      </ul>}
    </div>
  );
}
