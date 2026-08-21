#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────
# Nova Manager — Deploy to GCP Cloud Run
# Run as pranaypandit12@gmail.com
# Prerequisites: scripts/gcp_admin_setup.sh and
#                scripts/gcp_infra_setup.sh completed
# ──────────────────────────────────────────────────────────────
set -euo pipefail

### ── PROJECT SETTINGS ────────────────────────────────────────
PROJECT_ID="xgaminn"
REGION="us-central1"
REPO="app-images"
IMAGE_NAME="nova-manager"
TAG="$(date +%Y%m%d%H%M%S)"
SA_EMAIL="nova-manager-sa@${PROJECT_ID}.iam.gserviceaccount.com"
CLOUD_SQL_INSTANCE="${PROJECT_ID}:${REGION}:nova-db"
VPC_CONNECTOR="nova-connector"
### ────────────────────────────────────────────────────────────

# Get data VM internal IP for ClickHouse env vars
DATA_VM_IP=$(gcloud compute instances describe nova-data \
  --zone="${REGION}-a" --project="$PROJECT_ID" \
  --format='value(networkInterfaces[0].networkIP)')

echo "=== Config ==="
echo "  Project:    $PROJECT_ID"
echo "  Region:     $REGION"
echo "  Tag:        $TAG"
echo "  Data VM IP: $DATA_VM_IP"
echo ""

# 1. Configure gcloud
gcloud config set account tyrongamess@gmail.com
gcloud config set project "$PROJECT_ID"
gcloud config set run/region "$REGION"

# 2. Build & push
FULL_IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/${IMAGE_NAME}:${TAG}"
echo "=== Building image: $FULL_IMAGE ==="
gcloud builds submit --tag "$FULL_IMAGE"

# 3. Run Alembic migrations (Cloud Run Job)
echo "=== Running database migrations ==="
if gcloud run jobs describe nova-migrate --region="$REGION" --project="$PROJECT_ID" 2>/dev/null; then
  gcloud run jobs update nova-migrate \
    --image="$FULL_IMAGE" \
    --region="$REGION" \
    --project="$PROJECT_ID"
  gcloud run jobs execute nova-migrate \
    --region="$REGION" \
    --project="$PROJECT_ID" \
    --wait
else
  gcloud run jobs create nova-migrate \
    --image="$FULL_IMAGE" \
    --command="alembic" \
    --args="upgrade,head" \
    --set-cloudsql-instances="$CLOUD_SQL_INSTANCE" \
    --vpc-connector="$VPC_CONNECTOR" \
    --set-secrets="DATABASE_URL=DATABASE_URL:latest" \
    --service-account="$SA_EMAIL" \
    --region="$REGION" \
    --project="$PROJECT_ID" \
    --max-retries=0 \
    --execute-now --wait
fi

# 4. Run ClickHouse bootstrap (Cloud Run Job)
echo "=== Bootstrapping ClickHouse ==="
if gcloud run jobs describe nova-clickhouse-bootstrap --region="$REGION" --project="$PROJECT_ID" 2>/dev/null; then
  gcloud run jobs update nova-clickhouse-bootstrap \
    --image="$FULL_IMAGE" \
    --region="$REGION" \
    --project="$PROJECT_ID"
  gcloud run jobs execute nova-clickhouse-bootstrap \
    --region="$REGION" \
    --project="$PROJECT_ID" \
    --wait
else
  gcloud run jobs create nova-clickhouse-bootstrap \
    --image="$FULL_IMAGE" \
    --command="python" \
    --args="scripts/bootstrap_clickhouse.py" \
    --set-cloudsql-instances="$CLOUD_SQL_INSTANCE" \
    --vpc-connector="$VPC_CONNECTOR" \
    --set-secrets="DATABASE_URL=DATABASE_URL:latest,CLICKHOUSE_PASSWORD=CLICKHOUSE_PASSWORD:latest" \
    --set-env-vars="CLICKHOUSE_HOST=${DATA_VM_IP},CLICKHOUSE_PORT=8123,CLICKHOUSE_USER=default,PYTHONPATH=/app" \
    --service-account="$SA_EMAIL" \
    --region="$REGION" \
    --project="$PROJECT_ID" \
    --max-retries=0 \
    --execute-now --wait
fi

# 5. Deploy API
echo "=== Deploying API ==="
gcloud run deploy "$IMAGE_NAME" \
  --image="$FULL_IMAGE" \
  --region="$REGION" \
  --platform=managed \
  --allow-unauthenticated \
  --add-cloudsql-instances="$CLOUD_SQL_INSTANCE" \
  --vpc-connector="$VPC_CONNECTOR" \
  --service-account="$SA_EMAIL" \
  --set-secrets="DATABASE_URL=DATABASE_URL:latest,JWT_SECRET_KEY=JWT_SECRET_KEY:latest,REDIS_URL=REDIS_URL:latest,OPENAI_API_KEY=OPENAI_API_KEY:latest,BREVO_API_KEY=BREVO_API_KEY:latest,CLICKHOUSE_PASSWORD=CLICKHOUSE_PASSWORD:latest,NOTICE_SERVICE_SECRET=NOTICE_SERVICE_SECRET:latest,NOTICE_SERVICE_URL=NOTICE_SERVICE_URL:latest,NOVA_ADMIN_KEY=NOVA_ADMIN_KEY:latest" \
  --set-env-vars="CLICKHOUSE_HOST=${DATA_VM_IP},CLICKHOUSE_PORT=8123,CLICKHOUSE_USER=default" \
  --memory=512Mi \
  --cpu=1 \
  --min-instances=0 \
  --max-instances=10 \
  --concurrency=80 \
  --port=8000 \
  --project="$PROJECT_ID"

# 6. Deploy Worker
echo "=== Deploying Worker ==="
gcloud run deploy "nova-manager-worker" \
  --image="$FULL_IMAGE" \
  --region="$REGION" \
  --platform=managed \
  --no-allow-unauthenticated \
  --command="python" \
  --args="scripts/run_worker.py" \
  --add-cloudsql-instances="$CLOUD_SQL_INSTANCE" \
  --vpc-connector="$VPC_CONNECTOR" \
  --service-account="$SA_EMAIL" \
  --set-secrets="DATABASE_URL=DATABASE_URL:latest,JWT_SECRET_KEY=JWT_SECRET_KEY:latest,REDIS_URL=REDIS_URL:latest,CLICKHOUSE_PASSWORD=CLICKHOUSE_PASSWORD:latest,NOTICE_SERVICE_SECRET=NOTICE_SERVICE_SECRET:latest,NOTICE_SERVICE_URL=NOTICE_SERVICE_URL:latest,NOVA_ADMIN_KEY=NOVA_ADMIN_KEY:latest" \
  --set-env-vars="CLICKHOUSE_HOST=${DATA_VM_IP},CLICKHOUSE_PORT=8123,CLICKHOUSE_USER=default,PYTHONPATH=/app" \
  --cpu=1 \
  --memory=512Mi \
  --no-cpu-throttling \
  --concurrency=1 \
  --min-instances=1 \
  --max-instances=3 \
  --port=8080 \
  --project="$PROJECT_ID"

# 7. Notice Service (runs on a dedicated GCE VM, NOT Cloud Run)
# The notice service maintains persistent SSE connections, so it needs
# a single long-lived process — not Cloud Run's ephemeral containers.
#
# Deployed facts (verified 2026-07-28 — the previous values in this block were
# wrong and cost a debugging session, so keep them accurate):
#   VM instance    notice-service        (NOT "nova-notice-vm")
#   Zone           us-central1-c         (NOT ${REGION}-a — that's nova-data)
#   systemd unit   nova-notice.service   (NOT "nova-notice-service")
#   Run user       admin2
#   Checkout       /opt/nova-manager on branch `staging`
#   Interpreter    /opt/nova-manager/.venv/bin/python (poetry/pyproject, NOT
#                  requirements.txt — that file does not exist)
#   Public URL     https://sse.api.nova.xgaming.club  → VM :8001
#
# Branch: track `staging`, the same branch Cloud Run deploys. `staging` is a
# strict superset of the old `sse` branch (sse was 0 ahead / 81 behind), and
# scripts/run_notice_service.py + nova_manager/core/security.py are byte-
# identical between them, so there is no reason to run the notice service off
# a separate branch. It was pinned to `sse` at an orphaned 2026-03 commit for
# ~4 months before being moved to `staging`.
#
# git needs the deploy key passed explicitly — there is no ~/.ssh/config on
# the VM, so a bare `git pull` fails with "Permission denied (publickey)".
echo "=== Deploying Notice Service (GCE VM) ==="
gcloud compute ssh notice-service --zone=us-central1-c --project="$PROJECT_ID" \
  --command="sudo -H -u admin2 bash -c \"cd /opt/nova-manager && \
    GIT_SSH_COMMAND='ssh -i ~/.ssh/nova_deploy -o IdentitiesOnly=yes' \
      git fetch origin staging && git checkout -B staging origin/staging\" && \
    sudo systemctl restart nova-notice.service"
#
# Required env vars on the VM, in /opt/nova-manager/.env — loaded BOTH by the
# systemd unit (EnvironmentFile=) and by nova_manager/core/config.py's
# load_dotenv(os.getcwd()/.env, override=True):
#   JWT_SECRET_KEY         (must BYTE-match Cloud Run's — see warning below)
#   NOTICE_SERVICE_SECRET  (shared secret, must match Cloud Run's NOTICE_SERVICE_SECRET)
#   PORT                   (default: 8001)
#
# ⚠ KNOWN UNRESOLVED ISSUE (2026-07-28): GET /subscribe rejects the production
# SDK key with 401 "Invalid SDK API key: signature verification failed", while
# the very same key authenticates fine against Cloud Run's nova-manager. Ruled
# out: stale code (now on staging @ same commit as Cloud Run), branch drift
# (security.py identical), NOTICE_SERVICE_SECRET (matches), and every one of the
# 4 JWT_SECRET_KEY Secret Manager versions (validate_sdk_api_key rejects the key
# under all of them). Leading hypothesis: a trailing-whitespace byte mismatch —
# Cloud Run's secretKeyRef injects the secret payload RAW (the payload ends with
# 0x20 0x0d 0x0a), whereas python-dotenv strips trailing whitespace when reading
# .env, so the two sides HMAC over different strings. If so, the fix is to make
# the VM's JWT_SECRET_KEY carry the identical trailing bytes (quote it in .env),
# or to normalise (.strip()) the secret on both sides in config.py.
# Until this is fixed, app-side SSE reconnects loop forever and LiveOps notices
# never live-update (initial load still works via the main API).
#
# Also worth fixing app-side: the SDK's subscribe XHR handler treats a 401 as a
# dropped stream (it never checks xhr.status in onloadend) and retries forever
# with 1s/2s/4s…30s backoff — see xgaming-nova-react-sdk NovaContext connectSSE.
#
# Required env vars on Cloud Run (steps 5 & 6):
#   NOTICE_SERVICE_URL     (VM internal IP, e.g. http://10.128.0.2:8001)
#   NOTICE_SERVICE_SECRET  (shared secret, must match the VM's value)

# 8. Get URL and run smoke test
API_URL=$(gcloud run services describe "$IMAGE_NAME" \
  --region="$REGION" --project="$PROJECT_ID" \
  --format='value(status.url)')

echo ""
echo "=== Deployment complete ==="
echo "  API URL: $API_URL"
echo "  Health:  $API_URL/health"
echo ""
echo "Run smoke tests:"
echo "  python scripts/smoke_test.py --base-url $API_URL"
