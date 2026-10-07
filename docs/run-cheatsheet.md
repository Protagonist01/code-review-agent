# Run cheat sheet

Run commands from the cloned repository root. Configure `.env` and `keys/private-key.pem` using the README before starting real reviews.

## Offline demo

```bash
uv sync --locked --extra dev
uv run --locked code-review-demo
```

No Docker, provider key, or GitHub App is needed. Model output is recorded.

## Start, inspect, and stop

```bash
docker compose --env-file .env -f infra/docker-compose.yml up --build -d redis api worker
docker compose --env-file .env -f infra/docker-compose.yml ps
docker compose --env-file .env -f infra/docker-compose.yml logs -f api worker
docker compose --env-file .env -f infra/docker-compose.yml restart worker
docker compose --env-file .env -f infra/docker-compose.yml down
```

`down` keeps Redis data. Adding `-v` deletes volumes and queued work; use that only when deliberately resetting the pilot.

In PowerShell, check API liveness and Redis connectivity:

```powershell
Invoke-RestMethod http://localhost:8000/health
Invoke-RestMethod http://localhost:8000/ready
```

## Optional monitoring

Set `GRAFANA_ADMIN_PASSWORD` to a strong value in `.env`, then:

```bash
docker compose --env-file .env -f infra/docker-compose.yml --profile monitoring up -d
```

| Service | Local URL |
| --- | --- |
| API documentation | http://localhost:8000/docs |
| API metrics | http://localhost:8000/metrics |
| Flower | http://localhost:5555 |
| Prometheus | http://localhost:9090 |
| Grafana | http://localhost:3000 |

Grafana login is `admin` with your configured password. Worker panels require separate metrics collection; see the deployment notes.

## Local webhook delivery

Install tunnel software separately. For example, with `cloudflared` on your PATH:

```bash
cloudflared tunnel --url http://localhost:8000
```

Configure the GitHub App webhook URL as `https://YOUR_TUNNEL/webhook`. Temporary tunnel URLs change on restart. A tunnel can expose every API route; use only for local tests and stop it afterward. Public pilots need controlled ingress as described in [deployment.md](deployment.md).

Open or update a PR in your authorized test repository. A 202 webhook response means a job was queued. Confirm the review and commit status on GitHub and inspect worker logs; a green webhook delivery alone does not prove review completion.
