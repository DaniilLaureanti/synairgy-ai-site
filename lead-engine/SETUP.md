# Production activation checklist

## Confirmed work

- Existing repository: DaniilLaureanti/synairgy-ai-site, original base 0a11dddc.
- The old scheduled job failed immediately because GOOGLE_PLACES_API_KEY was
  absent. Logs also showed other integration variables empty.
- A new OpenAI key was created through the encrypted local-write flow.
- The bounded live probe returned HTTP 429 / credit_balance_exhausted.
  That is API billing exhaustion, not a transient throughput limit.
- The Stripe connector was reconnected to 404dream.info (live account). No live
  product, payment, subscription or customer was created during development.

## Before live activation

1. Select an authorized persistent Python/Docker host. The current GitHub Pages
   marketing site cannot host this API, SMTP connection or persistent database.
2. Deploy the container with a persistent volume, TLS, a long ADMIN_TOKEN,
   backups, network limits and authenticated administrative access.
3. Supply the new OpenAI key through runtime secrets and add API balance:
   https://platform.openai.com/settings/organization/billing
   ChatGPT subscriptions and API billing are separate. Keep the existing
   gpt-5-mini configuration; for small future experiments gpt-6-luna is also
   a starter-model option, not an automatic migration.
4. Configure Google Places API (New) and its restricted key, or import explicit
   company seeds. A functioning OpenAI key alone cannot supply Places access.
5. Configure the sending mailbox, SMTP credentials, domain authentication and a
   sender postal address. Verify the actual recipient before enabling outreach.
   OUTREACH_ENABLED remains 0 until this is ready.
6. Configure a separate Stripe sandbox with a restricted API key. Set
   STRIPE_API_KEY and STRIPE_WEBHOOK_SECRET in server secrets. A ChatGPT Stripe
   connector does not inject a server API key into the Python application.
7. Register /webhooks/stripe and test signed completed, asynchronous success,
   failure, duplicate and wrong-amount events before any live payment.
8. Confirm deliverable scope, tax/invoicing setup and customer onboarding.
   A generated ZIP is not a deployed customer website.
9. Configure an authorized domain/deployment adapter for final delivery. Domain
   purchases, DNS changes and customer production access are not fabricated or
   performed without those credentials.
10. Put LEAD_ENGINE_URL in GitHub variables and LEAD_ENGINE_ADMIN_TOKEN in the
    lead-engine environment's secrets. Run workflow_dispatch with dry_run=true,
    then a bounded run. Set ENGINE_ENABLED=1 only after checks succeed.

## Rollback / recovery

- Stop the scheduler or set ENGINE_ENABLED=0.
- Set OUTREACH_ENABLED=0 on the runtime as the send kill switch.
- Keep the persistent volume intact; deploy the preceding code version.
- For transient task failures, inspect the event history and job error code.
  Retry blocked/dead tasks explicitly after correcting their root cause.
- For a pre-crash 'sending' message, reconcile actual mailbox/server delivery.
  The system never automatically retries uncertain SMTP sends.
- Use a consistent backup and a restore test before every schema migration.

## Still outside this release

Phone/social adapters, mailbox ingestion, AI negotiation, customer-domain
publishing and recurring subscriptions need implementation and live verification.
Do not describe this release as a fully autonomous production business.
