import { getProfileStatus } from "@/lib/api";

export default async function ProfileStatusBadge() {
  const status = await getProfileStatus();
  if (!status) return null;

  return (
    <div
      className={`mb-6 inline-flex items-center gap-2 rounded-full border px-3 py-1.5 font-mono text-[11px] tracking-wide ${
        status.is_adaptive ? "border-ok/40 text-ok" : "border-wire/30 text-wire"
      }`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${status.is_adaptive ? "bg-ok signal-dot" : "bg-wire"}`} aria-hidden />
      {status.is_adaptive ? (
        "ADAPTIVE DIGEST ACTIVE"
      ) : (
        <>
          STATIC DIGEST &middot; {status.engagement_count}/{status.threshold} INTERACTIONS UNTIL DIGESTS ADAPT TO YOU
        </>
      )}
    </div>
  );
}
