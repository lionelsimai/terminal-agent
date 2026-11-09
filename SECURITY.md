# Security Policy

## Supported versions
| Version | Supported |
|---|---|
| 0.1.x | Yes |

## Reporting a vulnerability
Do **not** open a public issue for security problems.
Email **lionel@theaicapitol.com** with details and steps to reproduce.
We aim to acknowledge within 72 hours.

## Design notes
This project is built to fail closed: sandboxes, allowlists, and auth checks
deny by default. Never run it with broader permissions than you need.
