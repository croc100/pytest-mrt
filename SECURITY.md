# Security Policy

## Supported versions

| Version | Security fixes |
|---------|---------------|
| 0.6.x   | ✅ Active      |
| < 0.6   | ❌ No longer supported |

## Reporting a vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

Report privately via [GitHub Security Advisories](https://github.com/croc100/pytest-mrt/security/advisories/new).

Include:
- Description of the vulnerability
- Steps to reproduce
- Impact assessment (what an attacker could do)
- Suggested fix, if you have one

### Response SLA

| Severity | Initial response | Fix target |
|----------|-----------------|------------|
| Critical | 24 hours        | 7 days     |
| High     | 48 hours        | 14 days    |
| Medium   | 5 business days | 30 days    |
| Low      | 10 business days| Next release|

We will acknowledge receipt, keep you updated on progress, and credit you in the release notes unless you prefer to remain anonymous.

## Scope

pytest-mrt is a **testing tool**. Its attack surface is narrow:

**In scope:**
- Code execution via crafted migration files (AST parsing vulnerabilities)
- Credential exposure via config file handling
- SQL injection via test database operations

**Out of scope:**
- Issues in your own migration files (by design, the tool reads and executes them)
- Vulnerabilities in optional dependencies (psycopg2, PyMySQL, anthropic) — report to those projects
- "pytest-mrt lets me run SQL against a database I configured" — that's intended behavior

## Security model

pytest-mrt:
- **Does not make any network requests** outside of connecting to the database URL you provide
- **Does not collect or transmit any data** from your migrations or database
- **Only reads migration files** using Python's `ast` module (no `eval` or `exec`)
- **Should only run against a test database** — never point it at production

The `mrt explain` command (optional, `pip install pytest-mrt[ai]`) sends migration source code to the Anthropic API. Do not use it if your migrations contain secrets.

## Audit & compliance

- License: MIT (see `LICENSE`)
- No telemetry, no analytics, no phone-home
- All dependencies are listed in `pyproject.toml` and pinned in your lock file
- Static analysis (`mrt check`) operates entirely offline

For compliance questionnaires or vendor security reviews, open a [GitHub Discussion](https://github.com/croc100/pytest-mrt/discussions).
