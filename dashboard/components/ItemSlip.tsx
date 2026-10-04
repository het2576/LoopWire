import { LoopwireItem } from "@/lib/api";
import { TYPE_LABEL } from "@/lib/format";

export default function ItemSlip({ item, index }: { item: LoopwireItem; index: number }) {
  const eyebrow = TYPE_LABEL[item.type] ?? "Link";

  return (
    <li
      className="paper-sheet dispatch-sheet"
    >
      <div className="grid sm:grid-cols-[145px_1fr]">
        <div className="flex items-center justify-between border-b border-ink/10 px-5 py-4 sm:block sm:border-b-0 sm:border-r sm:px-6 sm:py-7">
          <p className="font-mono text-sm font-semibold text-signal">{String(index + 1).padStart(2, "0")}</p>
          <p className="font-mono text-[11px] text-ink/45 sm:mt-8">{eyebrow}<br /><span className="text-ink/35">{!item.couldnt_extract && item.read_time_minutes ? `${item.read_time_minutes} min read` : "Saved link"}</span></p>
        </div>
        <div className="px-5 py-6 sm:px-8 sm:py-7">
        <div
          className={`text-[12px] font-semibold ${
            item.couldnt_extract ? "text-alert" : "text-ink/50"
          }`}
        >
          {item.couldnt_extract ? "Couldn’t extract this source" : "Reading note"}
        </div>

        <h2 className="mt-2 font-mono text-xl font-semibold leading-tight tracking-[-0.055em] text-ink sm:text-2xl">{item.title}</h2>

        {item.couldnt_extract ? (
          <p className="mt-2 text-[15px] leading-relaxed text-ink/70">
            {item.type === "unsupported"
              ? "This source isn't supported for extraction yet (e.g. social posts or playlists)."
              : "We couldn't pull readable content from this one — a paywall or missing captions, most likely."}{" "}
            The raw link is still here.
          </p>
        ) : (
          <>
            {/* Key takeaway callout — bold single-sentence insight */}
            {item.key_takeaway && (
              <p className="mt-4 rounded-r-lg border-l-2 border-mint bg-white/5 py-2.5 pl-4 pr-3 text-[15px] font-semibold leading-snug text-ink/90">
                {item.key_takeaway}
              </p>
            )}

            {/* Full summary */}
            {item.summary && (
            <p className="mt-3 max-w-2xl text-[15px] leading-relaxed text-ink/75">{item.summary}</p>
            )}

            {/* Relevance note */}
            {item.relevance_note && (
              <p className="mt-3 max-w-xl text-[13px] italic leading-relaxed text-ink/50">
                {item.relevance_note}
              </p>
            )}
          </>
        )}

        <a
          href={item.read_url}
          className="mt-5 inline-flex items-center gap-2 rounded-lg bg-ink-deep px-3.5 py-2 text-[12px] font-semibold text-white transition-colors hover:bg-signal"
        >
          {item.couldnt_extract ? "Open raw link" : "Read source"} <span aria-hidden>↗</span>
        </a>
        </div>
      </div>
    </li>
  );
}
