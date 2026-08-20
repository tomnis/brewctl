> **SUPERSEDED — historical design doc, not the current architecture.**
>
> This plan describes a Forgejo *registry* approach: build, `docker push` to
> `forgejo.<host>/…`, and have TrueNAS pull. That was abandoned. The registry is
> HTTP-only, which meant every Docker daemon on the network needed an
> `insecure-registries` entry maintained by a Post Init script that restarts the
> daemon (stopping every container on the box) and that a TrueNAS upgrade could
> silently revert. Streaming the image straight to the deploy host with
> `docker save | ssh docker load` removes the registry, the daemon config, and
> the pull step in exchange for one `ssh` key.
>
> Consequences: `FORGEJO_HOST` and `FORGEJO_TOKEN` referenced below are **not**
> used by any workflow. The live design is `.forgejo/workflows/build.yml`
> (publish) and `deploy.yml` (promote), with `deploy/nas/image.tag` as the
> pinned reference. Kept for the reasoning, not as instructions.

# Plan: GitOps CI Pipeline for Brewctl

## Context

Setting up Forgejo CI/CD on TrueNAS to build and push Docker images to Forgejo's built-in registry, then deploy to TrueNAS via the `app.update` API. Code lives on GitHub (public), CI mirror is private on Forgejo. The goal is a tag-driven GitOps flow: `git tag v1.2.3` → CI builds → TrueNAS updates running image.

The root `Dockerfile` produces a single production image: api + bundled frontend (same-origin, no CORS). The `deploy/nas/docker-compose.yml` already notes: "When the registry and Forgejo runner land, replace `build:` with `image:`."

## Current State

- **Root `Dockerfile`**: Multi-stage (node → python). Bundles frontend dist into API image. Exposes port 8000.
- **`backend/Dockerfile`**: Backend-only (dev). `fastapi dev src/brewctl/main.py`
- **`frontend/Dockerfile`**: Frontend-only (dev). `npm run dev` (not used in production).
- **Existing `.forgejo/workflows/docker-build.yml`**: Single job, builds root Dockerfile, `load: true` (no push). Triggers on all pushes.
- **`deploy/nas/docker-compose.yml`**: Builds from root Dockerfile. Comment says to replace `build:` with `image:` when registry lands.
- **Frontend `package.json` version**: `0.0.0` (not semver — Git tags are the version source).

## Architecture

```
GitHub (public code)
  └─> Mirror → Forgejo (private, same code + CI + manifests)
                     │
                     ├─> Forgejo Runner (built-in)
                     │      └─> Forgejo Registry (built-in)
                     │
                     └─> deploy/manifest/api.json
                         └─> TrueNAS API (app.update)
```

## Steps

### 1. Replace existing workflow

**File**: `.forgejo/workflows/docker-build.yml` → replace content (keep filename, rename `name:` in YAML).

Replace the existing single-`build` job with a two-job pipeline:

- **`build`**: Checkout → login to Forgejo registry → build + push the root Dockerfile image
  - On `push` to `master`: tag with `git-sha` only (no deploy)
  - On `push` of `v*` tags: tag with `{version}`, `latest`, and `git-sha` (triggers deploy)
- **`deploy`**: (runs only on tag pushes) Update TrueNAS via `app.update` API

### 2. Create build-and-deploy workflow

```yaml
name: Build Docker Image

on:
  push:
    branches: [master]
    tags: ['v*']

jobs:
  build:
    runs-on: docker
    steps:
      - uses: actions/checkout@v4

      - name: Login to Forgejo Registry
        uses: docker/login-action@v3
        with:
          registry: ${{ vars.FORGEJO_HOST }}
          username: ${{ github.actor }}
          password: ${{ secrets.FORGEJO_TOKEN }}

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3

      - name: Build and push image
        uses: docker/build-push-action@v5
        with:
          context: .
          push: true
          tags: |
            ${{ vars.FORGEJO_HOST }}/brewctl/brewctl-api:{{ github.sha }}
            ${{ startsWith(github.ref, 'refs/tags/') && format('{0}/brewctl/brewctl-api:{1}', vars.FORGEJO_HOST, github.ref_name) || '' }}
            ${{ startsWith(github.ref, 'refs/tags/') && format('{0}/brewctl/brewctl-api:latest', vars.FORGEJO_HOST) || '' }}

  deploy:
    needs: build
    runs-on: docker
    if: startsWith(github.ref, 'refs/tags/')
    steps:
      - uses: actions/checkout@v4

      - name: Update TrueNAS app image
        run: |
          curl -s -X POST ${{ vars.TRUENAS_API }}/api/v2.0/app/update \
            -H "Authorization: Key ${{ secrets.TRUENAS_API_KEY }}" \
            -H "Content-Type: application/json" \
            -d '{
              "app_name": "brewctl-api",
              "values": {
                "image": {
                  "repository": "${{ vars.FORGEJO_HOST }}/brewctl/brewctl-api",
                  "tag": "${{ github.ref_name }}"
                }
              },
              "custom_app": true
            }'
```

**Notes on the workflow:**
- One image (root Dockerfile) — api + bundled frontend. This is what `deploy/nas` uses.
- The `deploy` job runs only on tag pushes (`if: startsWith(...)`). Master pushes build + push images but skip deployment — manual merge to trigger deploy.
- The `deploy` job checks out the repo (for manifest updates in future iterations).
- The `deploy/nas/docker-compose.yml` comment already says to replace `build:` with `image:` — this workflow makes that change.

### 3. Update deploy/nas/docker-compose.yml

Replace `build:` with `image:` referencing the Forgejo registry. Everything else (env vars, ports, healthcheck) stays the same.

**Before**:
```yaml
services:
  api:
    build:
      context: ../..
      dockerfile: Dockerfile
```

**After**:
```yaml
services:
  api:
    image: ${FORGEJO_HOST}/brewctl/brewctl-api:latest
    restart: unless-stopped
    # ... all existing env vars, ports, healthcheck unchanged ...
```

The `FORGEJO_HOST` env var is already available on the TrueNAS box. `latest` is the default — the deploy job updates the image tag via the API, so `latest` always points to the latest deployed version.

### 4. Create manifest directory

**Directory**: `deploy/manifest/`

**File**: `deploy/manifest/api.json`
```json
{
  "image": {
    "repository": "forgejo.local/brewctl/brewctl-api",
    "tag": ""
  }
}
```

This file is the single source of truth for "what version is deployed." The deploy job can update it (future iteration). For now, it documents the expected image path.

### 5. Configure Forgejo repo settings

- **`FORGEJO_HOST`** (repo variable): Your Forgejo instance URL (e.g., `forgejo.local`)
- **`FORGEJO_TOKEN`** (repo secret): Personal Access Token with `write:packages` scope
- **`TRUENAS_API`** (repo variable): TrueNAS middleware API URL (e.g., `https://truenas.local`)
- **`TRUENAS_API_KEY`** (repo secret): API key with `APP:UPDATE` scope

### 6. Mirror setup (manual, outside this plan)

- Create a private mirror of the GitHub repo on Forgejo
- Push the workflow file and `deploy/manifest/` directory to the mirror
- Register a built-in runner on the Forgejo instance

## Files Modified

| File | Action |
|------|--------|
| `.forgejo/workflows/docker-build.yml` | Replace content — build + deploy pipeline |
| `deploy/nas/docker-compose.yml` | Replace `build:` with `image:` referencing Forgejo registry |
| `deploy/manifest/api.json` | **New** — deployment manifest |

## Verification

1. Push a commit to master → verify image is pushed to registry with `git-sha` tag (no deploy)
2. `git tag v1.0.0 && git push origin v1.0.0` → verify images tagged `v1.0.0`, `latest`, and `git-sha` appear in registry
3. Verify TrueNAS `app.update` API call succeeds (check deploy job logs)
4. Confirm TrueNAS is running the new image version
5. Rollback test: `git tag v0.9.9 <old-commit>` → verify rollback works
