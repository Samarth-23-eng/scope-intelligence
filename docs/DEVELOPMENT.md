# Development

## Docker workflow

Docker is the closest match to the supported runtime:

```bash
cp .env.example .env
docker compose up --build
```

Use a unique `POSTGRES_PASSWORD`. The API applies pending SQL migrations on
startup.

Useful commands:

```bash
docker compose ps
docker compose logs -f api
docker compose logs -f dashboard
docker compose up -d --build api dashboard
```

## Native backend

Use Python 3.12:

```bash
python -m venv .venv
python -m pip install -r requirements-dev.txt
python -m playwright install chromium
```

Configure PostgreSQL, Redis, and Qdrant URLs in `.env`, then run:

```bash
python -m uvicorn api.main:app --reload
```

Backend checks:

```bash
python -m pytest -q
python -m compileall -q agents alerts api config db intelligence llm_gateway reports
```

## Native dashboard

Use Node.js 24:

```bash
cd dashboard
cp .env.local.example .env.local
npm ci
npm run dev
```

Dashboard checks:

```bash
npm run lint
npm run build
```

## Database migrations

Migrations live in `db/migrations/` and are applied in filename order.

- Add the next three-digit migration number.
- Make released migrations additive and idempotent where possible.
- Never edit a migration already included in a release.
- Add migration-structure assertions to `tests/test_migrations.py`.
- Define foreign-key deletion behavior explicitly.

## Testing source adapters

Tests must not depend on live third-party services. Use fixtures and mocked
responses to cover:

- successful collection;
- empty results;
- rate limits and temporary failures;
- forbidden and not-found responses;
- malformed content;
- deduplication and provenance;
- bounded retries and partial pipeline completion.

Never place a real token or private response body in a fixture.

## Branch and commit style

Suggested branch prefixes:

- `feat/`
- `fix/`
- `docs/`
- `refactor/`
- `test/`
- `security/`

Use imperative, focused commit messages such as
`Add source health diagnostics for RSS feeds`.
