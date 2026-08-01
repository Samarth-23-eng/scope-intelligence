# Changelog

All notable changes will be documented here. The project follows semantic
versioning where practical.

## [Unreleased]

### Added

- Experimental pre-alpha Social Collection Studio with bounded YouTube channel,
  video, transcript, and public-comment evidence capture.
- Experimental pre-alpha Deep Research Lab with isolated Tor routing, multiple
  hidden-service search engines, GET-only collection, strict budgets, explicit
  operator acknowledgement, and review-required evidence.
- A multi-page Settings hub for AI routing, collection budgets, and encrypted
  connector credentials.
- Prominent experimental-content warnings, Deep Research operating guidance,
  and attribution to Robin by Apurv Singh Gautam.
- Public open-source governance, contribution, support, security, and issue
  workflows.
- Provider-neutral shared LLM gateway with encrypted BYOK storage.
- Model Connections dashboard for cloud, local, and OpenAI-compatible models.

### Security

- Upgraded Requests to 2.33.0 to resolve PYSEC-2026-2275, an insecure temporary
  file reuse issue in ZIP extraction.

## [0.1.1] — 2026-07-29

### Security

- Upgraded vulnerable Python and dashboard dependencies, including the PDF
  parser, cryptography stack, FastAPI/Starlette stack, and development tooling.
- Removed unused vulnerable LangChain packages and pinned JobSpy to an immutable
  upstream revision that permits a patched Markdownify release.
- Constrained generated-report paths to the private report workspace and removed
  server filesystem paths from API responses.
- Prevented internal indexing diagnostics from leaking through API responses and
  hardened public-profile hostname validation.
- Added Python and dashboard dependency audits to continuous integration.

## [0.1.0] — 2026-07-29

### Added

- Name-first company discovery and identity context.
- Durable hybrid collection campaigns with resumable crawl frontiers.
- Website, feed, news, job, GitHub, YouTube metadata, transcript, and public
  source-profile collection.
- Immutable evidence versions, chunks, hybrid retrieval, and source health.
- Citation-bound summaries, signals, predictions, and investigations.
- Relationship aliases, temporal observations, corroboration, contradiction,
  freshness, risk, and graph metrics.
- Continuous monitoring, claim verification, and fused situation timeline.
- PDF reporting, alert evaluation, and optional email/Discord delivery.
- Multi-page Next.js operator workspace with evidence, intelligence,
  relationships, research, reports, operations, and model settings.

[Unreleased]: https://github.com/Samarth-23-eng/osint-platform/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/Samarth-23-eng/osint-platform/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/Samarth-23-eng/osint-platform/releases/tag/v0.1.0
