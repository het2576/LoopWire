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

export default function WireRow({ item }: { item: SavedItem }) {
  const status = effectiveStatus(item.status, item.loopwire_send_id);
  const meta = STATUS_META[status] ?? { label: status, tone: "wire" as const };
  const typeLabel = TYPE_LABEL[item.type] ?? "Link";

  return (
    <li
      className="border-b border-ink/7 last:border-0"
    >
      <a
        href={readUrl(item.item_id)}
        className="group grid grid-cols-[12px_1fr_auto] items-center gap-x-3 gap-y-1 px-4 py-4 transition-colors hover:bg-white/6 sm:grid-cols-[12px_118px_1fr_auto_auto] sm:gap-x-4 sm:px-5"
      >
        <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${DOT_CLASS[meta.tone]}`} aria-hidden />

        <span className="col-start-2 text-[11px] font-medium text-wire sm:col-start-auto">
          {typeLabel}
        </span>

        <span className="col-start-2 min-w-0 truncate text-[14px] font-medium text-ink/85 group-hover:text-signal sm:col-start-auto">
          {item.title}
        </span>

        <span className="hidden text-[11px] text-wire sm:inline">
          {item.loopwire_send_id ? `#${item.loopwire_send_id.toString().padStart(3, "0")}` : "—"}
        </span>

        <span className={`col-start-3 row-start-1 text-[11px] font-medium ${TEXT_CLASS[meta.tone]} sm:col-start-auto`}>
          {meta.label}
        </span>

        <span className="hidden w-16 shrink-0 text-right text-[11px] text-wire/70 md:inline">
          {relativeTime(item.added_at)}
        </span>
      </a>
    </li>
  );
}
