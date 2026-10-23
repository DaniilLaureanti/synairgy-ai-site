# Telegram owner console

The console can run **before Render**, on the existing Python project and local
SQLite directory. It needs a dedicated Telegram bot and an owner binding; no
OpenAI balance, Google key, SMTP or Stripe key is required to navigate it. It does
not start prospecting or send client email merely by opening the menu.

## Connect the bot

1. Create a dedicated SynAirgy Lead Engine bot with the official
   [BotFather](https://t.me/BotFather), or use an existing bot dedicated to this
   project. Do not share a bot already receiving updates for Crosspost or another
   application: a bot has one update stream.
2. Put `TELEGRAM_BOT_TOKEN` in the process's private environment and set
   `TELEGRAM_ENABLED=1`. Do not paste the token into Git, Notion, screenshots or
   logs. The program reads environment variables; it does not auto-load env files.
3. Set a known positive `TELEGRAM_OWNER_ID`, or run the pairing command below.
   Pairing displays a random private link valid for five minutes. Open it yourself
   and press Start. A bare `/start`, another person's ordinary message or a group
   message cannot claim ownership. The paired numeric ID is saved in SQLite;
   an explicit environment owner overrides it. Pairing will not replace an owner.

From `lead-engine/`, with Python 3.12 and installed requirements:

```sh
export PYTHONPATH=src
python -m synairgy.cli telegram-pair
python -m synairgy.cli telegram-setup
python -m synairgy.cli telegram
```

Skip `telegram-pair` if the owner ID is already configured. `telegram-setup`
checks bot identity/webhook state and installs command descriptions; it sends no
chat message. It refuses an active webhook instead of deleting another system's
integration. Once the polling process runs, the paired welcome/menu is delivered;
`/start` also opens it. A bounded diagnostic tick is `telegram --once`.

Do not save the pairing link in Notion. If pairing expires, generate a new link.
For deployment, either transfer a consistent private data backup or privately set
the confirmed owner ID; an empty cloud database does not inherit local pairing.
`doctor` reports environment configuration only; the actual API/CLI runtime also
resolves the owner saved by pairing.

## First menu

- **Обзор**: CRM counts, configuration presence, runtime flags and persisted pauses.
- **Отрасли**: source-backed hypotheses, mature cohort outcomes and latest intake
  shares; unknown costs remain unknown. This is not a profit forecast.
- **Лиды**: paginated companies, offer/problem/stage and a private preview link
  when the runtime has an HTTPS address.
- **Деньги**: confirmed gross payments, recorded costs/refunds. No invented profit.
- **Нужно решение**: blocked/dead jobs, uncertain SMTP sends, portfolio failures
  and failed Telegram deliveries.
- **Управление**: independently pause acquisition or outbound mail. Every change
  requires a ten-minute, one-use confirmation tied to the current control revision.
  Stale/replayed confirmations cannot override a newer decision.
- **Сегодня / Прошлая неделя**: observed daily counts and the previous completed
  Berlin calendar week; SMTP acceptance is not proof of reading/delivery.

Daily reports are queued once after `TELEGRAM_REPORT_HOUR` (default **19:00**),
weekly reports on Mondays after **09:00**, both Europe/Berlin including DST.
After the owner starts, payment, package, reply and terminal-job events generate
notifications. Uncertain email outcomes and blocked/failed research runs also
produce deduplicated notices. Periodic reports run only while the console process
is running; past offline days are not automatically backfilled.

## Operating boundaries

- Only the configured owner in their private chat can read or mutate state.
  Usernames, group membership, button visibility and AI output grant no access.
- Only pause/resume controls mutate commercial behavior. Navigation does not
  invoke AI, discover companies, approve/send client messages or create charges.
- Acquisition pause applies to discovery/seed intake and portfolio research/intake.
  Existing processing, follow-ups and paid fulfillment can continue. Send pause
  is checked in the actual SMTP claim path. An already started operation may finish.
- Resume only removes a pause: it cannot enable `OUTREACH_ENABLED`, live billing,
  bypass approval, suppressions, contact verification or daily limits.
- The core uses schema **v3**, an additive migration from v1/v2. Back up consistently
  before upgrade, restore-test, and do not roll an old binary onto a new database.
- Update receipts, offsets, confirmations, pause revisions, notification outbox and
  report/event dedupe survive restarts. Leases fence stale pollers/delivery commits.
- Telegram message delivery is at-least-once: a crash/ambiguous network response
  can duplicate a notification. Business control changes remain idempotent.
  Retries are bounded to five attempts and honor a bot-wide `retry_after` pause.
  A permanent rejection becomes a failed delivery shown in **Нужно решение**.
- Token-bearing URLs and raw request exceptions are not logged. Redirects are
  refused; only fixed Bot API methods are allowed.
- Client mailbox reading/replying through Telegram, free-form AI commands,
  domain publication and automatic cost accounting remain separate integrations.

## Later on Render

The same `serve` process starts the polling thread when Telegram is enabled and
the token/owner are configured. No Telegram webhook/domain or second service is
needed. Keep exactly one app worker and one persistent SQLite host. A database
lease prevents a second local/CLI poller consuming the same bot concurrently.
If it stays online locally, Render is unnecessary for the initial console test;
Render later supplies the persistent, continuously running environment.

The admin API also exposes authenticated `GET /api/controls` and
`POST /api/controls/pause` with `target` (`acquisition` or `outreach`) and a strict
boolean `paused`. These use the same state as Telegram. Pausing new work never
disables payment webhooks or durability.

References checked 2026-10-23: [Bot API](https://core.telegram.org/bots/api),
[bot features](https://core.telegram.org/bots/features).
