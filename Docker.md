# FIRE — Docker Quick Reference

## Architecture

```
Your PC
  ├── Ollama (runs natively — uses your GPU, models already downloaded)
  │     └── http://localhost:11434
  │
  └── Docker
        ├── fire_backend  → http://localhost:8101
        │     └── talks to Ollama via host.docker.internal:11434
        └── fire_frontend → http://localhost:8102  (Step 7)
```

Ollama runs on your machine directly — no second container, no re-downloading
models. Docker just talks to it via `host.docker.internal`.

## Prerequisites

- Docker Desktop installed and running
- Ollama running on your machine (`ollama serve` or as a service)
- Your models already pulled (qwen3:14b-q4_K_M for insights)

## First time setup

```bash
# 1. Copy env file and add your Gemini key
cp .env.example .env
# Edit .env — set GEMINI_API_KEY=AIza...

# 2. Build and start
docker compose up -d --build

# 3. Verify backend is up
curl http://localhost:8101/health
```

## Daily use

```bash
# Start (also runs on PC boot automatically)
docker compose up -d

# Stop
docker compose down

# View logs
docker compose logs -f fire_backend

# Rebuild after code changes
docker compose up -d --build
```

## Auto-start on Windows boot

Two steps:
1. Docker Desktop → Settings → General → ✓ "Start Docker Desktop when you log in"
2. Ollama installs itself as a Windows service and starts automatically

With `restart: unless-stopped` in docker-compose.yml, fire_backend starts
automatically when Docker starts.

## Access from other LAN devices

Find your PC's local IP:
  Windows: ipconfig → IPv4 Address (e.g. 192.168.1.42)

From any phone or tablet on your WiFi:
  http://192.168.1.42:8101/docs   ← API
  http://192.168.1.42:8102        ← Frontend (Step 7)

## Ports

| Service       | Host port | Notes                        |
|---------------|-----------|------------------------------|
| fire_backend  | 8101      | FastAPI — /docs for Swagger  |
| fire_frontend | 8102      | React app (Step 7)           |
| Ollama        | 11434     | Native on host, not Docker   |

## Data

All financial data lives in a named Docker volume:

```bash
# See where Docker stores it
docker volume inspect fire_data

# Backup
docker run --rm -v fire_data:/data -v %cd%:/backup \
  alpine tar czf /backup/fire_backup.tar.gz /data
```

## Troubleshooting

**Backend can't reach Ollama:**
Make sure Ollama is running on your host:
```bash
ollama list   # should show your models
curl http://localhost:11434/api/tags  # should return JSON
```
On Linux, also verify `host.docker.internal` resolves — it's automatic on
Windows/Mac Docker Desktop but needs `extra_hosts: host-gateway` on Linux
(already set in docker-compose.yml).