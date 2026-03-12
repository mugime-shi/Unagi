# ─── base: shared setup ──────────────────────────────────────────────────────
FROM python:3.12-slim AS base

WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app ./app

# ─── dev: local docker-compose (no Lambda adapter needed) ────────────────────
FROM base AS dev
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# ─── lambda: AWS Lambda via Mangum (API function) ────────────────────────────
# Build with: docker build --target lambda -t namazu-api .
FROM public.ecr.aws/lambda/python:3.12 AS lambda
COPY backend/requirements.txt ${LAMBDA_TASK_ROOT}/
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app ${LAMBDA_TASK_ROOT}/app
CMD ["app.main.handler"]

# ─── scheduler: AWS Lambda EventBridge handler (daily price fetch) ────────────
# Build with: docker build --target scheduler -t namazu-scheduler .
FROM public.ecr.aws/lambda/python:3.12 AS scheduler
COPY backend/requirements.txt ${LAMBDA_TASK_ROOT}/
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app ${LAMBDA_TASK_ROOT}/app
CMD ["app.tasks.fetch_prices.lambda_handler"]
