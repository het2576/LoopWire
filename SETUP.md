# Loopwire Setup

Everything below is a one-time setup to get your own credentials. None of these
need to happen before the code works locally against SQLite for testing, but
you'll need all of them for the real Telegram → Supabase → Gemini → Resend flow.

## 1. Supabase (database)

1. Go to https://supabase.com, sign in, click **New project**.
2. Pick any name/region, set a database password (save it - you'll need it below).
3. Once the project is ready: **Project Settings → Database → Connection string → URI**.
4. Copy the URI. It looks like:
   `postgresql://postgres.[project-ref]:[password]@aws-0-[region].pooler.supabase.com:5432/postgres`
5. In `backend/.env`, set `DATABASE_URL` to that string, but change the scheme
   from `postgresql://` to `postgresql+psycopg2://` (SQLAlchemy needs the driver
   name), e.g.:
   `DATABASE_URL=postgresql+psycopg2://postgres.[ref]:[password]@aws-0-[region].pooler.supabase.com:5432/postgres`
6. Run `cd backend && uv run python -m app.init_db` to create tables (each
   user's interest profile starts blank until they set it in Settings —
   there's no seeded default anymore, since Phase A made this multi-tenant).

## 2. Telegram bot (@BotFather)

1. In Telegram, open a chat with **@BotFather**.
2. Send `/newbot`, give it a name and a unique username (must end in `bot`).
3. BotFather replies with an API token like `123456789:AAExxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx`.
4. Put that in `backend/.env` as `TELEGRAM_BOT_TOKEN`.
5. Generate three more secrets and add them too (used in sections 5-7 below):
   ```bash
   python3 -c "import secrets; print(secrets.token_urlsafe(32))"   # run three times
   ```
   Set one each as `TELEGRAM_WEBHOOK_SECRET`, `SEND_LOOPWIRE_SECRET`, and `PROCESS_PENDING_SECRET`.
6. Open a chat with your new bot and send `/start` to confirm it responds
   (this works once the backend is running - see "Running everything locally" below).

## 3. Gemini API key (Google AI Studio)

1. Go to https://aistudio.google.com/apikey.
2. Click **Create API key** (choose or create a Google Cloud project if prompted).
3. Copy the key into `backend/.env` as `GEMINI_API_KEY`.
4. Free tier is generous and sufficient for personal send volume.

## 4. Resend (email delivery) - only needed for Phase 4

1. Go to https://resend.com and sign up.
2. **Domains → Add Domain**. Use a subdomain of a domain you already own, e.g.
   `loopwire.yourdomain.dev` (don't use your root domain - keeps this isolated
   from your main site's DNS).
3. Resend gives you SPF/DKIM TXT records to add at your DNS provider. Add them,
   then click **Verify** in Resend (propagation can take a few minutes to an hour).
4. Once verified, create an API key: **API Keys → Create API Key**.
5. Set in `backend/.env`:
   - `RESEND_API_KEY` = the key
   - `LOOPWIRE_FROM_EMAIL` = e.g. `hello@loopwire.yourdomain.dev`
6. There's no `LOOPWIRE_TO_EMAIL` anymore — since Phase A, each dispatch is
   emailed to the signed-in user's own Google account email, read straight
   off their `User` row.
7. Until this is configured, sends still work end-to-end (the bundle gets
   built and is visible on the dashboard) - `send_loopwire_email` just returns
   `None` and logs are skipped if the key isn't set, so you can develop
   everything else first and wire email up last.

## 5. Telegram webhook mode (how ingestion actually runs)

The bot no longer runs as a separate always-on polling process. It's a
`POST /telegram-webhook` route inside the FastAPI app - Telegram pushes each
update to that URL instead of the app repeatedly asking "anything new?".
This means the whole backend fits on Render's free **Web Service** tier
(background workers need a paid plan; a webhook-driven web service doesn't).

**How registration works**: on every startup, `app/main.py`'s lifespan calls
Telegram's `setWebhook` API pointed at `{BACKEND_BASE_URL}/telegram-webhook`.
So the only thing you need to do after deploying is make sure
`BACKEND_BASE_URL` is set to your real public HTTPS URL (Render gives you
`https://<service-name>.onrender.com`) - the app registers itself, no manual
`curl` needed in production.

**Verify it worked**, any time, from your machine:
```bash
curl -s "https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/getWebhookInfo" | python3 -m json.tool
```
Look for `"url"` matching your deployed URL + `/telegram-webhook`, and
`"last_error_message"` absent (if present, it'll tell you exactly what went
wrong - usually an expired/wrong URL or a firewall blocking Telegram's IPs).

**Testing this locally, before deploying** (this is what the PRD/task asked
for - confirm the webhook flow works before touching Render):
```bash
# terminal 1: run the backend as usual
cd backend && uv run uvicorn app.main:app --reload --port 8000

# terminal 2: expose it publicly
ngrok http 8000
# copy the https://xxxx.ngrok-free.dev URL it prints
```
Then set `BACKEND_BASE_URL=https://xxxx.ngrok-free.dev` in `backend/.env` and
restart the backend - the startup log will show `Telegram webhook registered
at https://xxxx.ngrok-free.dev/telegram-webhook`. Forward a link to your bot
on Telegram and it should reply instantly, same as before. When you're done
testing, either let the tunnel close (Telegram will just log delivery
failures against the dead URL until you register a new one) or explicitly
run `deleteWebhook`:
```bash
curl -s -X POST "https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/deleteWebhook"
```
then set `BACKEND_BASE_URL` back to `http://localhost:8000` (webhook
registration is skipped automatically for non-https URLs, it won't crash the app).

> Don't run `uv run python -m app.telegram_bot` (long-polling mode) at the
> same time a webhook is registered - Telegram only allows one delivery mode
> per bot token and will error with a "Conflict" if both are active.

## 6. Triggering sends: cron-job.org instead of an internal scheduler

`POST /send-digest?key=<SEND_LOOPWIRE_SECRET>` builds and sends a dispatch on
demand - this replaces relying on an internal always-on scheduler, since a
free-tier Render service that's spun down at 9am won't fire an in-process
cron job on time anyway. Instead, an external service pings the endpoint on
a schedule, which also happens to wake the service up if it was asleep.

1. Go to https://cron-job.org and create a free account.
2. **Create cronjob**:
   - URL: `https://<your-render-url>/send-digest?key=<SEND_LOOPWIRE_SECRET>`
   - Schedule: whatever you want (e.g. daily at 08:00 in your timezone)
   - Request method: `POST`
3. Save. That's the entire schedule - no code or redeploy needed to change
   the time later, just edit the cron job.
4. Test it immediately with the "Execute now" button in cron-job.org's UI,
   or manually: `curl -X POST "https://<your-render-url>/send-digest?key=<SEND_LOOPWIRE_SECRET>"`
   Expect `{"status": "sent", "items_count": N}` (or `"no_new_items"` if
   nothing's been summarized since the last dispatch).

If you'd rather self-host on something that supports always-on processes
(a paid Render plan, a VPS, etc.), `app/scheduler.py`'s `start_scheduler()`
is still there and does the same thing on an in-process cron - just call it
from `main.py`'s lifespan again. It's not wired up by default anymore.

## 7. Processing saved links: a second cron-job.org trigger, no worker service

The extraction + summarization step used to run as `app.worker` - an
always-on polling loop checking for pending items every 30s. That needed a
Render **background worker**, which isn't available on the free tier. It's
now `POST /process-pending?key=<PROCESS_PENDING_SECRET>` instead: one
extraction+summarization pass over whatever's pending, triggered the same
way as sends.

1. In cron-job.org, **create a second cronjob**:
   - URL: `https://<your-render-url>/process-pending?key=<PROCESS_PENDING_SECRET>`
   - Schedule: every 5-10 minutes (this one should run often - it's what
     makes a forwarded link show up "processed" soon after you send it,
     not just once a day like the digest)
   - Request method: `POST`
2. Test it: `curl -X POST "https://<your-render-url>/process-pending?key=<PROCESS_PENDING_SECRET>"`
   Expect `{"processed": N, "failed": M}` (`processed` = items attempted,
   `failed` = how many of those came back `extraction_failed` - paywall, no
   captions, etc. - not an error in the request itself).

With both cron jobs running, the entire pipeline - ingestion (webhook),
processing (this), and delivery (section 6) - is driven by HTTP calls to one
Render web service. No background worker, no always-on process, no paid tier
needed.

## 8. Deploying the backend to Render

1. Push this repo to GitHub (Render deploys from a git remote, not a local
   folder).
2. In Render: **New → Blueprint**, pick the repo. Render reads
   `backend/render.yaml` automatically and proposes one free web service,
   `loopwire-api`.
3. Render will prompt for every env var marked `sync: false` in that file
   before the first deploy. Fill in the values you already collected above:
   `DATABASE_URL`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET`,
   `SEND_LOOPWIRE_SECRET`, `PROCESS_PENDING_SECRET`, `GEMINI_API_KEY`,
   `RESEND_API_KEY`, `LOOPWIRE_FROM_EMAIL`.
4. Generate one more secret for `INTERNAL_AUTH_SECRET`:
   ```bash
   python3 -c "import secrets; print(secrets.token_urlsafe(32))"
   ```
   Keep this value handy — it has to be pasted into Vercel too (step 9),
   exactly matching, or every dashboard→backend API call will 401.
5. Leave `DASHBOARD_BASE_URL` and `BACKEND_BASE_URL` blank for now — you
   don't know either real URL yet. Deploy anyway; Render will build and
   assign you a URL like `https://loopwire-api-xxxx.onrender.com`.
6. Once it's live, go back into the service's **Environment** tab and set:
   - `BACKEND_BASE_URL` = that same `https://loopwire-api-xxxx.onrender.com` URL
     (the app pings Telegram's `setWebhook` against this on every startup —
     see section 5 — so it must point at itself)
   - `DASHBOARD_BASE_URL` = your Vercel URL from step 9 below (used only for
     the CORS allow-list; you'll circle back and set this after step 9)
   Saving env var changes triggers an automatic redeploy.
7. Confirm it's alive: `curl https://loopwire-api-xxxx.onrender.com/health`
   should return `{"status":"ok"}` (or similar 200).

> Render's free tier spins the service down after 15 minutes idle and takes
> ~30-60s to wake on the next request — this is why sends and processing are
> driven by external cron pings (section 6-7) rather than an internal timer:
> the ping itself wakes the service up.

## 9. Deploying the dashboard to Vercel

1. In Vercel: **Add New → Project**, import the same GitHub repo.
2. Set **Root Directory** to `dashboard` (the repo is a monorepo — Vercel
   needs to know the Next.js app isn't at the repo root).
3. Framework preset should auto-detect as Next.js; leave build/output
   settings default.
4. Before the first deploy, add these **Environment Variables** (Production,
   and Preview if you want PRs to build too):
   - `NEXT_PUBLIC_BACKEND_URL` = your Render URL from section 8
     (`https://loopwire-api-xxxx.onrender.com`)
   - `AUTH_SECRET` = generate with `npx auth secret` or
     `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`
   - `AUTH_GOOGLE_ID` / `AUTH_GOOGLE_SECRET` = your Google OAuth client
     credentials (see section 10 below if you don't have production ones yet)
   - `INTERNAL_AUTH_SECRET` = the **exact same value** you set on Render in
     step 8.4 — this is the shared secret the two services use to trust each
     other; a mismatch here fails silently as 401s on every dashboard page.
5. Deploy. Vercel assigns a stable URL immediately, e.g.
   `https://loopwire.vercel.app` (or your own custom domain if you attach one).
6. Go back to Render and set `DASHBOARD_BASE_URL` to this Vercel URL (step
   8.6) so CORS allows the dashboard to call the API.

## 10. Google Cloud Console — production OAuth redirect URI

The Google OAuth client you use for local dev (`http://localhost:3000`) also
needs your production URL registered, or sign-in will fail with
`redirect_uri_mismatch` once deployed.

1. Go to https://console.cloud.google.com/apis/credentials, open your
   existing OAuth 2.0 Client ID (the one whose ID/secret you're using locally).
2. Under **Authorized JavaScript origins**, add your Vercel URL, e.g.
   `https://loopwire.vercel.app`.
3. Under **Authorized redirect URIs**, add:
   `https://loopwire.vercel.app/api/auth/callback/google`
4. Save. This takes effect immediately — no redeploy needed on either side.
5. If your OAuth consent screen is still in **Testing** mode, only accounts
   you've explicitly added as test users can sign in — either add every
   tester's Google account under **Audience → Test users**, or publish the
   app (**Audience → Publish app**) if you want any Google account to be
   able to sign in.

## Running everything locally

From `backend/`:
```bash
uv run python -m app.init_db        # one-time: create tables
uv run uvicorn app.main:app --reload --port 8000   # API + webhook + /send-digest + /process-pending
```

From `dashboard/`:
```bash
npm install
npm run dev   # http://localhost:3000
```

Then: forward a link to your bot in Telegram (needs a webhook registered per
section 5, or run `uv run python -m app.telegram_bot` for plain polling
instead), hit `POST http://localhost:8000/process-pending?key=<PROCESS_PENDING_SECRET>`
to extract + summarize it immediately (instead of waiting on a cron or
running `app.worker` as a standalone loop - both still work if you prefer
them for local dev), then `POST http://localhost:8000/send-digest?key=<SEND_LOOPWIRE_SECRET>`
to force a send, and check the dashboard.
