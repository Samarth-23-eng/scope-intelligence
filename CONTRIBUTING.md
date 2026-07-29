# Contributing to Scope Intelligence

Thank you for helping build an evidence-first open-source intelligence
platform. Contributions of code, documentation, source adapters, tests,
research methods, accessibility improvements, and design work are welcome.

## Before you begin

- Read the [Code of Conduct](CODE_OF_CONDUCT.md).
- Search existing issues and pull requests before opening a duplicate.
- Never include API keys, cookies, private datasets, personal information, or
  material collected from access-controlled sources.
- Keep collection behavior lawful, rate-limited, and respectful of source
  policies. Features intended to bypass authentication, CAPTCHAs, paywalls, or
  technical access controls will not be accepted.
- For substantial changes, open a feature request first so implementation and
  data-model choices can be discussed before significant work begins.

## Development setup

The supported path uses Docker:

```bash
cp .env.example .env
docker compose up --build
```

Set a unique `POSTGRES_PASSWORD` in `.env`, then open
`http://localhost:3000`. See [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) for
native Python and Node.js setup.

## Making a change

1. Fork the repository and create a focused branch:

   ```bash
   git checkout -b feat/short-description
   ```

2. Keep the change small enough to review. Separate refactors from functional
   changes where practical.
3. Add or update tests for behavior changes.
4. Update documentation and `.env.example` for configuration changes.
5. Run the release checks:

   ```bash
   python -m pytest -q
   cd dashboard
   npm run lint
   npm run build
   ```

6. Open a pull request using the repository template.

## Contribution areas

- **Source adapters:** Prefer official APIs and public feeds. Adapters must
  isolate failures, record provenance, respect configured budgets, and avoid
  account automation.
- **AI agents:** Outputs must be schema-validated and grounded in supplied
  evidence IDs. Prompts must treat collected content as untrusted data.
- **Relationship intelligence:** Preserve evidence links, temporal state,
  contradiction signals, and deterministic confidence inputs.
- **Dashboard:** Maintain keyboard access, responsive layouts, clear empty and
  error states, and the existing restrained visual language.
- **Database changes:** Add a numbered, additive migration. Never edit a
  migration already released.

## Pull request expectations

A maintainable pull request:

- explains the user problem and the chosen solution;
- documents security, privacy, and collection-policy implications;
- includes tests or explains why tests are not applicable;
- does not introduce secrets, generated build output, or unrelated formatting
  churn;
- keeps public APIs and migrations backward compatible when possible.

Maintainers may ask for changes or close work that conflicts with the project's
ethical collection policy, evidence-first architecture, or roadmap.

## Reporting security issues

Do not open public issues for vulnerabilities or exposed credentials. Follow
[SECURITY.md](SECURITY.md).
