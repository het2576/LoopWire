import DispatchHeader from "@/components/DispatchHeader";
import EmptyState from "@/components/EmptyState";
import ItemSlip from "@/components/ItemSlip";
import ProfileStatusBadge from "@/components/ProfileStatusBadge";
import { getLatestLoopwireSend, markOpened } from "@/lib/api";

export default async function LatestPage() {
  const send = await getLatestLoopwireSend();

  if (!send) {
    return (
      <div>
        <section className="focus-hero mb-8 px-5 py-9 sm:mb-10 sm:px-10 sm:py-14">
          <div className="relative z-10"><p className="text-sm font-medium text-mint">Your next great read starts here</p>
          <h1 className="mt-4 max-w-xl font-mono text-[clamp(2.35rem,11vw,3rem)] font-semibold leading-[0.95] tracking-[-0.07em] sm:text-6xl">Your reading space is ready.</h1>
          <p className="mt-5 max-w-md text-[15px] leading-relaxed text-white/65">Send a link to your Telegram bot and Loopwire will turn it into a concise, personal briefing.</p>
          <div className="signal-cascade mt-9"><span>capture</span><i /><span>distill</span><i /><span>return</span></div></div>
        </section>
        <ProfileStatusBadge />
        <EmptyState>
          Nothing in the wire yet. Forward a link to your Telegram bot to start filling the queue —
          your first dispatch will show up here once it&apos;s built and sent.
        </EmptyState>
      </div>
    );
  }

  for (const item of send.items) {
    markOpened(item.item_id);
  }

  return (
    <div>
      <section className="focus-hero mb-8 px-5 py-9 sm:mb-10 sm:px-10 sm:py-12">
        <div className="relative z-10 grid gap-8 sm:grid-cols-[1fr_auto] sm:items-end">
          <div><p className="text-sm font-medium text-mint">Fresh from your reading queue</p><h1 className="mt-4 max-w-xl font-mono text-[clamp(2.35rem,11vw,3rem)] font-semibold leading-[0.95] tracking-[-0.07em] sm:text-6xl">A better way to come back to what matters.</h1><div className="signal-cascade mt-8"><span>saved by you</span><i /><span>ready to read</span></div></div>
          <p className="max-w-52 text-sm leading-relaxed text-white/60">A concise, personal briefing made from the links you chose to keep.</p>
        </div>
      </section>
      <ProfileStatusBadge />
      <DispatchHeader id={send.id} sentAt={send.sent_at} itemCount={send.item_count} period={send.period} />
      <ul className="flex flex-col gap-5">
        {send.items.map((item, index) => (
          <ItemSlip key={item.item_id} item={item} index={index} />
        ))}
      </ul>
    </div>
  );
}
