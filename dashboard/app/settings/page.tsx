import { redirect } from "next/navigation";
import { createConnectionCode, getMe, updateInterestProfile } from "@/lib/api";

async function saveProfile(formData: FormData) {
  "use server";
  const text = (formData.get("profile_text") as string) ?? "";
  await updateInterestProfile(text.trim());
  redirect("/settings?saved=1");
}

async function generateCode() {
  "use server";
  const result = await createConnectionCode();
  if (!result) {
    console.error("[Settings] generateCode: createConnectionCode returned null — check Vercel and Render env vars (INTERNAL_AUTH_SECRET, NEXT_PUBLIC_BACKEND_URL)");
  }

  redirect(result ? `/settings?code=${result.code}` : "/settings?code_error=1");
}

export default async function SettingsPage({
  searchParams,
}: {
  searchParams: Promise<{ code?: string; saved?: string; code_error?: string }>;
}) {
  const { code, saved, code_error } = await searchParams;
  const me = await getMe();

  return (
    <div className="flex flex-col gap-7">
      <div><p className="page-kicker">Your preferences</p><h1 className="page-title mt-3">Make it yours.</h1><p className="page-intro mt-4">Tell Loopwire what you care about, then connect where your best links arrive.</p></div>

      {/* Interest profile */}
      <section className="paper-sheet">
        <div className="grid sm:grid-cols-[190px_1fr]"><div className="border-b border-white/10 px-6 py-6 sm:border-b-0 sm:border-r sm:px-7"><div className="flex h-9 w-9 items-center justify-center rounded-xl bg-signal/20 text-lg text-signal">✦</div><p className="mt-4 font-mono text-sm font-semibold">Your interests</p><p className="mt-2 text-[12px] leading-relaxed text-ink/50">This informs every summary.</p></div><div className="px-6 py-6 sm:px-8">
        <p className="text-[14px] leading-relaxed text-ink/60">
          A short paragraph describing what you care about — shapes how new links are summarized and scored.
        </p>
        <form action={saveProfile} className="mt-4">
          <textarea
            name="profile_text"
            defaultValue={me?.interest_profile_text ?? ""}
            rows={4}
            placeholder="e.g. I'm a backend engineer interested in distributed systems, AI/LLM tooling, and indie startups."
            className="w-full resize-y rounded-xl border border-white/10 bg-black/20 px-4 py-3 text-[14px] leading-relaxed text-ink placeholder:text-ink/35 focus:border-signal focus:outline-none"
          />
          <div className="mt-3 flex items-center gap-3">
            <button
              type="submit"
              className="min-h-11 rounded-xl bg-ink-deep px-4 py-2.5 text-[12px] font-semibold text-white transition-colors hover:bg-signal"
            >
              Save profile
            </button>
            {saved && <span className="font-mono text-[12px] text-ok">Saved ✓</span>}
          </div>
        </form>
        </div></div>
      </section>

      {/* Telegram connection */}
      <section className="paper-sheet">
        <div className="grid sm:grid-cols-[190px_1fr]"><div className="border-b border-white/10 px-6 py-6 sm:border-b-0 sm:border-r sm:px-7"><div className="flex h-9 w-9 items-center justify-center rounded-xl bg-blue/20 text-lg text-blue">↗</div><p className="mt-4 font-mono text-sm font-semibold">Telegram</p><p className="mt-2 text-[12px] leading-relaxed text-ink/50">Your capture inbox.</p></div><div className="px-6 py-6 sm:px-8">

        {me?.telegram_chat_id ? (
          code ? (
              <div className="mt-1 rounded-xl border border-ok/20 bg-ok/10 px-4 py-3">
              <p className="font-mono text-[13px] font-semibold text-ok">Telegram is connected.</p>
              <p className="mt-1 text-[13px] text-ink/70">
                Forward any link to <span className="font-mono text-ink">@loopwirexbot</span> to start saving.
              </p>
            </div>
          ) : (
            <p className="mt-1 flex items-center gap-2 text-[14px] text-ink/70">
              <span className="h-1.5 w-1.5 rounded-full bg-ok" aria-hidden />
              Connected — forward links to <span className="font-mono text-ink">@loopwirexbot</span> to start saving.
            </p>
          )
        ) : (
          <>
            <p className="mt-2 text-[13px] leading-relaxed text-ink/60">
              Not connected yet. Generate a code, then send it to the bot as{" "}
              <span className="font-mono text-ink">/connect &lt;code&gt;</span>.
            </p>

            {code && (
              <div className="mt-4 rounded-xl border border-signal/30 bg-signal/10 px-4 py-3">
                <div className="font-mono text-[11px] text-ink/50">Your code — expires in 15 min</div>
                <div className="mt-1 font-mono text-xl font-bold tracking-[0.15em] text-ink">{code}</div>
                <div className="mt-2 font-mono text-[12px] text-ink/60">Send: /connect {code}</div>
              </div>
            )}
            {code_error && (
              <div className="mt-3 rounded-xl border border-alert/20 bg-alert/10 px-4 py-3">
                <p className="font-mono text-[12px] font-semibold text-alert">
                  Couldn&apos;t generate a code — try again in a moment.
                </p>
                <p className="mt-1 text-[12px] text-ink/60">
                  If this keeps failing, check that{" "}
                  <code className="rounded bg-ink/10 px-1">INTERNAL_AUTH_SECRET</code> and{" "}
                  <code className="rounded bg-ink/10 px-1">NEXT_PUBLIC_BACKEND_URL</code>{" "}
                  are set correctly in both Vercel and Render.
                  {" "}See <a href="/api/debug" target="_blank" className="underline">diagnostic info</a>.
                </p>
              </div>

            )}

            <form action={generateCode} className="mt-4">
              <button
                type="submit"
                className="min-h-11 rounded-xl bg-ink-deep px-4 py-2.5 text-[12px] font-semibold text-white transition-colors hover:bg-signal"
              >
                {code ? "Generate new code" : "Generate connection code"}
              </button>
            </form>
          </>
        )}
        </div></div>
      </section>

      {me?.email && (
        <p className="text-[12px] text-wire">Signed in as {me.email}</p>
      )}
    </div>
  );
}
