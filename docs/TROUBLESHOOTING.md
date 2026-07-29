# Troubleshooting

## Dashboard does not open

Check container state:

```bash
docker compose ps
docker compose logs --tail 100 dashboard
docker compose logs --tail 100 api
```

If port `3000` is reserved, set `DASHBOARD_PORT=3200` and
`CORS_ORIGINS=http://localhost:3200` in `.env`, then rebuild the dashboard.

## Model test cannot reach the provider

- Confirm the model server is running.
- Check the base URL and model ID.
- In Docker, use a normal localhost URL in the UI; the backend translates it
  to `host.docker.internal`.
- Confirm the provider key has access to the selected model.
- Review the exact error shown on the Model connections page.

`401` indicates authentication failure, `403` indicates permission denial,
`404` usually indicates a wrong base URL or model endpoint, and `429` indicates
rate or quota exhaustion.

## Pipeline completes with little data

- Review Collections and the error center instead of relying only on the final
  summary.
- Confirm the company identity and discovered source profiles.
- Inspect robots decisions, HTTP status, retry state, and browser fallback
  counts.
- Add official RSS feeds or public source profiles where available.
- Increase crawl budgets gradually.

## Semantic retrieval is initially slow

The first request may download the local embedding model into the Docker
`model_cache` volume. Later requests reuse it.

## Database migration fails

```bash
docker compose logs --tail 150 api
docker compose exec postgres pg_isready -U osint -d osintdb
```

Do not delete volumes as a first response; doing so removes local intelligence
data. Back up PostgreSQL before manual migration repair.

## Browser collection fails

Rebuild the API image to ensure its Playwright version and Chromium installation
match:

```bash
docker compose build --no-cache api
docker compose up -d api
```

## Before sharing logs

Remove API keys, authorization headers, cookies, email addresses, private
company data, tunnel URLs, internal hostnames, and filesystem paths.
