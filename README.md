# TrustRAG

**Research with receipts.** TrustRAG is a full-stack, account-isolated research
assistant for searchable PDFs. It retrieves relevant passages, answers from
those passages, shows source pages, and abstains when the available evidence is
too weak.

## Product

TrustRAG helps people inspect policies, handbooks, technical manuals, reports,
and research papers without treating an AI response as unquestionable truth.
Its central workflow is:

1. Create an account and upload a text-searchable PDF.
2. Ask a focused question about your own library.
3. Inspect the answer's evidence cards, source filename, and page.
4. Confirm consequential claims against the original source.

The website also includes a practical user manual, privacy and limitations
pages, a theme switch, a searchable document library, downloadable research
transcripts, and an automated support assistant. The help assistant answers
from a curated copy of this manual and abstains when it cannot match a topic;
it does not claim to be human or perfectly accurate.

## Start locally on Windows

Requirements:

- Python 3.11 or newer.
- Ollama installed separately for local model answers.
- Internet access the first time the embedding model is downloaded.

### 1. Start the website

Double-click [`run_trustrag.bat`](./run_trustrag.bat), or run from PowerShell:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
ollama pull llama3.2:3b
.\.venv\Scripts\python.exe -m uvicorn app:app --host 127.0.0.1 --port 8765
```

Open [http://127.0.0.1:8765](http://127.0.0.1:8765). Interactive API
documentation is at [http://127.0.0.1:8765/docs](http://127.0.0.1:8765/docs).
Local development uses Ollama when a hosted-provider key is not configured.

### 2. Create your private account

Select **Create your private workspace**. Accounts use a normalized email
address and a password of at least 12 characters. This portfolio build does not
include password-reset email; keep your password safe.

### 3. Index a source

Go to **My library**, choose one or more text-based PDF files, and select
**Upload and index**. Limits are 20 MB and 500 pages per PDF, 100 PDFs per
account, and 5,000 indexed passages per account. Scanned/image-only PDFs need
OCR before upload.

### 4. Research and verify

Ask a specific question in **Workspace**. Open the returned evidence cards to
inspect the exact retrieved text, source name, page, and relevance score. Use
**Export this conversation** to download a Markdown transcript. Remove
documents from **My library** when they are no longer needed.

The **User manual** explains the purpose, quick start, answer pipeline, data
handling, accuracy limitations, and troubleshooting. **Help chat** answers
common usage questions from the manual; questions outside the manual receive
an explicit fallback.

## AI provider and settings

For local development, TrustRAG sends questions to Ollama on
`http://127.0.0.1:11434` by default. The default local answer model is
`llama3.2:3b`; install it with `ollama pull llama3.2:3b`.

For public hosting, set secrets on the server rather than in browser code,
committed files, or a public GitHub repository:

| Environment variable | Purpose |
| --- | --- |
| `TRUSTRAG_ENV` | Set to `production` for production settings. |
| `TRUSTRAG_SECRET_KEY` | Stable, randomly generated session-signing secret; at least 32 characters. |
| `TRUSTRAG_LLM_API_KEY` | Hosted OpenAI-compatible provider key. Required for hosted answers. |
| `TRUSTRAG_LLM_BASE_URL` | Provider API base URL, default `https://api.openai.com/v1`. |
| `TRUSTRAG_LLM_MODEL` | Hosted model name, default `gpt-4o-mini`. |
| `TRUSTRAG_DATABASE_PATH` | SQLite database file path. |
| `TRUSTRAG_DATA_DIR` | Persistent storage directory for the SQLite database and embedding cache. |
| `TRUSTRAG_OLLAMA_URL` | Optional local Ollama URL, default `http://127.0.0.1:11434`. |
| `TRUSTRAG_OLLAMA_MODEL` | Local development model, default `llama3.2:3b`. |
| `TRUSTRAG_EMBEDDING_MODEL` | Sentence-transformer model, default `sentence-transformers/all-MiniLM-L6-v2`. |

Copy [`.env.example`](./.env.example) to `.env` for local configuration.
`.env` is ignored by Git. A hosted provider may process the question and
retrieved PDF passages; review its data-retention terms and only upload content
you are authorized to share.

## Account separation and operational safeguards

- Passwords are salted and hashed with scrypt; raw passwords are not stored.
- Sessions use a signed, HTTP-only, same-site cookie, can be revoked at logout,
  and expire after seven days.
- Production cookies are marked secure. Production startup fails without a
  sufficiently long `TRUSTRAG_SECRET_KEY`.
- Documents, passage search, deletion, and answers are scoped to the
  authenticated owner in the SQLite queries.
- Users can delete their account, its active sessions, and indexed documents.
- Registration/login and per-account upload/answer requests are rate-limited.
- PDFs have per-file size/page limits and per-account document/passage limits.
- HTTP security headers restrict framing, browser capabilities, and script
  sources. Authenticated/private API responses are not cacheable.
- The app has a root site, robots rules, server-side SEO metadata, OpenAPI docs,
  and a health endpoint.

This is a portfolio application, not a professionally audited or
high-availability service. SQLite and the in-memory rate limiter suit a small,
single-instance deployment. Production operators must protect persistent
storage, back up the database, monitor the host, set secrets, and review the
selected AI provider's privacy terms.

## Deploy and publish

The repository includes a production Dockerfile, persistent-disk Render
blueprint, Docker ignore rules, and GitHub Actions checks. To create a public
deployment:

1. Create an empty GitHub repository under your own GitHub account.
2. Push this project's files to that repository.
3. Create a Render account and create a web service from the GitHub
   repository (or apply [`render.yaml`](./render.yaml)).
4. Supply a private `TRUSTRAG_LLM_API_KEY` in the Render service settings.
   Render generates `TRUSTRAG_SECRET_KEY` from the blueprint.
5. Keep the mounted persistent disk enabled and wait for the deployment health
   check to pass.
6. Add the resulting hosted URL to your portfolio. A custom domain can be
   attached in the hosting provider's settings.

**Publishing limitation in this working copy:** it currently has no Git
commits and no configured GitHub remote. Therefore no public source URL, public
website URL, or search-engine listing can be created from this workspace alone.
The exact GitHub repository URL/account is needed before pushing to your
account. Search engines also decide independently whether and when a site is
indexed; typing “TrustRAG” into search is not the same as registering a
domain, and indexing cannot be guaranteed.

See [DEPLOYMENT.md](./DEPLOYMENT.md) for the step-by-step GitHub and hosting
checklist.

## API

The website API is same-origin. Open `/docs` for interactive API documentation.

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Liveness check. |
| `GET` | `/api/status` | Public deployment/provider readiness without revealing the API key. |
| `POST` | `/api/auth/register` | Create an account and sign in. |
| `POST` | `/api/auth/login` | Sign in to an existing account. |
| `GET` | `/api/auth/me` | Return the signed-in account. |
| `DELETE` | `/api/auth/me` | Delete the account, sessions, and owned documents. |
| `POST` | `/api/auth/logout` | Revoke the active session. |
| `POST` | `/api/support` | Search the curated user manual. |
| `GET` | `/documents` | List the signed-in user's documents. |
| `POST` | `/documents` | Upload and index a PDF. |
| `DELETE` | `/documents/{document_id}` | Delete an owned document. |
| `POST` | `/search` | Search only owned PDF passages. |
| `POST` | `/ask` | Generate an evidence-grounded answer or abstain. |

Private endpoints require the HTTP-only session cookie. `/ask` sends relevant
passages to the server-configured provider and validates citation identifiers
against retrieved evidence. That validation does not prove that a cited source
entails every generated statement. No “100% accurate” guarantee is made.

## Tests and checks

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe evaluate_retrieval.py
```

Tests cover account creation/login/logout, session expiry/revocation,
authentication boundaries, user data isolation, PDF limits/processing,
retrieval/citations, provider responses, and manual-based support. The test
suite uses deterministic local fakes; it does not call a paid provider.
GitHub Actions runs the unit tests on pushes and pull requests.

## Project layout

```text
app.py                  FastAPI site, authentication, private APIs, safety headers
auth.py                 Account storage, scrypt passwords, signed revocable sessions
answering.py            Local/hosted answer providers, citation checks, abstention
rag_engine.py           PDF processing, embeddings, isolated SQLite retrieval
support.py              Curated user-manual support answers
web/                    Responsive premium website, accessible theme, manual, help
Dockerfile              Production container
render.yaml             Example persistent-disk hosted deployment
.github/workflows/ci.yml Automated unit-test checks
tests/                  Auth, API isolation, retrieval, and answer tests
evaluation/              Small retrieval evaluation dataset
run_trustrag.bat         Windows local-development launcher
```
