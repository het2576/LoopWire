export default function SignalBar({ label, value, tone }: { label: string; value: number; tone: "signal" | "ok" | "wire" }) {
  const colorClass = tone === "ok" ? "bg-ok" : tone === "signal" ? "bg-signal" : "bg-wire";
  const pct = Math.round(value * 100);

  return (
    <div>
      <div className="mb-1.5 flex justify-between text-[12px] text-wire">
        <span>{label}</span>
        <span className="font-semibold text-ink">{pct}%</span>
      </div>
      <div className="h-2 w-full overflow-hidden rounded-full bg-white/10">
        <div className={`h-full rounded-full ${colorClass}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}
