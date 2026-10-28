# Minecraft staff presence integration

The website exposes a small authenticated webhook for a Paper/Spigot plugin to report staff joins and quits.

## Railway environment variable

Set `MINECRAFT_WEBHOOK_TOKEN` to a long random secret. Keep it private; do not put it in a public repository or client-side config.

## Request

Send an HTTPS POST to:

`https://YOUR-WEBSITE-DOMAIN/workspace/api/minecraft-event`

Headers:

- `Content-Type: application/json`
- `X-MiladCraft-Token: YOUR_SHARED_SECRET`

Body for a join:

```json
{"username":"MinecraftStaffName","event":"join"}
```

Body for a quit:

```json
{"username":"MinecraftStaffName","event":"quit"}
```

The endpoint records events only for usernames that match an existing staff account. Ordinary players are ignored. Accepted events update the online indicator, total online minutes, and the staff activity feed. Requests with a missing or invalid token are rejected. If the token is not configured, the endpoint returns HTTP 503.

## Plugin integration notes

Call the endpoint from the server-side plugin on player join and quit. Use a background HTTP client so web requests do not block the Minecraft main thread. Retry transient failures with a short bounded retry policy, never log the shared token, and configure the URL and token in the plugin's private server config. Use the exact staff Minecraft username stored on the website.

This repository provides the receiving endpoint; the Minecraft plugin that sends the events must be installed and configured separately. The endpoint has not been connected to a live Minecraft server yet.
