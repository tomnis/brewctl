# Production image for the api service. Bundles the built frontend, which the
# api serves at /app (see the StaticFiles mount in brewctl/api/server.py), so the
# UI and the API are same-origin and no CORS or API-URL configuration is needed.
#
# The hardware service is NOT built here -- it runs bare metal on the Pi. See
# deploy/pi/.
FROM node:25.3.0-alpine AS node-build
WORKDIR /app/frontend
# install npm deps
COPY frontend/package*.json ./
RUN npm i --no-audit

# Intentionally not passing BREWCTL_FRONTEND_API_URL: leaving it unset makes the
# bundle address its own origin at runtime (see getApiUrl in
# frontend/src/components/brew/constants.ts), so one image works behind any
# hostname. Only override it if the api is served from a different origin than
# the UI.
ARG BREWCTL_FRONTEND_IS_PROD=true
ENV BREWCTL_FRONTEND_IS_PROD=$BREWCTL_FRONTEND_IS_PROD

# copy frontend sources
COPY frontend/ ./

RUN npm run build

# --------------------
# Final runtime stage
# --------------------
FROM python:3.13-slim AS runtime

WORKDIR /app
COPY backend/requirements/ ./requirements/
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements/api.txt

# copy backend code
COPY backend/src/ ./src/
# copy built frontend assets -- the api serves these from ./build
COPY --from=node-build /app/frontend/dist/ ./build/

EXPOSE 8000
ENV PYTHONPATH=/app/src
ENV BREWCTL_MODE=api

# `fastapi run`, not `dev`: dev is a reload server. Entry point is main.py, which
# dispatches on BREWCTL_MODE -- the old src/brewctl/api/server.py path predates
# the api/hardware split.
CMD ["fastapi", "run", "src/brewctl/main.py", "--host", "0.0.0.0", "--port", "8000"]
