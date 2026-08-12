NAS_COMPOSE := deploy/nas/docker-compose.yml

# Local development: all three services on one host, hardware in mock mode.
dev:
	docker compose build && docker compose up

# Build the production api image (bundles the frontend, served at /app).
build-prod-image:
	docker compose -f $(NAS_COMPOSE) build

# Deploy api + frontend to the NAS. Run this on the NAS, with deploy/nas/.env in place.
deploy-nas:
	docker compose -f $(NAS_COMPOSE) up -d --build

# Deploy the hardware service to the Pi. Bare metal -- no Docker on that box.
# The post-receive hook refreshes deps and restarts the unit; run
# deploy/pi/install.sh on the Pi itself for the first install or unit changes.
deploy-pi:
	git push pi $$(git rev-parse --abbrev-ref HEAD)

testBackend:
	cd backend && pytest tests

testFrontend:
	cd frontend && npm run test:run

test: testBackend testFrontend

lint:
	cd frontend && npm run lint

.PHONY: dev build-prod-image deploy-nas deploy-pi testBackend testFrontend test lint
