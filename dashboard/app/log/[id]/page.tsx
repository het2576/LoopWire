import { notFound } from "next/navigation";
import DispatchHeader from "@/components/DispatchHeader";
import ItemSlip from "@/components/ItemSlip";
import { getLoopwireSend } from "@/lib/api";

export default async function LoopwireSendDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const send = await getLoopwireSend(Number(id));

  if (!send) {
    notFound();
  }

  return (
    <div>
      <DispatchHeader id={send.id} sentAt={send.sent_at} itemCount={send.item_count} period={send.period} />
      <ul className="flex flex-col gap-5">
        {send.items.map((item, index) => (
          <ItemSlip key={item.item_id} item={item} index={index} />
        ))}
      </ul>
    </div>
  );
}
