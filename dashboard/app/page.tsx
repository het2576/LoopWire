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
