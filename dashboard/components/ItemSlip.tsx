import { LoopwireItem } from "@/lib/api";
import { TYPE_LABEL } from "@/lib/format";

export default function ItemSlip({ item, index }: { item: LoopwireItem; index: number }) {
  const eyebrow = [
    TYPE_LABEL[item.type] ?? "Link",
    !item.couldnt_extract && item.read_time_minutes ? `${item.read_time_minutes} MIN` : null,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <li
      className="slip teletype-in bg-paper text-ink"
      style={{ animationDelay: `${index * 70}ms` }}
    >
      <div className="px-6 pt-6 pb-5 sm:px-8">
        <div
          className={`font-mono text-[11px] font-semibold tracking-[0.15em] ${
            item.couldnt_extract ? "text-alert" : "text-ink/50"
          }`}
        >
          {item.couldnt_extract ? `${eyebrow} · COULDN'T EXTRACT` : eyebrow}
        </div>

        <h2 className="mt-2 font-mono text-lg font-semibold leading-snug text-ink">{item.title}</h2>

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
              <p className="mt-3 border-l-2 border-signal pl-3 font-sans text-[14px] font-semibold leading-snug text-ink/90">
                {item.key_takeaway}
              </p>
            )}

            {/* Full summary */}
            {item.summary && (
              <p className="mt-2 text-[15px] leading-relaxed text-ink/75">{item.summary}</p>
            )}

            {/* Relevance note */}
            {item.relevance_note && (
              <p className="mt-2 text-[13px] italic leading-relaxed text-ink/50">
                {item.relevance_note}
              </p>
            )}
          </>
        )}

        <a
          href={item.read_url}
          className="mt-4 inline-block font-mono text-[13px] font-semibold tracking-wide text-signal underline decoration-signal/40 underline-offset-4 hover:decoration-signal"
        >
          {item.couldnt_extract ? "Open raw link →" : "Read source →"}
        </a>
      </div>
    </li>
  );
}
