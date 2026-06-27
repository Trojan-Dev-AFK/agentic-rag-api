# Production Deployment

This document is the exact deployment sequence for running the API in production, including AWS S3 storage wiring.

---

## 1. Prerequisites

1. Linux server with Docker installed.
2. Production PostgreSQL 16+ with `vector` extension enabled.
3. Production Redis 7+.
4. Reachable Ollama endpoint with model `llama3.1` pulled.
5. AWS account access to create an S3 bucket and IAM user.

---

## 2. Clone the repository

```bash
git clone <repo-url>
cd agentic-rag-api
```

---

## 3. Create and link AWS S3

### 3.1 Create bucket

Create a bucket (example name used below):

- Bucket: `agentic-rag-api`
- Region: same region as your deployment when possible
- Public access: keep blocked

### 3.2 Create IAM user for app storage access

Attach this policy (replace bucket name if different):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["s3:PutObject", "s3:GetObject", "s3:DeleteObject"],
      "Resource": "arn:aws:s3:::agentic-rag-api/BACKEND/*"
    }
  ]
}
```

Create an access key for this IAM user and keep:

- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`

### 3.3 Optional CLI verification

```bash
aws s3api put-object --bucket agentic-rag-api --key BACKEND/healthcheck.txt --body /etc/hosts
aws s3api delete-object --bucket agentic-rag-api --key BACKEND/healthcheck.txt
```

If both commands succeed, S3 permissions are correct.

---

## 4. Create production environment file

Create `.env.production` in repository root:

```env
# Database
DATABASE_URL_ASYNC=postgresql+asyncpg://<db_user>:<db_pass>@<db_host>:5432/<db_name>
DATABASE_URL_SYNC=postgresql://<db_user>:<db_pass>@<db_host>:5432/<db_name>
DB_POOL_SIZE=10
DB_MAX_OVERFLOW=20

# Redis
REDIS_URL=redis://<redis_host>:6379/0

# Runtime controls
LOGIN_RATE_LIMIT_ATTEMPTS=10
LOGIN_RATE_LIMIT_WINDOW_SECONDS=60
CHAT_RATE_LIMIT_REQUESTS=30
CHAT_RATE_LIMIT_WINDOW_SECONDS=60
CHAT_IDEMPOTENCY_TTL_SECONDS=300
TOKEN_SESSION_CACHE_TTL_SECONDS=60
VECTOR_SEARCH_CACHE_TTL_SECONDS=300
CHAT_HISTORY_CACHE_TTL_SECONDS=60
DOCUMENT_METADATA_CACHE_TTL_SECONDS=60
READINESS_REQUIRE_REDIS=true
DEFAULT_LIST_LIMIT=50
MAX_LIST_LIMIT=200
MAX_UPLOAD_BYTES=26214400

# Security
SECRET_KEY=<strong-random-secret>
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=60

# Embedding
EMBEDDING_MODEL=all-MiniLM-L6-v2
CHUNK_SIZE=1000
CHUNK_OVERLAP=200

# Encoding
ENCODING=utf-8

# Storage: enable S3
DOCUMENT_STORAGE=CLOUD_STORAGE
AWS_ACCESS_KEY_ID=<aws-access-key-id>
AWS_SECRET_ACCESS_KEY=<aws-secret-access-key>
AWS_REGION=<aws-region>
S3_BUCKET_NAME=agentic-rag-api

# Optional logging override
LOG_LEVEL=INFO

# Optional (when Ollama is remote):
# OLLAMA_HOST=http://<ollama-host>:11434
```

Notes:

1. `LOCAL_UPLOAD_DIR` is not used when `DOCUMENT_STORAGE=CLOUD_STORAGE`.
2. Object key format will be `BACKEND/{company_id}/{stem}_{DD-MM-YYYY_HH-MM-SS}.pdf`.

---

## 5. Build production image

```bash
docker build -t agentic-rag-api:v2026.06.27 .
```

### 5.1 Pin release image tags

Do not deploy with floating `latest` tags in production. Compose is pinned directly to explicit image tags:

- `agentic-rag-api:v2026.06.27`
- `pgvector/pgvector:pg16`
- `redis:7-alpine`

When releasing a new version, update the app image tag in `docker-compose.yml`.

---

## 6. Run database migrations

Run migrations once per deployment:

```bash
docker run --rm --env-file .env.production agentic-rag-api:latest \
  uv run alembic upgrade head
```

---

## 7. Start API container

```bash
docker run -d \
  --name agentic-rag-api \
  --restart unless-stopped \
  -p 8000:8000 \
  --env-file .env.production \
  agentic-rag-api:latest
```

---

## 8. Start Celery worker container

```bash
docker run -d \
  --name agentic-rag-worker \
  --restart unless-stopped \
  --env-file .env.production \
  agentic-rag-api:latest \
  uv run celery -A app.worker.celery_app worker --pool=prefork --loglevel=info
```

If your environment does not support prefork, use `--pool=solo`.

---

## 9. Health and readiness checks

```bash
curl -fsS http://<server-host>:8000/healthz
curl -fsS http://<server-host>:8000/readyz
docker compose ps
```

Expected:

1. `/healthz` returns HTTP 200.
2. `/readyz` returns HTTP 200 only when DB (and Redis when required) are reachable.
3. `docker compose ps` should show `healthy` for app, worker, db, and redis.

---

## 10. Verify S3 linkage from application

1. Upload a PDF through `POST /v1/documents/upload`.
2. Check API logs for S3 initialization/upload success messages.
3. Confirm object exists in bucket under `BACKEND/<company_id>/...`.

Useful commands:

```bash
docker logs --tail 200 agentic-rag-api
docker logs --tail 200 agentic-rag-worker
aws s3 ls s3://agentic-rag-api/BACKEND/ --recursive | tail -20
```

---

## 11. Upgrade procedure

On each release:

1. Pull latest code.
2. Rebuild image.
3. Run migrations.
4. Restart API and worker containers.

Commands:

```bash
git pull
docker build -t agentic-rag-api:latest .
docker run --rm --env-file .env.production agentic-rag-api:latest uv run alembic upgrade head
docker rm -f agentic-rag-api agentic-rag-worker
docker run -d --name agentic-rag-api --restart unless-stopped -p 8000:8000 --env-file .env.production agentic-rag-api:latest
docker run -d --name agentic-rag-worker --restart unless-stopped --env-file .env.production agentic-rag-api:latest uv run celery -A app.worker.celery_app worker --pool=prefork --loglevel=info
```

---

## 12. Rollback

If a release fails:

1. Re-run old image tag containers.
2. Keep DB restore plan ready before applying irreversible migrations.

Example rollback:

```bash
docker rm -f agentic-rag-api agentic-rag-worker
docker run -d --name agentic-rag-api --restart unless-stopped -p 8000:8000 --env-file .env.production agentic-rag-api:<previous-tag>
docker run -d --name agentic-rag-worker --restart unless-stopped --env-file .env.production agentic-rag-api:<previous-tag> uv run celery -A app.worker.celery_app worker --pool=prefork --loglevel=info
```

---

## 13. Production checklist

1. Strong `SECRET_KEY` set.
2. DB and Redis endpoints are private/restricted.
3. S3 bucket is private with least-privilege IAM policy.
4. API and worker containers are both running.
5. `alembic upgrade head` executed successfully.
6. `/healthz` and `/readyz` return 200.
7. Test document upload creates object in S3.
