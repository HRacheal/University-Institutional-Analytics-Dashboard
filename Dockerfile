# University Institutional Analytics Dashboard: one image that builds the React frontend and serves it from FastAPI.
# Inference only: the saved (Colab-trained) model artifacts are copied in and verified by SHA-256 when loaded.
# Build: docker build -t uiad .        Run: docker run -p 8000:8000 -e UIAD_ENV=production ... uiad

# ---------- stage 1: build the frontend ----------
FROM node:22-bookworm-slim AS frontend
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---------- stage 2: Python runtime ----------
FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    MPLCONFIGDIR=/tmp/matplotlib \
    NUMBA_CACHE_DIR=/tmp/numba \
    UIAD_ENV=production \
    UIAD_VAR_DIR=/var/data \
    PORT=8000

# libgomp1: OpenMP runtime needed by XGBoost, LightGBM and scikit-learn
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 app

WORKDIR /app
COPY requirements.txt ./
RUN pip install -r requirements.txt

# application code, saved models/reports, and the data the analytics read
COPY backend/app ./backend/app
COPY data_warehouse ./data_warehouse
COPY data ./data
COPY --from=frontend /build/frontend/dist ./frontend/dist
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN sed -i 's/\r$//' /usr/local/bin/entrypoint.sh && chmod 755 /usr/local/bin/entrypoint.sh \
    && mkdir -p /var/data && chown app:app /var/data

WORKDIR /app/backend
EXPOSE 8000
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
