# MILAD CRAFT Website

A Persian RTL website for the MILAD CRAFT Minecraft server, with a Flask staff portal.

## Features
- Public landing page prepared for server information, gallery, and community links.
- Staff login with Werkzeug password hashing.
- Role-specific permissions for Builder, H-Builder, Developer, and Owner.
- Project creation and claiming.
- Warning records with optional evidence links.
- Owner/Developer staff-account creation.

## Run locally
```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

Set `SECRET_KEY`, `BOOTSTRAP_OWNER_USERNAME`, and `BOOTSTRAP_OWNER_PASSWORD` in your environment before first run. The bootstrap owner is created only if that username does not already exist. Do not commit real secrets to GitHub.

```bash
python app.py
```

Open http://127.0.0.1:8080

## Railway
- Deploy this repository with the start command in `Procfile`.
- Set a strong random `SECRET_KEY`.
- Set `BOOTSTRAP_OWNER_USERNAME` and a unique `BOOTSTRAP_OWNER_PASSWORD` in Railway Variables.
- Attach a persistent volume and set `DATA_DIR` to its mount path, so the SQLite database survives redeploys.
- Keep the repository private and never put real credentials in source files.

## Initial role matrix
| Role | View projects | Claim project | Create project | Issue warning | Manage staff |
| --- | --- | --- | --- | --- | --- |
| Builder | Yes | Yes | No | No | No |
| H-Builder | Yes | No | Yes | Yes | No |
| Developer | Yes | Yes | Yes | Yes | Yes |
| Owner | Yes | Yes | Yes | Yes | Yes |

The initial implementation is a foundation and should be reviewed and hardened before public production use (including CSRF protection, login rate limiting, and a formal audit trail).
