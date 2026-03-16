#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────
# GCP Admin Setup — Run as admin2@xgaming.club
# One-time project setup: enable APIs, create service account,
# grant deployer permissions to pranaypandit12@gmail.com
# ──────────────────────────────────────────────────────────────
set -euo pipefail

PROJECT_ID="xgaminn"
DEPLOYER="pranaypandit12@gmail.com"
SERVICE_ACCOUNT="nova-manager-sa"
SA_EMAIL="${SERVICE_ACCOUNT}@${PROJECT_ID}.iam.gserviceaccount.com"

echo "=== Activating admin account ==="
gcloud config set account admin2@xgaming.club
gcloud config set project "$PROJECT_ID"

# ── 1. Enable required APIs ──────────────────────────────────
echo "=== Enabling APIs ==="
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com \
  compute.googleapis.com \
  sqladmin.googleapis.com \
  vpcaccess.googleapis.com \
  --project="$PROJECT_ID"

# ── 2. Create service account for Cloud Run ──────────────────
echo "=== Creating service account ==="
gcloud iam service-accounts describe "$SA_EMAIL" --project="$PROJECT_ID" 2>/dev/null \
  || gcloud iam service-accounts create "$SERVICE_ACCOUNT" \
       --display-name="Nova Manager Service Account" \
       --project="$PROJECT_ID"

echo "=== Granting service account roles ==="
for ROLE in \
  roles/cloudsql.client \
  roles/secretmanager.secretAccessor \
  roles/logging.logWriter \
  roles/monitoring.metricWriter; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:$SA_EMAIL" \
    --role="$ROLE" --quiet
done

# ── 3. Grant deployer (pranay) permissions ───────────────────
echo "=== Granting deployer permissions to $DEPLOYER ==="
for ROLE in \
  roles/run.admin \
  roles/artifactregistry.admin \
  roles/cloudbuild.builds.editor \
  roles/secretmanager.admin \
  roles/cloudsql.admin \
  roles/iam.serviceAccountUser \
  roles/compute.instanceAdmin.v1 \
  roles/vpcaccess.admin; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="user:$DEPLOYER" \
    --role="$ROLE" --quiet
done

# ── 4. Grant Cloud Build the Artifact Registry writer role ───
echo "=== Granting Cloud Build AR writer ==="
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')
for SA in \
  "${PROJECT_NUMBER}@cloudbuild.gserviceaccount.com" \
  "${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:$SA" \
    --role="roles/artifactregistry.writer" --quiet || true
done

echo ""
echo "=== Admin setup complete ==="
echo "Deployer $DEPLOYER now has permissions to:"
echo "  - Build and push Docker images"
echo "  - Create/manage Cloud Run services"
echo "  - Create/manage Cloud SQL instances"
echo "  - Create/manage Compute Engine VMs"
echo "  - Create/manage secrets"
echo "  - Create VPC connectors"
echo ""
echo "Next: Pranay should run scripts/gcp_infra_setup.sh"
