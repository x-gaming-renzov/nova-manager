#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────
# GCP Infrastructure Setup — Run as pranaypandit12@gmail.com
# Creates: Cloud SQL, GCE data VM, VPC connector, Artifact
# Registry, and secrets. Run ONCE before first deploy.
# ──────────────────────────────────────────────────────────────
set -euo pipefail

PROJECT_ID="xgaminn"
REGION="us-central1"
ZONE="${REGION}-a"
SA_EMAIL="nova-manager-sa@${PROJECT_ID}.iam.gserviceaccount.com"

echo "=== Activating deployer account ==="
gcloud config set account pranaypandit12@gmail.com
gcloud config set project "$PROJECT_ID"

# ── 1. Artifact Registry ─────────────────────────────────────
echo "=== Creating Artifact Registry ==="
gcloud artifacts repositories describe app-images --location="$REGION" 2>/dev/null \
  || gcloud artifacts repositories create app-images \
       --location="$REGION" \
       --repository-format=docker \
       --project="$PROJECT_ID"

# ── 2. VPC Serverless Connector ──────────────────────────────
echo "=== Creating VPC Connector ==="
gcloud compute networks vpc-access connectors describe nova-connector \
  --region="$REGION" --project="$PROJECT_ID" 2>/dev/null \
  || gcloud compute networks vpc-access connectors create nova-connector \
       --region="$REGION" \
       --network=default \
       --range=10.8.0.0/28 \
       --project="$PROJECT_ID"

# ── 3. Cloud SQL PostgreSQL ──────────────────────────────────
echo "=== Creating Cloud SQL instance (db-g1-small, ~\$28/mo) ==="
# Check if instance exists
if gcloud sql instances describe nova-db --project="$PROJECT_ID" 2>/dev/null; then
  echo "Cloud SQL instance nova-db already exists."
else
  gcloud sql instances create nova-db \
    --database-version=POSTGRES_15 \
    --tier=db-g1-small \
    --region="$REGION" \
    --storage-size=10GB \
    --storage-type=SSD \
    --project="$PROJECT_ID"

  # Create database
  gcloud sql databases create nova_manager \
    --instance=nova-db \
    --project="$PROJECT_ID"

  # Generate and set password
  DB_PASSWORD=$(openssl rand -base64 24)
  gcloud sql users create nova_user \
    --instance=nova-db \
    --password="$DB_PASSWORD" \
    --project="$PROJECT_ID"

  echo ""
  echo "!! SAVE THIS — Cloud SQL credentials:"
  echo "   User:     nova_user"
  echo "   Password: $DB_PASSWORD"
  echo "   Database: nova_manager"
  echo "   Instance: ${PROJECT_ID}:${REGION}:nova-db"
  echo ""
fi

# ── 4. GCE Data VM (Redis + ClickHouse) ──────────────────────
echo "=== Creating data services VM (e2-small, ~\$17/mo) ==="
if gcloud compute instances describe nova-data --zone="$ZONE" --project="$PROJECT_ID" 2>/dev/null; then
  echo "VM nova-data already exists."
else
  gcloud compute instances create nova-data \
    --project="$PROJECT_ID" \
    --zone="$ZONE" \
    --machine-type=e2-small \
    --image-family=cos-stable \
    --image-project=cos-cloud \
    --tags=nova-data-services \
    --boot-disk-size=20GB \
    --boot-disk-type=pd-ssd \
    --metadata=startup-script='#!/bin/bash
docker run -d --name redis --restart=always -p 6379:6379 redis:7-alpine 2>/dev/null || docker start redis
docker run -d --name clickhouse --restart=always \
  -p 8123:8123 -p 9000:9000 \
  -e CLICKHOUSE_DEFAULT_ACCESS_MANAGEMENT=1 \
  -v /var/lib/clickhouse:/var/lib/clickhouse \
  clickhouse/clickhouse-server:24.8-alpine 2>/dev/null || docker start clickhouse'

  echo "Waiting for VM to start..."
  sleep 10
fi

# Get VM internal IP for env vars
DATA_VM_IP=$(gcloud compute instances describe nova-data \
  --zone="$ZONE" --project="$PROJECT_ID" \
  --format='value(networkInterfaces[0].networkIP)')
echo "Data VM internal IP: $DATA_VM_IP"

# ── 5. Firewall rules ────────────────────────────────────────
echo "=== Creating firewall rules ==="
gcloud compute firewall-rules describe allow-nova-data --project="$PROJECT_ID" 2>/dev/null \
  || gcloud compute firewall-rules create allow-nova-data \
       --allow=tcp:8123,tcp:6379 \
       --source-ranges=10.8.0.0/28 \
       --target-tags=nova-data-services \
       --project="$PROJECT_ID"

# ── 6. Secrets ────────────────────────────────────────────────
echo "=== Creating secrets (you'll need to set values) ==="
for SECRET in DATABASE_URL JWT_SECRET_KEY REDIS_URL OPENAI_API_KEY BREVO_API_KEY CLICKHOUSE_PASSWORD; do
  gcloud secrets describe "$SECRET" --project="$PROJECT_ID" 2>/dev/null \
    || echo "PLACEHOLDER" | gcloud secrets create "$SECRET" \
         --data-file=- \
         --project="$PROJECT_ID"
done

echo ""
echo "=== Infrastructure setup complete ==="
echo ""
echo "Data VM IP: $DATA_VM_IP"
echo ""
echo "IMPORTANT: Update secrets with real values:"
echo "  # Database URL (use Cloud SQL connection name for Cloud Run):"
echo "  echo -n 'postgresql://nova_user:PASSWORD@/nova_manager?host=/cloudsql/${PROJECT_ID}:${REGION}:nova-db' \\"
echo "    | gcloud secrets versions add DATABASE_URL --data-file=- --project=$PROJECT_ID"
echo ""
echo "  # Redis (on data VM):"
echo "  echo -n 'redis://${DATA_VM_IP}:6379/0' \\"
echo "    | gcloud secrets versions add REDIS_URL --data-file=- --project=$PROJECT_ID"
echo ""
echo "  # JWT secret:"
echo "  openssl rand -base64 32 | tr -d '\\n' \\"
echo "    | gcloud secrets versions add JWT_SECRET_KEY --data-file=- --project=$PROJECT_ID"
echo ""
echo "  # Other secrets (OPENAI_API_KEY, BREVO_API_KEY, CLICKHOUSE_PASSWORD):"
echo "  echo -n 'your-value' | gcloud secrets versions add SECRET_NAME --data-file=- --project=$PROJECT_ID"
echo ""
echo "Next: Update secrets, then run ./deploy_to_gcp.sh"
