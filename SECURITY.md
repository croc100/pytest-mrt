# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability, please **do not** open a public issue.

Email: open a private [GitHub Security Advisory](https://github.com/croc100/pytest-mrt/security/advisories/new)

We will respond within 48 hours.

## Scope

pytest-mrt is a testing tool that runs against a database you provide.
It does not make network requests, collect data, or run code outside of your test environment.

**Always point pytest-mrt at a test database, never production.**
