# Production setup checklist

## 1 — OpenAI
Create a project API key named `SynAirgy Lead Engine` and store it in GitHub Actions as `OPENAI_API_KEY`.

## 2 — Google Places
Create a Google Cloud API key with Places API (New) enabled. Restrict the key and store it as `GOOGLE_PLACES_API_KEY`.

## 3 — Notion
Create a Notion internal integration, share `SynAirgy Leads CRM` with it, and save the token as `NOTION_TOKEN` and the CRM data source ID as `NOTION_DATA_SOURCE_ID`.

## 4 — Telegram (optional)
Create a bot with BotFather, send it one message, get your chat ID, then store `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`.

## 5 — First safe run
GitHub → Actions → `SynAirgy Lead Engine` → Run workflow: query `Barbershop in Hamburg`, limit `5`, dry run `true`. Inspect the uploaded `results.json`.

## 6 — First CRM run
Repeat with dry run off. Weak leads become SKIP/REVIEW; strong leads become READY; duplicates are ignored.

## 7 — Daily rhythm
1. Open Notion view `🔥 High Score`.
2. Read the evidence, not only the score.
3. If the problem is real, tick `Approved`.
4. Contact manually.
5. Move the card through the pipeline.
6. Set the next follow-up immediately.

After ~100 reviewed leads, tune the threshold and prompt from real conversion data.
