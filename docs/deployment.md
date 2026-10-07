# Deployment and release guidance

This repository supplies a Docker Compose pilot environment. It has no hosted service or automatic production deployment configured. GitHub Pages cannot run this API, Redis, and worker stack.

## Local pilot

From the repository root, create `.env` from `.env.example`, set the GitHub App credentials and provider, and mount the private key at `keys/private-key.pem`.

```bash
docker compose --env-file .env -f infra/docker-compose.yml config --quiet
docker compose --env-file .env -f infra/docker-compose.yml up --build -d redis api worker
docker compose --env-file .env -f infra/docker-compose.yml ps
docker compose --env-file .env -f infra/docker-compose.yml logs -f api worker
```

Use `config --quiet`: printing the expanded configuration can disclose credentials. `--env-file .env` supplies root-level variables for Compose interpolation; each app service also loads that file at runtime.

The API and worker share the same image. The image installs the application from `uv.lock`, runs as UID 10001, and mounts only keys read-only. On Linux, grant that UID or an appropriate group permission to read the key without making it world-readable. The worker command explicitly sets concurrency to one, with at most five simultaneous per-hunk model calls inside a task.

`/health` is API liveness. `/ready` verifies API-to-Redis connectivity. Neither proves that a worker, model provider, or GitHub authentication is functioning. Review worker logs and validate those dependencies separately.

## Monitoring

Set a strong `GRAFANA_ADMIN_PASSWORD` in `.env` before enabling the profile:

```bash
docker compose --env-file .env -f infra/docker-compose.yml --profile monitoring up -d
```

Grafana uses login `admin` and your configured password. Do not share an installation with an unset password. All published ports bind to localhost. Flower has no configured authentication: keep it private.

The API's webhook counters are scrapeable. Worker and token panels are incomplete until separate metrics instrumentation and collection are added. Prometheus evaluates supplied rules, but Alertmanager delivery and Loki collection are not configured.

## Before a public pilot

- Place an HTTPS reverse proxy in front of `/webhook`. Keep `/metrics`, `/docs`, `/ready`, Redis, and monitoring private. Limit request size, rate, and proxy timeout.
- Supply credentials through your host's secret mechanism. Install the GitHub App only on repositories intended for the pilot. Review hosted providers' handling of code.
- Record the revision, lockfile, image digest, configuration, and selected model. Base and service tags can move; pin and scan image digests when promoting a release.
- Redis uses append-only persistence and a named volume. Test backups, restoration, disk limits, and restart behavior. `down -v` deletes that volume and queued work.
- Verify signed delivery, worker execution, provider response, and GitHub publication using an authorized test repository. This creates real comments and statuses.
- Exercise provider outages, GitHub rate limits, queue outages, worker crashes, duplicate delivery, and new commits during review. Error-status publication can itself fail; monitor logs.

Deduplication is bounded to one hour. Publication reconciles identical payloads but does not serialize concurrent jobs. Changed model output on retry can create another review. The final SHA check and remote write are not atomic. Keep the AI status advisory until recovery and quality have been validated.

## GitHub checks and release evidence

The CI workflow is configured to lint, format-check, type-check, test Python 3.11/3.13, build and inspect packages, install the wheel outside the checkout, audit locked runtime dependencies, build the container, and check API/Redis readiness. It does not publish packages or deploy a service.

The first workflow run requires publishing the changes to GitHub. After successful runs, enable required checks on the default branch and private vulnerability reporting in repository settings. Those server-side controls cannot be established by adding files locally.

For a recruiter-facing release, link a successful CI run and, if available, a sanitized review from a dedicated demo repository. A recorded offline demo is useful software evidence, but must not be described as proof of live model quality.
