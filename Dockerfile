FROM node:25.3.0-alpine AS node-build
WORKDIR /app/frontend
# install npm deps
COPY frontend/package*.json ./
RUN npm i  --no-audit

ARG COLDBREW_FRONTEND_API_URL
ENV COLDBREW_FRONTEND_API_URL=$COLDBREW_FRONTEND_API_URL
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
RUN apt-get update && apt-get upgrade -y && apt-get install -y gcc bluez
COPY backend/requirements/ ./requirements/
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements/base.txt && \
    pip install --no-cache-dir -r requirements/pi.txt

# copy backend code
COPY backend/src/ ./src/
# copy built frontend assets
COPY --from=node-build /app/frontend/dist/ ./build/
EXPOSE 8000
CMD ["fastapi", "dev",  "src/brewserver/server.py", "--host", "0.0.0.0"]
# TODO use uvicorn?
# CMD ["uvicorn", "brewserver.server:app", "--host", "0.0.0.0", "--port", "8000"]