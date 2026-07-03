import { dispatchNumber, formatDispatchTimestamp } from "@/lib/format";

export default function DispatchHeader({
  id,
  sentAt,
  itemCount,
  period,
}: {
  id: number;
  sentAt: string;
  itemCount: number;
  period: string;
}) {
  return (
    <div className="mb-8">
      <div className="font-mono text-3xl font-bold tracking-tight text-signal sm:text-4xl">
        DISPATCH {dispatchNumber(id)}
      </div>
      <div className="mt-2 font-mono text-xs tracking-[0.1em] text-wire">
        RECEIVED {formatDispatchTimestamp(sentAt)} · {itemCount} ITEM{itemCount === 1 ? "" : "S"} ·{" "}
        {period.toUpperCase()}
      </div>
    </div>
  );
}
