import Link from "next/link";
import EmptyState from "@/components/EmptyState";
import WireRow from "@/components/WireRow";
import { listItems } from "@/lib/api";

const FILTERS = [
  { value: undefined, label: "All" },
  { value: "pending", label: "Queued" },
  { value: "extraction_failed", label: "Failed" },
  { value: "summarized", label: "Ready" },
  { value: "sent", label: "Sent" },
] as const;

export default async function WirePage({
  searchParams,
}: {
  searchParams: Promise<{ status?: string }>;
}) {
  const { status } = await searchParams;
  const items = await listItems(status);

  return (
    <div>
      <div className="mb-8 grid gap-5 sm:mb-10 sm:grid-cols-[1fr_auto] sm:items-end"><div><p className="page-kicker">Your incoming queue</p><h1 className="page-title mt-3">Everything you saved.</h1><p className="page-intro mt-4">Follow each link from first save to its place in a briefing.</p></div><div className="hidden max-w-44 text-sm leading-relaxed text-wire sm:block">The queue updates as your links are processed.</div></div>

      <div className="mb-6 flex gap-2 overflow-x-auto pb-1 [scrollbar-width:none]">
        {FILTERS.map((f) => {
          const active = (status ?? undefined) === f.value;
          const href = f.value ? `/wire?status=${f.value}` : "/wire";
          return (
            <Link
              key={f.label}
              href={href}
              className={`min-h-11 shrink-0 rounded-full px-3.5 py-2 text-[12px] font-semibold transition-colors ${
                active
                  ? "bg-ink-deep text-white shadow-sm"
                  : "bg-paper text-wire hover:bg-white/12 hover:text-mint"
              }`}
            >
              {f.label}
            </Link>
          );
        })}
      </div>

      {!items || items.length === 0 ? (
        <EmptyState>
          {status
            ? "Nothing matches this filter right now."
            : "Nothing on the wire yet. Forward a link to your Telegram bot to start filling the queue."}
        </EmptyState>
      ) : (
        <ul className="overflow-hidden rounded-[20px] border border-ink/7 bg-paper shadow-[0_10px_26px_rgba(27,35,69,0.045)]">
          {items.map((item) => (
            <WireRow key={item.item_id} item={item} />
          ))}
        </ul>
      )}
    </div>
  );
}
