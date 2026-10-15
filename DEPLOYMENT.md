# TrustRAG deployment and GitHub guide

Use this checklist when publishing TrustRAG as a public portfolio project.

## Before you publish the source

1. Create a new **empty** GitHub repository under the account that should own
   this project.
2. Do not add an API key, password, `.env`, SQLite database, user upload, or
   private PDF to the repository.
3. This workspace has no configured GitHub remote. Add your repository URL
   only after confirming the correct GitHub account and destination:

   ```powershell
   git remote add origin https://github.com/YOUR-ACCOUNT/YOUR-REPOSITORY.git
   git branch -M main
   git add .gitignore .dockerignore .env.example .github Dockerfile DEPLOYMENT.md README.md app.py answering.py auth.py combined_search.py create_sample_pdf.py evaluate_retrieval.py evaluation pdf_reader.py rag_engine.py render.yaml requirements.txt run_trustrag.bat search.py support.py tests ui.py web
   git status --short
   git diff --cached --check
   git commit -m "Build secure public TrustRAG research assistant"
   git push -u origin main
   ```

   Inspect `git status` before committing. `data/` is deliberately excluded
   from that command because local databases, uploads, and personal research
   must never be published. Add a demonstration PDF only after verifying that
   you own its distribution rights and that it contains no private information.

4. GitHub Actions runs unit tests on the push. Resolve failed checks before
   deployment.

## Deploy on Render

1. Create a Render account and connect the GitHub repository.
2. Create a **Blueprint** using the repository's `render.yaml`, or select
   Docker when creating a web service.
3. Ensure the service has a persistent disk mounted at `/var/data`; SQLite
   user accounts, sessions, and private passages must persist across deploys.
4. Set `TRUSTRAG_LLM_API_KEY` as a private Render environment secret. Never
   add it to `render.yaml`, GitHub Actions logs, or source files.
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
