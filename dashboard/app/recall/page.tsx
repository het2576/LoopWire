import EmptyState from "@/components/EmptyState";
import RecallSession from "@/components/RecallSession";
import { getNextRecall, getRecallStats } from "@/lib/api";

export default async function RecallPage() {
  const [card, stats] = await Promise.all([getNextRecall(), getRecallStats()]);

  return (
    <div>
      <div className="mb-8 sm:mb-10">
        <p className="page-kicker">Active recall</p>
        <h1 className="page-title mt-3">Do you still remember?</h1>
        <p className="page-intro mt-4">
          A day after you click through to or 👍 something, Loopwire asks about its key idea — then waits longer each time you get
          it right. Saving isn&apos;t learning; remembering is.
        </p>
      </div>

      {card ? (
        <RecallSession key={card.card_id} card={card} />
      ) : (
        <EmptyState>
          {stats && stats.cards_active > 0
            ? "Nothing due right now — your next question unlocks soon. Check back tomorrow."
            : "No questions yet. Open or 👍 an item from your dispatch and its recall questions unlock the next day."}
        </EmptyState>
      )}

      {stats && stats.reviews > 0 && (
        <p className="mt-6 text-[13px] text-ink/55">
          {stats.reviews} reviews · retention{" "}
          {stats.retention_rate !== null ? `${Math.round(stats.retention_rate * 100)}%` : "–"} · {stats.cards_retired}{" "}
          mastered
        </p>
      )}
    </div>
  );
}
