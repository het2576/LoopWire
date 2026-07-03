import { SavedItem, readUrl } from "@/lib/api";
import { STATUS_META, TYPE_LABEL, effectiveStatus, relativeTime } from "@/lib/format";

const DOT_CLASS: Record<string, string> = {
  wire: "bg-wire",
  signal: "bg-signal signal-dot",
  alert: "bg-alert",
  ok: "bg-ok",
};

const TEXT_CLASS: Record<string, string> = {
  wire: "text-wire",
  signal: "text-signal",
  alert: "text-alert",
  ok: "text-ok",
};

export default function WireRow({ item, index }: { item: SavedItem; index: number }) {
  const status = effectiveStatus(item.status, item.loopwire_send_id);
  const meta = STATUS_META[status] ?? { label: status, tone: "wire" as const };
  const typeLabel = TYPE_LABEL[item.type] ?? "Link";

  return (
    <li
      className="teletype-in border-b border-white/10 last:border-0"
      style={{ animationDelay: `${Math.min(index, 12) * 40}ms` }}
    >
      <a
        href={readUrl(item.item_id)}
        className="group flex items-center gap-3 py-3.5 transition-colors hover:bg-ink-raised/60 sm:gap-4"
      >
        <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${DOT_CLASS[meta.tone]}`} aria-hidden />

        <span className="w-[72px] shrink-0 font-mono text-[10px] uppercase tracking-wider text-wire sm:w-[92px]">
          {typeLabel}
        </span>

        <span className="min-w-0 flex-1 truncate text-[14px] text-paper/90 group-hover:text-paper">
          {item.title}
        </span>

        <span className="hidden shrink-0 font-mono text-[11px] text-wire sm:inline">
          {item.loopwire_send_id ? `#${item.loopwire_send_id.toString().padStart(3, "0")}` : "—"}
        </span>

        <span className={`shrink-0 font-mono text-[10px] uppercase tracking-wider ${TEXT_CLASS[meta.tone]}`}>
          {meta.label}
        </span>

        <span className="hidden w-16 shrink-0 text-right font-mono text-[11px] text-wire/70 md:inline">
          {relativeTime(item.added_at)}
        </span>
      </a>
    </li>
  );
}
