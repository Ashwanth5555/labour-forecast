# Sodexo Healthcare - Labour Forecast
#
# One image, three app processes behind one public port - the same shape the
# app has locally, so there is no CORS or cross-service networking to set up:
#
#   :80    nginx     - serves the built frontend, proxies /api -> :8300
#   :8300  backend   - ingestion, forecasting, analytics, auth, assistant
#   :8200  mock API  - stands in for UKG / Workday / ADT / POS / Payroll / ERP
#
# Python 3.12 matches the local .venv; tensorflow-cpu 2.17 and pmdarima 2.0.4
# publish wheels for it and are built against numpy 1.26.

# --- Stage 1: build the frontend -------------------------------------------
FROM node:22-slim AS frontend
WORKDIR /app/frontend_sodexo
COPY frontend_sodexo/package*.json ./
RUN npm ci
COPY frontend_sodexo/ ./
RUN npm run build

# --- Stage 2: python dependencies (slow layer, cached separately) ----------
FROM python:3.12-slim AS pydeps
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*
COPY backend_sodexo/requirements.txt /tmp/backend-requirements.txt
COPY mock_api_sodexo/requirements.txt /tmp/mock-requirements.txt
RUN pip install --prefix=/install -r /tmp/backend-requirements.txt -r /tmp/mock-requirements.txt

# --- Stage 3: runtime -------------------------------------------------------
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends nginx supervisor curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=pydeps /install /usr/local
RUN python -c "import numpy; assert numpy.__version__ == '1.26.4', numpy.__version__"

WORKDIR /app
COPY backend_sodexo/ /app/backend_sodexo/
COPY mock_api_sodexo/ /app/mock_api_sodexo/
# Mock API source workbook, plus a snapshot of an already-synced and trained
# database so the demo is usable immediately. Container storage is ephemeral:
# a restart returns to this snapshot.
COPY data/sodex.xlsx /app/data/sodex.xlsx
COPY deploy/seed.db /app/data/sodexo.db
COPY --from=frontend /app/frontend_sodexo/dist/ /usr/share/nginx/html/

COPY deploy/nginx.conf /etc/nginx/sites-available/default
COPY deploy/supervisord.conf /etc/supervisor/conf.d/labour-forecast.conf

# The backend resolves ./data relative to the project root (this WORKDIR).
ENV DATABASE_URL=sqlite:///./data/sodexo.db \
    MOCK_API_BASE_URL=http://127.0.0.1:8200 \
    DATA_DIR=/app/data

EXPOSE 80
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
    CMD curl -fsS http://127.0.0.1:80/health || exit 1

CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/supervisord.conf", "-n"]
