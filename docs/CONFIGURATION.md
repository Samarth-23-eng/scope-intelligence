# Configuration

Copy `.env.example` to `.env`. Blank optional credentials disable only their
associated integrations.

## Core services

| Variable | Purpose |
| --- | --- |
| `POSTGRES_PASSWORD` | Required Docker database password |
| `POSTGRES_URL` | Native backend PostgreSQL connection |
| `REDIS_URL` | Pipeline status and coordination |
| `QDRANT_URL` | Semantic evidence index |
| `CORS_ORIGINS` | Comma-separated browser origins allowed by the API |
| `DASHBOARD_PORT` | Local host port for the dashboard |

## Model connection

The preferred setup is the dashboard's **Model connections** page.

Environment fallback:

| Variable | Purpose |
| --- | --- |
| `LLM_PROVIDER` | `openai`, `openrouter`, `anthropic`, `google`, `ollama`, `lmstudio`, or `openai_compatible` |
| `LLM_BASE_URL` | Provider or local model API base URL |
| `LLM_MODEL` | One model ID shared by every agent |
| `LLM_AUTH_MODE` | `api_key`, `bearer`, or `none` |
| `LLM_API_KEY` | Provider credential; keep only in `.env` |
| `LLM_MASTER_KEY` | Optional Fernet key for encrypted saved credentials |
| `LLM_REQUEST_TIMEOUT_SECONDS` | Completion request timeout |

If no `LLM_MASTER_KEY` is supplied, Docker creates a private key in the
`llm_secrets` volume. Losing this key makes saved credentials unreadable.

## Collection budgets

`CRAWLER_*` variables control page count, depth, concurrency, retries, document
size, PDF pages, sitemap limits, browser fallbacks, and recovery behavior.
Larger values increase bandwidth, storage, runtime, and block risk. Prefer
better URL scoring and source adapters over unbounded crawling.

## Optional public sources

| Variable | Integration |
| --- | --- |
| `NEWSAPI_KEY` | NewsAPI ingestion |
| `YOUTUBE_API_KEY` | YouTube Data API metadata and optional comments |
| `GITHUB_TOKEN` | Higher GitHub public API allowance |
| `ENABLE_JOB_SCRAPER` | Multi-source public job search |
| `ENABLE_LINKEDIN_SCRAPER` | Experimental public job results; off by default |

Use short-lived, least-privilege, read-only credentials. Never expose `.env`
through a tunnel or include it in logs and bug reports.

## Monitoring

The global scheduler can be disabled with
`MONITORING_SCHEDULER_ENABLED=false`. Individual company monitoring remains
controlled from each company workspace.
