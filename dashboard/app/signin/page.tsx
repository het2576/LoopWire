import { signIn } from "@/auth";

function GoogleLogo() {
  return (
    <svg width="18" height="18" viewBox="0 0 48 48" aria-hidden="true" className="shrink-0">
      <path
        fill="#EA4335"
        d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"
      />
      <path
        fill="#4285F4"
        d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"
      />
      <path
        fill="#FBBC05"
        d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"
      />
      <path
        fill="#34A853"
        d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"
      />
    </svg>
  );
}

export default function SignInPage() {
  return (
    <div className="mx-auto grid min-h-[calc(100vh-15rem)] max-w-5xl items-center gap-8 lg:grid-cols-[1.1fr_0.9fr] lg:gap-16">
      <div><p className="page-kicker">Your own corner of the internet</p><h1 className="page-title mt-4">Save the link.<br />Keep the thought.</h1><p className="page-intro mt-6">Loopwire turns the interesting things you find into a brief you will actually want to return to.</p><div className="mt-8 flex flex-wrap gap-3 text-[12px] font-medium text-wire"><span className="rounded-full bg-paper px-3 py-2">Personal summaries</span><span className="rounded-full bg-paper px-3 py-2">Telegram capture</span></div></div>
      <div className="paper-sheet text-ink"><div className="px-7 py-8 sm:px-10 sm:py-10"><p className="font-mono text-lg font-semibold tracking-[-0.05em]">Start your reading space</p><p className="mt-3 text-[14px] leading-relaxed text-ink/65">Sign in once, then send links to Telegram whenever inspiration strikes.</p>

        <form
          className="mt-6"
          action={async () => {
            "use server";
            await signIn("google", { redirectTo: "/" });
          }}
        >
          <button
            type="submit"
            className="group inline-flex w-full items-center justify-center gap-3 rounded-xl bg-ink-deep px-5 py-3.5 text-[13px] font-semibold text-white transition-colors hover:bg-signal"
          >
            <span className="flex h-6 w-6 items-center justify-center rounded-full bg-paper">
              <GoogleLogo />
            </span>
            Continue with Google
          </button>
        </form>

        <div className="mt-7 flex items-center gap-3 text-ink/30">
          <div className="h-px flex-1 bg-ink/10" />
          <span className="text-[10px] font-medium">What happens next</span>
          <div className="h-px flex-1 bg-ink/10" />
        </div>

        <p className="mt-4 text-[12px] leading-relaxed text-ink/45">
          After signing in, connect Telegram from Settings to start saving links.
        </p>
        <p className="mt-2 text-[12px] leading-relaxed text-ink/45">
          Some paywalled articles or videos without captions can&apos;t be summarized — you&apos;ll see them flagged, not silently dropped.
        </p>
      </div></div>
    </div>
  );
}
