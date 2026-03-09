FROM node:25.3.0-alpine AS node-build
WORKDIR /app/frontend
# install npm deps
COPY frontend/package*.json ./
RUN npm i --no-audit

ARG BREWCTL_FRONTEND_API_URL
ENV BREWCTL_FRONTEND_API_URL=$BREWCTL_FRONTEND_API_URL
# copy frontend sources
COPY frontend/ ./

# run frontend build (adjust command if your project uses a different script)
RUN npm run build

# --------------------
# Final runtime stage
# --------------------
FROM python:3.13 AS runtime

WORKDIR /app
# install pip deps
RUN apt-get update && apt-get upgrade -y && apt-get install -y gcc
COPY backend/requirements/ ./requirements/
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements/base.txt && \
    pip install --no-cache-dir -r requirements/backend.txt

# copy backend code
COPY backend/src/ ./src/
# copy built frontend assets
COPY --from=node-build /app/frontend/dist/ ./build/
EXPOSE 8000
ENV PYTHONPATH=/app/src
CMD ["fastapi", "dev",  "src/brewctl/api/server.py", "--host", "0.0.0.0"]
# TODO use uvicorn?
# CMD ["uvicorn", "brewctl.api.server:app", "--host", "0.0.0.0", "--port", "8000"]