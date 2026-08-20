NAS_MANIFEST := deploy/nas/app.yaml

# Local development: all three services on one host, hardware in mock mode.
dev:
	docker compose build && docker compose up

# Run the production artifact locally: the image CI publishes, serving the
# bundled frontend at http://localhost:8000/app, against a mock hardware service.
prod-local:
	docker compose -f docker-compose.prod.yml up --build

# Build the production api image (bundles the frontend, served at /app).
build-prod-image:
	docker build -t brewctl-api:local .

# Apply the manifest to the TrueNAS custom app. Needs TRUENAS_URL and
# TRUENAS_API_KEY. There is no compose build here -- a TrueNAS Custom App
# deploys from an image, not from source. The image reference comes from
# deploy/nas/image.tag, substituted into the manifest's @IMAGE@ by apply.sh;
# preview it with `./deploy/nas/apply.sh deploy/nas/app.yaml --render`.
deploy-nas:
	./deploy/nas/apply.sh $(NAS_MANIFEST)

# Deploy the hardware service to the Pi. Bare metal -- no Docker on that box.
# The post-receive hook refreshes deps and restarts the unit; run
# deploy/pi/install.sh on the Pi itself for the first install or unit changes.
deploy-pi:
	git push coldbrewer $$(git rev-parse --abbrev-ref HEAD)

testBackend:
	cd backend && pytest tests

testFrontend:
	cd frontend && npm run test:run

test: testBackend testFrontend

lint:
	cd frontend && npm run lint

.PHONY: dev prod-local build-prod-image deploy-nas deploy-pi testBackend testFrontend test lint
