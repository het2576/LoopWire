import { getProfileStatus } from "@/lib/api";

export default async function ProfileStatusBadge() {
  const status = await getProfileStatus();
  if (!status) return null;

  return (
    <div
      className={`mb-6 flex w-fit max-w-full items-center gap-2 rounded-full px-3 py-2 text-[12px] font-medium leading-snug ${
        status.is_adaptive ? "bg-ok/10 text-ok" : "bg-mint/25 text-ink"
      }`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${status.is_adaptive ? "bg-ok signal-dot" : "bg-wire"}`} aria-hidden />
      {status.is_adaptive ? (
        "Digest adapts to your reading"
      ) : (
        <>
          {status.engagement_count}/{status.threshold} interactions before the digest adapts
        </>
      )}
    </div>
  );
}
