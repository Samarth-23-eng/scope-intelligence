# Deep Research Lab

Deep Research Lab is an optional local experiment for searching publicly
reachable Tor hidden services during authorized company research. It is
disabled by default and is not part of the normal collection pipeline.

> **Pre-alpha content warning:** searches may surface explicit, graphic,
> sexual, violent, hateful, extremist, fraudulent, unlawful, malicious, or
> otherwise disturbing material. Results are unverified and may be false.
> Operate in an isolated environment and review every item before use.

## Safety boundary

- Version-3 `.onion` pages only
- HTTP `GET` requests only
- No authentication, forms, uploads, or file downloads
- No arbitrary target URLs and no recursive site crawling
- Explicit authorization acknowledgement for every run
- Strict result, page, byte, delay, and time budgets
- Credential-like text is redacted before storage
- Evidence is assigned low confidence and marked as unverified
- Source text is treated as untrusted data, never as agent instructions

## Local setup

Start the isolated Tor service:

```bash
docker compose --profile deep-research up -d tor
```

Open **Settings → Collection**, enable **Deep Research Lab**, and save. In a
company dossier, open **Collection → Deep Research** and use **Test Tor route**
before the first run.

Stop the optional service when it is no longer needed:

```bash
docker compose --profile deep-research stop tor
```

The implementation is inspired by Robin's modular Tor search and scraping
workflow. Attribution is recorded in `THIRD_PARTY_NOTICES.md`.
