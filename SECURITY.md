# Security Policy

## Supported versions

| Version | Supported |
| --- | --- |
| Latest release | Yes |
| `main` | Best effort |
| Older releases | No |

## Supported deployment

Scope Intelligence is designed for a private, local workspace. Docker Compose
binds the dashboard and API to `127.0.0.1`. The current release does not include
multi-user authentication and must not be exposed directly to the internet.

If you deploy behind a network boundary, use TLS, authentication, request
limits, restrictive firewall rules, a reviewed reverse proxy, and independent
backup and monitoring controls.

## Reporting a vulnerability

Use GitHub's private vulnerability reporting for this repository. Do not open a
public issue containing exploit details, credentials, private company data, or
personal information.

Include:

- affected version or commit;
- component and deployment model;
- minimal safe reproduction;
- practical impact;
- suggested mitigation, if known.

You should receive an acknowledgement within seven days. Timelines for a fix
depend on severity, reproducibility, and maintainer availability.

## Credential handling

- Copy `.env.example` to `.env`; never commit `.env`.
- Prefer short-lived, least-privilege, read-only credentials.
- Protect `LLM_MASTER_KEY` and the Docker `llm_secrets` volume.
- Never put credentials in investigation prompts, company records, URLs,
  screenshots, reports, fixtures, issues, or logs.
- Revoke a credential immediately if it appears in a chat, terminal transcript,
  screenshot, commit, or build output.

Deleting a secret from the latest revision is insufficient when it remains in
Git history. Revoke it, replace or rewrite the history, and run a full-history
secret scan.

## Scope

High-priority reports include authentication or authorization bypass, remote
code execution, credential disclosure, cross-company data exposure, unsafe
deserialization, server-side request forgery, prompt-driven external actions,
and failures in secret encryption or redaction.

Automated scanning that degrades services, testing against third-party sources,
and reports based solely on unsupported scanner output are out of scope.
