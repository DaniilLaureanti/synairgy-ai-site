# SynAirgy Lead Engine

Internal lead-discovery engine for SynAirgy.

## What it does

`Google Places → public business website → evidence extraction → OpenAI qualification → Notion CRM → Telegram`

It **does not send cold email or automated sales messages**. It automates discovery, analysis, scoring, CRM entry, and notifications; the actual outreach remains manual.

## Default operating mode

- City: Hamburg
- Initial niche: barbershops
- 20 businesses per weekday run
- Only scores ≥ 75 are pushed as hot leads
- Schedule: 09:10 Europe/Berlin, Monday–Friday
- Duplicate detection: Google Place ID in Notion

## Required GitHub Actions secrets

Repository → Settings → Secrets and variables → Actions:

- `GOOGLE_PLACES_API_KEY`
- `OPENAI_API_KEY`
- `NOTION_TOKEN`
- `NOTION_DATA_SOURCE_ID`

Optional:
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

Optional repository variable:
- `OPENAI_MODEL` (defaults to `gpt-5-mini`)

## Notion

Create a Notion integration/token with the minimum needed content permissions, then share **SynAirgy Leads CRM** with that connection. Use the CRM's data source ID for `NOTION_DATA_SOURCE_ID`.

The engine writes Company/Status/Score, Offer/Price, Website/Instagram/phone/address, Problem/Evidence/Why Now, Opening/Call Script, Contact Channel, Legal Relevance, Place ID and fingerprint.

## Google Places

Enable Places API (New) and create a restricted API key. The engine uses Text Search (New) with a production field mask instead of `*`.

## OpenAI

The engine calls the Responses API with Structured Outputs. The model must return a strict JSON schema, which prevents brittle free-text parsing. It is instructed to use only supplied evidence, choose one problem and one offer, and never automate cold outreach.

## First safe run

GitHub → Actions → `SynAirgy Lead Engine` → Run workflow:
- dry_run = true
- query = `Barbershop in Hamburg`
- limit = `5`

Inspect the uploaded results artifact. Then run again with dry_run off.

## Tuning

Do not rotate all niches in the first week. Keep one niche long enough to measure:

`discovered → READY → contacted → interested → meeting → offer → won`

## Germany outreach guardrail

The engine deliberately does not automate cold advertising messages. Before a manual B2B call, use `Legal Relevance` as a reminder to verify the concrete business context. If a business objects, stop contacting it. This is an operational guardrail, not legal advice.
