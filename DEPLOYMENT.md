# TrustRAG deployment guide

The source repository is already public at
<https://github.com/BBhanuKiran/TrustRAG>. The FastAPI website currently runs
locally; this guide covers deploying it as a hosted service.

## Before hosting

1. Create or sign in to a Render account and connect the GitHub repository.
2. Review Render's current service and persistent-disk charges before creating
   resources. Do not proceed unless you approve any displayed costs.
3. Keep API keys, passwords, `.env`, SQLite databases, user uploads, and
   private PDFs out of GitHub.

## Deploy on Render

1. In Render, create a **Blueprint** from the GitHub repository and use
   `render.yaml`.
2. Review the resources and displayed costs, then create the service only if
   you approve them.
3. Add `TRUSTRAG_LLM_API_KEY` as a private service environment variable. Never
   put it in the repository, logs, or browser code.
4. Ensure the service has a persistent disk mounted at `/var/data`; SQLite
   user accounts, sessions, and private passages must persist across deploys.
5. Verify `TRUSTRAG_SECRET_KEY` has at least 32 characters. The Render
   blueprint requests a generated secret; keep that secret stable across
   deploys.
6. Confirm `TRUSTRAG_ENV=production`, provider URL, and model settings.
7. Deploy and confirm `/health` responds with `{"status":"ok"}`.
8. Test signup, login, upload, citation-backed answer generation, deletion,
   logout, and isolation with a second account using non-sensitive sample PDFs.
9. Review the AI provider's retention terms and the hosting plan's storage,
   backup, logging, and costs before inviting public users.
10. Attach a domain you own in Render. Add a sitemap and additional SEO work
    only once the final domain is known. No search engine can be forced to
    index a new domain immediately.

## Hosting notes

- `render.yaml` selects a small paid/starter service and persistent disk.
- The sentence-transformer model is downloaded/cached in `/var/data` on first
  use. Allow for model initialization time and persistent-disk usage.
- Production runs one process because SQLite is not configured for concurrent
  multi-process writes and the rate limiter is in memory.
- Local Ollama is a development fallback only. Production requires a hosted
  OpenAI-compatible API key because the deploying user's desktop is not
  available to the server.
- The provider receives questions and retrieved text excerpts. The app sends
  no key to the browser; public deployment still has third-party processing.
- The in-memory rate limiter is a basic single-process safeguard, not a
  substitute for provider-side quotas, edge rate limits, monitoring, or a
  distributed abuse-control service.
- Password-reset email, verified email, account deletion, billing, user
  agreements, formal privacy notice, backups/restores, and security audit are
  not included. Plan those before treating the app as a production SaaS.
