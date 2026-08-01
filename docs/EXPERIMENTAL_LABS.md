# Experimental Labs: Pre-alpha Safety Notice

Social Collection Studio and Deep Research Lab are pre-alpha test features.
They are provided for local evaluation by operators conducting lawful,
authorized research. They are not production-ready intelligence services.

## Content warning

Experimental collectors may surface explicit, graphic, sexual, violent,
hateful, extremist, fraudulent, malicious, unlawful, false, or otherwise
disturbing material. Search results, public comments, transcripts, and hidden
services are controlled by third parties and are not safety-vetted by Scope.

Do not assume that a collected statement is true. Anonymous and user-generated
sources require independent corroboration before they are used in analysis or
reporting.

## Operator checklist

- Confirm that the research purpose and target are lawful and authorized.
- Use an isolated local environment and never expose the dashboard publicly.
- Start with the smallest practical result, page, comment, and time budgets.
- Do not enter credentials into collected pages or interact with their forms.
- Do not download or redistribute unknown files or explicit source material.
- Review evidence before allowing it to influence claims or relationships.
- Delete content that is irrelevant, unsafe, or no longer required.
- Follow applicable law, source policies, data protection, and retention rules.

## Feature boundaries

### Social Collection Studio

The current reference connector supports bounded public YouTube collection.
Comments and transcripts can contain unsafe material. Commenter identity is
minimized, but the content itself remains untrusted.

### Deep Research Lab

The lab accepts research queries rather than arbitrary target URLs. It permits
only version-3 `.onion` HTTP(S) targets discovered through configured search
engines and performs GET-only text collection. It does not authenticate,
submit forms, upload data, download files, or recursively crawl sites.

Deep Research evidence receives a low default confidence, an anonymous-source
trust tier, a prompt-injection boundary, and a mandatory review marker.

## Reporting problems

Report security issues privately using [SECURITY.md](../SECURITY.md). Do not
attach explicit content, live hidden-service data, credentials, or private
investigation records to a public GitHub issue.
