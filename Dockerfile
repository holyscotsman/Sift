# Multi-stage build: build the React UI, then run the FastAPI app that serves it.
# Works on any container host (Render, Fly.io, Railway, Koyeb, a VPS).

# --- Stage 1: build the frontend ------------------------------------------------
FROM node:22-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# --- Stage 2: runtime -----------------------------------------------------------
FROM python:3.12-slim AS runtime
WORKDIR /app

# Install the backend (deps + the `sift` package) from wheels.
COPY pyproject.toml README.md ./
COPY backend/ ./backend/
RUN pip install --no-cache-dir .

# Bring in the built UI and point the app at it.
COPY --from=frontend /app/frontend/dist ./frontend/dist
ENV SIFT_FRONTEND_DIST=/app/frontend/dist \
    PYTHONUNBUFFERED=1

# Hosts inject $PORT; default to 8756 for local `docker run`.
EXPOSE 8756
CMD ["sh", "-c", "uvicorn sift.main:create_app --factory --host 0.0.0.0 --port ${PORT:-8756}"]
