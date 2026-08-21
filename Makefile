CONTROL_MANIFEST := deploy/control/app.yaml

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
# deploy/control/image.tag, substituted into the manifest's @IMAGE@ by apply.sh;
# preview it with `./deploy/control/apply.sh deploy/control/app.yaml --render`.
deploy-control:
	./deploy/control/apply.sh $(CONTROL_MANIFEST)

# Deploy the hardware service to the Pi. Bare metal -- no Docker on that box.
# The post-receive hook refreshes deps and restarts the unit; run
# deploy/device/install.sh on the Pi itself for the first install or unit changes.
#
# The pre-receive hook refuses the push outright while a brew is running, because
# the restart wipes the valve's in-memory position. FORCE=1 overrides it -- read
# deploy/device/pre-receive before you reach for that.
deploy-device:
	git push $(if $(FORCE),-o brewctl-force,) coldbrewer $$(git rev-parse --abbrev-ref HEAD)

testBackend:
	cd backend && pytest tests

testFrontend:
	cd frontend && npm run test:run

test: testBackend testFrontend

lint:
	cd frontend && npm run lint

.PHONY: dev prod-local build-prod-image deploy-control deploy-device testBackend testFrontend test lint
