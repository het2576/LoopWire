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
      <h1 className="mb-2 font-mono text-2xl font-bold tracking-tight text-signal">THE WIRE</h1>
      <p className="mb-6 text-[13px] text-wire">
        Every link you&apos;ve ever forwarded, live — not just the ones already sent.
      </p>

      <div className="mb-6 flex flex-wrap gap-2">
        {FILTERS.map((f) => {
          const active = (status ?? undefined) === f.value;
          const href = f.value ? `/wire?status=${f.value}` : "/wire";
          return (
            <Link
              key={f.label}
              href={href}
              className={`rounded-full border px-3 py-1 font-mono text-[11px] uppercase tracking-wider transition-colors ${
                active
                  ? "border-signal bg-signal/10 text-signal"
                  : "border-white/15 text-wire hover:border-white/30 hover:text-paper"
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
        <ul className="border-t border-white/10">
          {items.map((item, index) => (
            <WireRow key={item.item_id} item={item} index={index} />
          ))}
        </ul>
      )}
    </div>
  );
}
