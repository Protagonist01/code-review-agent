# Run Cheat Sheet

Use these commands from the project root:

```powershell
cd "D:\document\dev\work\portfolio projects\code-review-agent"
```

## Start The App

Build and start everything:

```powershell
docker compose -f infra\docker-compose.yml up --build
```

Start in the background instead:

```powershell
docker compose -f infra\docker-compose.yml up -d --build
```

Check containers:

```powershell
docker compose -f infra\docker-compose.yml ps
```

Check the API health endpoint:

```powershell
Invoke-RestMethod http://localhost:8000/health
```

Expected response:

```json
{"status":"ok"}
```

## Expose The Local API To GitHub

In a second terminal, start Cloudflare Tunnel:

```powershell
.\tools\cloudflared.exe tunnel --url http://localhost:8000
```

Copy the generated `https://...trycloudflare.com` URL.

Use this webhook URL in the GitHub App settings:

```text
https://<your-trycloudflare-url>/webhook
```

The quick tunnel URL changes every time you restart `cloudflared`.

## Useful Local URLs

API health:

```text
http://localhost:8000/health
```

API metrics:

```text
http://localhost:8000/metrics
```

Flower Celery dashboard:

```text
http://localhost:5555
```

Prometheus:

```text
http://localhost:9090
```

Grafana:

```text
http://localhost:3000
```

Grafana login:

```text
admin / admin
```

## Watch Logs

All services:

```powershell
docker compose -f infra\docker-compose.yml logs -f
```

API and worker only:

```powershell
docker compose -f infra\docker-compose.yml logs -f api worker
```

Recent review-related logs:

```powershell
docker compose -f infra\docker-compose.yml logs --since=10m api worker |
  Select-String -Pattern "webhook|review|github_auth|llm|status|ERROR|Exception"
```

## Trigger A Test Review

1. Keep Docker running.
2. Keep Cloudflare Tunnel running.
3. Confirm the GitHub App webhook points to the current tunnel URL.
4. Open or update a pull request in an installed repository.
5. Watch the GitHub App "Recent Deliveries" page.
6. Watch local logs:

```powershell
docker compose -f infra\docker-compose.yml logs -f api worker
```

A healthy review usually includes:

```text
webhook.received
github_auth.installation_token_issued
llm_backend.init provider=openrouter
github_client.review_posted
github_client.status_set state=success
review.complete
```

## Shut Down

If Docker Compose is running in the foreground, press:

```text
Ctrl+C
```

If Docker Compose is running in the background:

```powershell
docker compose -f infra\docker-compose.yml down
```

Stop Cloudflare Tunnel by pressing:

```text
Ctrl+C
```

## Hard Reset Local Containers

Use this when you want to remove containers and networks:

```powershell
docker compose -f infra\docker-compose.yml down
```

Use this only when you also want to remove Docker volumes:

```powershell
docker compose -f infra\docker-compose.yml down -v
```

## Common Fixes

Rebuild after dependency or Dockerfile changes:

```powershell
docker compose -f infra\docker-compose.yml up -d --build --force-recreate
```

Restart only the worker:

```powershell
docker compose -f infra\docker-compose.yml restart worker
```

Restart only the API:

```powershell
docker compose -f infra\docker-compose.yml restart api
```

If GitHub delivery is green but no review appears, check worker logs first:

```powershell
docker compose -f infra\docker-compose.yml logs --since=10m worker
```

If the tunnel URL changed, update the GitHub App webhook URL before redelivering events.
