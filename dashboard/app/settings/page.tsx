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
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="font-mono text-2xl font-bold tracking-tight text-signal">SETTINGS</h1>
        <p className="mt-2 text-[13px] text-wire">Your account, interest profile, and Telegram connection.</p>
      </div>

      {/* Interest profile */}
      <section className="slip bg-paper p-6 text-ink sm:p-8">
        <h2 className="font-mono text-sm font-semibold uppercase tracking-wide">Interest profile</h2>
        <p className="mt-2 text-[13px] leading-relaxed text-ink/60">
          A short paragraph describing what you care about — shapes how new links are summarized and scored.
        </p>
        <form action={saveProfile} className="mt-4">
          <textarea
            name="profile_text"
            defaultValue={me?.interest_profile_text ?? ""}
            rows={4}
            placeholder="e.g. I'm a backend engineer interested in distributed systems, AI/LLM tooling, and indie startups."
            className="w-full resize-y rounded-md border border-ink/15 bg-white px-3 py-2 text-[14px] leading-relaxed text-ink placeholder:text-ink/35 focus:border-signal focus:outline-none"
          />
          <div className="mt-3 flex items-center gap-3">
            <button
              type="submit"
              className="rounded-md bg-ink px-4 py-2 font-mono text-[12px] font-semibold tracking-wide text-paper transition-opacity hover:opacity-90"
            >
              Save profile
            </button>
            {saved && <span className="font-mono text-[12px] text-ok">Saved ✓</span>}
          </div>
        </form>
      </section>

      {/* Telegram connection */}
      <section className="slip bg-paper p-6 text-ink sm:p-8">
        <h2 className="font-mono text-sm font-semibold uppercase tracking-wide">Telegram</h2>

        {me?.telegram_chat_id ? (
          <p className="mt-3 flex items-center gap-2 text-[14px] text-ink/70">
            <span className="h-1.5 w-1.5 rounded-full bg-ok" aria-hidden />
            Connected — forward links to <span className="font-mono text-ink">@loopwirexbot</span> to start saving.
          </p>
        ) : (
          <>
            <p className="mt-2 text-[13px] leading-relaxed text-ink/60">
              Not connected yet. Generate a code, then send it to the bot as{" "}
              <span className="font-mono text-ink">/connect &lt;code&gt;</span>.
            </p>

            {code && (
              <div className="mt-4 rounded-md border border-signal/40 bg-signal/10 px-4 py-3">
                <div className="font-mono text-[11px] uppercase tracking-wide text-ink/50">Your code (expires in 15 min)</div>
                <div className="mt-1 font-mono text-xl font-bold tracking-[0.15em] text-ink">{code}</div>
                <div className="mt-2 font-mono text-[12px] text-ink/60">Send: /connect {code}</div>
              </div>
            )}
            {code_error && (
              <p className="mt-3 font-mono text-[12px] text-alert">
                Couldn&apos;t generate a code — try again in a moment.
              </p>
            )}

            <form action={generateCode} className="mt-4">
              <button
                type="submit"
                className="rounded-md bg-ink px-4 py-2 font-mono text-[12px] font-semibold tracking-wide text-paper transition-opacity hover:opacity-90"
              >
                {code ? "Generate new code" : "Generate connection code"}
              </button>
            </form>
          </>
        )}
      </section>

      {me?.email && (
        <p className="font-mono text-[11px] text-wire/70">Signed in as {me.email}</p>
      )}
    </div>
  );
}
