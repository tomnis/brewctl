FROM node:25.3.0-slim AS node-build
WORKDIR /app/frontend
# install npm deps
COPY frontend/package*.json ./
RUN npm i

ENV COLDBREW_FRONTEND_API_URL=$COLDBREW_FRONTEND_API_URL
# copy frontend sources
COPY frontend/ ./

# run frontend build (adjust command if your project uses a different script)
RUN npm run build

# --------------------
# Final runtime stage
# --------------------
FROM python:3.13-slim AS runtime
ENV COLDBREW_FRONTEND_API_URL=$COLDBREW_FRONTEND_API_URL


WORKDIR /app
# install pip deps
COPY backend/requirements/ ./requirements/
# install python deps into /deps so they are portable between stages
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements/base.txt

# copy backend code
COPY backend/src/ ./src/
# copy built frontend assets (adjust source path if your frontend build outputs elsewhere)
COPY --from=node-build /app/frontend/dist/ ./build/
# npm deps
# COPY /frontend /app/frontend/
# WORKDIR /app/frontend
# RUN npm install
# RUN npm run build

# then cp back to the backend assets directory

# RUN echo "$COLDBREW_FRONTEND_API_URL"
EXPOSE 8000
CMD ["fastapi", "dev",  "src/brewserver/server.py", "--host", "0.0.0.0"]
# CMD ["uvicorn", "brewserver.server:app", "--host", "0.0.0.0", "--port", "8000"]