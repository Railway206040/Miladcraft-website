# MILAD CRAFT Website

A Persian RTL, responsive Flask website for the MILAD CRAFT Minecraft server.

## Features
- Blue-and-black public homepage and server connection details.
- Server online/offline/player count check via the public mcsrvstat.us status API.
- Telegram community link: https://t.me/Milad_craft (configurable with TELEGRAM_URL).
- Staff login with hashed passwords and role-based permissions.
- Builder project claiming; H-Builder project creation and warnings.
- Developer/Owner full staff controls and rich-text Academy publishing.
- Academy editor supports bold, italic, underline, headings, ordered/unordered lists, quotes, hyperlinks, and images.
- Rich text is sanitized on the server using Bleach before publication.

## Local run
```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

Set these environment variables before running:
- `SECRET_KEY`: long random secret; required for production.
- `BOOTSTRAP_OWNER_USERNAME`: initial Owner username.
- `BOOTSTRAP_OWNER_PASSWORD`: initial Owner password (minimum 10 characters).
- `TELEGRAM_URL`: optional Telegram channel URL; defaults to https://t.me/Milad_craft.
- `DATA_DIR`: directory for SQLite data; use a persistent mounted volume in production.
- `COOKIE_SECURE=true`: keep enabled for HTTPS deployments.

Run `python app.py` and open http://127.0.0.1:8080.

## Railway
Deploy from this repository using the included Procfile. Configure the environment variables above and attach a persistent volume, setting DATA_DIR to its mount path. Never commit real credentials to GitHub.

## Initial role matrix
| Role | Claim project | Create project | Issue warning | Academy editor | Manage staff |
| --- | --- | --- | --- | --- | --- |
| Builder | Yes | No | No | No | No |
| H-Builder | No | Yes | Yes | No | No |
| Developer | Yes | Yes | Yes | Yes | Yes |
| Owner | Yes | Yes | Yes | Yes | Yes |

## Before public production
Add CSRF protection and login rate limiting, verify the status provider's response in the deployed environment, and confirm Railway persistent storage is configured. The server status is informational and can be temporarily unavailable if the external status API does not respond.
