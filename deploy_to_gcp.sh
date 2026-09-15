#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────
# Nova Manager — Deploy to GCP Cloud Run
# Run as tyrongamess@gmail.com
# Prerequisites: scripts/gcp_admin_setup.sh and
#                scripts/gcp_infra_setup.sh completed
#
# Usage:
#   ./deploy_to_gcp.sh staging     # deploys staging environment
#   ./deploy_to_gcp.sh production  # deploys production environment
# ──────────────────────────────────────────────────────────────
set -euo pipefail
export MSYS_NO_PATHCONV=1

### ── ENVIRONMENT ARGUMENT ───────────────────────────────────
DEPLOY_ENV="${1:-}"
if [[ -z "$DEPLOY_ENV" ]] || [[ "$DEPLOY_ENV" != "staging" && "$DEPLOY_ENV" != "production" ]]; then
  echo "Usage: $0 <staging|production>"
  echo ""
  echo "  staging     → deploys nova-manager-staging services (NOVA_ENV=staging)"
  echo "  production  → deploys nova-manager services (NOVA_ENV=production)"
  exit 1
fi

### ── PROJECT SETTINGS ────────────────────────────────────────
PROJECT_ID="xgaminn"
REGION="us-central1"
REPO="app-images"
TAG="$(date +%Y%m%d%H%M%S)"
SA_EMAIL="nova-manager-sa@${PROJECT_ID}.iam.gserviceaccount.com"
CLOUD_SQL_INSTANCE="${PROJECT_ID}:${REGION}:nova-db"
VPC_CONNECTOR="nova-connector"

### ── ENVIRONMENT-SPECIFIC NAMES & SECRETS ────────────────────
if [[ "$DEPLOY_ENV" == "staging" ]]; then
  IMAGE_NAME="nova-manager-staging"
  WORKER_NAME="nova-manager-worker-staging"
  MIGRATE_JOB="nova-migrate-staging"
  CH_BOOTSTRAP_JOB="nova-clickhouse-bootstrap-staging"
  DB_URL_SECRET="DATABASE_URL_STAGING"
  NOVA_ENV="staging"
else
  IMAGE_NAME="nova-manager"
  WORKER_NAME="nova-manager-worker"
  MIGRATE_JOB="nova-migrate"
  CH_BOOTSTRAP_JOB="nova-clickhouse-bootstrap"
  DB_URL_SECRET="DATABASE_URL"
  NOVA_ENV="production"
fi
### ────────────────────────────────────────────────────────────

# Get data VM internal IP for ClickHouse env vars
DATA_VM_IP=$(gcloud compute instances describe nova-data \
  --zone="${REGION}-a" --project="$PROJECT_ID" \
  --format='value(networkInterfaces[0].networkIP)')

echo "=== Config ==="
echo "  Environment: $DEPLOY_ENV"
echo "  Project:     $PROJECT_ID"
echo "  Region:      $REGION"
echo "  Tag:         $TAG"
echo "  API Service: $IMAGE_NAME"
echo "  Worker:      $WORKER_NAME"
echo "  DB Secret:   $DB_URL_SECRET"
echo "  NOVA_ENV:    $NOVA_ENV"
echo "  Data VM IP:  $DATA_VM_IP"
echo ""

# 1. Configure gcloud
gcloud config set account tyrongamess@gmail.com
gcloud config set project "$PROJECT_ID"
gcloud config set run/region "$REGION"

# 2. Build & push (shared image — same code, env vars differentiate)
FULL_IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/nova-manager:${TAG}"
echo "=== Building image: $FULL_IMAGE ==="
gcloud builds submit --tag "$FULL_IMAGE"

# 3. Run Alembic migrations (Cloud Run Job)
echo "=== Running database migrations ($MIGRATE_JOB) ==="
if gcloud run jobs describe "$MIGRATE_JOB" --region="$REGION" --project="$PROJECT_ID" 2>/dev/null; then
  gcloud run jobs update "$MIGRATE_JOB" \
    --image="$FULL_IMAGE" \
    --region="$REGION" \
    --project="$PROJECT_ID"
  gcloud run jobs execute "$MIGRATE_JOB" \
    --region="$REGION" \
    --project="$PROJECT_ID" \
    --wait
else
  gcloud run jobs create "$MIGRATE_JOB" \
    --image="$FULL_IMAGE" \
    --command="alembic" \
    --args="upgrade,head" \
    --set-cloudsql-instances="$CLOUD_SQL_INSTANCE" \
    --vpc-connector="$VPC_CONNECTOR" \
    --set-secrets="DATABASE_URL=${DB_URL_SECRET}:latest" \
    --service-account="$SA_EMAIL" \
    --region="$REGION" \
    --project="$PROJECT_ID" \
    --max-retries=0 \
    --execute-now --wait
fi

# 4. Run ClickHouse bootstrap (Cloud Run Job)
echo "=== Bootstrapping ClickHouse ($CH_BOOTSTRAP_JOB) ==="
if gcloud run jobs describe "$CH_BOOTSTRAP_JOB" --region="$REGION" --project="$PROJECT_ID" 2>/dev/null; then
  gcloud run jobs update "$CH_BOOTSTRAP_JOB" \
    --image="$FULL_IMAGE" \
    --region="$REGION" \
    --project="$PROJECT_ID"
  gcloud run jobs execute "$CH_BOOTSTRAP_JOB" \
    --region="$REGION" \
    --project="$PROJECT_ID" \
    --wait
else
  gcloud run jobs create "$CH_BOOTSTRAP_JOB" \
    --image="$FULL_IMAGE" \
    --command="python" \
    --args="scripts/bootstrap_clickhouse.py" \
    --set-cloudsql-instances="$CLOUD_SQL_INSTANCE" \
    --vpc-connector="$VPC_CONNECTOR" \
    --set-secrets="DATABASE_URL=${DB_URL_SECRET}:latest,CLICKHOUSE_PASSWORD=CLICKHOUSE_PASSWORD:latest" \
    --set-env-vars="CLICKHOUSE_HOST=${DATA_VM_IP},CLICKHOUSE_PORT=8123,CLICKHOUSE_USER=default,PYTHONPATH=/app,NOVA_ENV=${NOVA_ENV}" \
    --service-account="$SA_EMAIL" \
    --region="$REGION" \
    --project="$PROJECT_ID" \
    --max-retries=0 \
    --execute-now --wait
fi

# 5. Deploy API
echo "=== Deploying API ($IMAGE_NAME) ==="
gcloud run deploy "$IMAGE_NAME" \
  --image="$FULL_IMAGE" \
  --region="$REGION" \
  --platform=managed \
  --allow-unauthenticated \
  --add-cloudsql-instances="$CLOUD_SQL_INSTANCE" \
  --vpc-connector="$VPC_CONNECTOR" \
  --service-account="$SA_EMAIL" \
  --set-secrets="DATABASE_URL=${DB_URL_SECRET}:latest,JWT_SECRET_KEY=JWT_SECRET_KEY:latest,REDIS_URL=REDIS_URL:latest,OPENAI_API_KEY=OPENAI_API_KEY:latest,BREVO_API_KEY=BREVO_API_KEY:latest,CLICKHOUSE_PASSWORD=CLICKHOUSE_PASSWORD:latest,NOTICE_SERVICE_SECRET=NOTICE_SERVICE_SECRET:latest,NOTICE_SERVICE_URL=NOTICE_SERVICE_URL:latest,NOVA_ADMIN_KEY=NOVA_ADMIN_KEY:latest" \
  --set-env-vars="CLICKHOUSE_HOST=${DATA_VM_IP},CLICKHOUSE_PORT=8123,CLICKHOUSE_USER=default,NOVA_ENV=${NOVA_ENV}" \
  --memory=512Mi \
  --cpu=1 \
  --min-instances=0 \
  --max-instances=10 \
  --concurrency=80 \
  --port=8000 \
  --project="$PROJECT_ID"

# 6. Deploy Worker
echo "=== Deploying Worker ($WORKER_NAME) ==="
gcloud run deploy "$WORKER_NAME" \
  --image="$FULL_IMAGE" \
  --region="$REGION" \
  --platform=managed \
  --no-allow-unauthenticated \
  --command="python" \
  --args="scripts/run_worker.py" \
  --add-cloudsql-instances="$CLOUD_SQL_INSTANCE" \
  --vpc-connector="$VPC_CONNECTOR" \
  --service-account="$SA_EMAIL" \
  --set-secrets="DATABASE_URL=${DB_URL_SECRET}:latest,JWT_SECRET_KEY=JWT_SECRET_KEY:latest,REDIS_URL=REDIS_URL:latest,CLICKHOUSE_PASSWORD=CLICKHOUSE_PASSWORD:latest,NOTICE_SERVICE_SECRET=NOTICE_SERVICE_SECRET:latest,NOTICE_SERVICE_URL=NOTICE_SERVICE_URL:latest,NOVA_ADMIN_KEY=NOVA_ADMIN_KEY:latest" \
  --set-env-vars="CLICKHOUSE_HOST=${DATA_VM_IP},CLICKHOUSE_PORT=8123,CLICKHOUSE_USER=default,PYTHONPATH=/app,NOVA_ENV=${NOVA_ENV}" \
  --cpu=1 \
  --memory=512Mi \
  --no-cpu-throttling \
  --concurrency=1 \
  --min-instances=1 \
  --max-instances=3 \
  --port=8080 \
  --project="$PROJECT_ID"

# 7. Notice Service (only for production — staging shares it)
if [[ "$DEPLOY_ENV" == "production" ]]; then
  # Notice Service runs on a dedicated GCE VM, NOT Cloud Run.
  # It maintains persistent SSE connections, so it needs a single
  # long-lived process — not Cloud Run's ephemeral containers.
  #
  # VM instance:    notice-service
  # Zone:           us-central1-c
  # systemd unit:   nova-notice.service
  # Run user:       admin2
  # Checkout:       /opt/nova-manager on branch staging
  # Interpreter:    /opt/nova-manager/.venv/bin/python
  # Public URL:     https://sse.api.nova.xgaming.club → VM :8001
  echo "=== Deploying Notice Service (GCE VM) ==="
  gcloud compute ssh notice-service --zone=us-central1-c --project="$PROJECT_ID" \
    --command="sudo -H -u admin2 bash -c \"cd /opt/nova-manager && \
      GIT_SSH_COMMAND='ssh -i ~/.ssh/nova_deploy -o IdentitiesOnly=yes' \
        git fetch origin staging && git checkout -B staging origin/staging\" && \
      sudo systemctl restart nova-notice.service"
fi

# 8. Get URL and run smoke test
API_URL=$(gcloud run services describe "$IMAGE_NAME" \
  --region="$REGION" --project="$PROJECT_ID" \
  --format='value(status.url)')

echo ""
echo "=== Deployment complete ($DEPLOY_ENV) ==="
echo "  API URL: $API_URL"
echo "  Health:  $API_URL/health"
echo ""
echo "Run smoke tests:"
echo "  python scripts/smoke_test.py --base-url $API_URL"
