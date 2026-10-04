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
    <div className="mb-7 flex flex-wrap items-end justify-between gap-5 sm:mb-8">
      <div><p className="page-kicker">Delivered {formatDispatchTimestamp(sentAt)}</p><h2 className="mt-2 font-mono text-2xl font-semibold tracking-[-0.06em] text-ink sm:text-3xl">Dispatch {dispatchNumber(id)}</h2></div>
      <div className="flex gap-2 text-[12px] text-wire"><span className="rounded-full bg-paper px-3 py-1.5">{itemCount} item{itemCount === 1 ? "" : "s"}</span><span className="rounded-full bg-paper px-3 py-1.5 capitalize">{period}</span></div>
    </div>
  );
}
