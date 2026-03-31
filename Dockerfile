# ─── base: shared setup ──────────────────────────────────────────────────────
FROM python:3.12-slim AS base

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app ./app

# ─── dev: local docker-compose (no Lambda adapter needed) ────────────────────
FROM base AS dev
COPY backend/requirements-dev.txt .
RUN pip install --no-cache-dir -r requirements-dev.txt
# Copy alembic.ini so `alembic upgrade head` can locate the migrations directory.
# Runs migrations on every container start — safe because alembic is idempotent.
COPY backend/alembic.ini .
COPY backend/tests ./tests
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"]

# ─── lambda-base: shared Lambda setup ─────────────────────────────────────────
FROM public.ecr.aws/lambda/python:3.12 AS lambda-base
RUN dnf install -y libgomp && dnf clean all
COPY backend/requirements.txt ${LAMBDA_TASK_ROOT}/
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app ${LAMBDA_TASK_ROOT}/app

# ─── lambda: AWS Lambda via Mangum (API function) ────────────────────────────
# Build with: docker build --target lambda -t unagi-api .
FROM lambda-base AS lambda
CMD ["app.main.handler"]

# ─── scheduler: AWS Lambda EventBridge handler (daily price fetch) ────────────
# Build with: docker build --target scheduler -t unagi-scheduler .
FROM lambda-base AS scheduler
CMD ["app.tasks.fetch_prices.lambda_handler"]
