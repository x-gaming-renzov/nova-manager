#!/usr/bin/env bash
set -euo pipefail

### ── PROJECT SETTINGS ─────────────────────────────
PROJECT_ID="xg-nova-infra"
REGION="us-central1"
REPO="app-images"
IMAGE_NAME="nova-manager"
TAG="prod"                       # change to v2, $(date +%Y%m%d%H%M) etc.
### ────────────────────────────────────────────────

# 1 Configure gcloud
gcloud config set project "$PROJECT_ID"
gcloud config set run/region "$REGION"

# 2 Make sure the Artifact Registry repo exists
gcloud artifacts repositories describe "$REPO" --location="$REGION" \
  || gcloud artifacts repositories create "$REPO" \
       --location="$REGION" --repository-format=docker

# 3 Grant Cloud Build the writer role (idempotent)
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')
for SA in "$PROJECT_NUMBER@cloudbuild.gserviceaccount.com" \
          "$PROJECT_NUMBER-compute@developer.gserviceaccount.com"; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:$SA" --role="roles/artifactregistry.writer" --quiet || true
done

# 4 Build & push
FULL_IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/${IMAGE_NAME}:${TAG}"
gcloud builds submit --tag "$FULL_IMAGE"

# # 5 Deploy
gcloud run deploy "$IMAGE_NAME" \
  --image="$FULL_IMAGE" \
  --region="$REGION" \
  --platform=managed \
  --allow-unauthenticated

#6 Deploy worker
gcloud run deploy "nova-manager-worker" \
  --image="$FULL_IMAGE" \
  --region="$REGION" \
  --platform=managed \
  --command="python,scripts/run_worker.py" \
  --no-allow-unauthenticated \
  --cpu=1 \
  --no-cpu-throttling \
  --concurrency=1 \
  --min-instances=1 \
  --max-instances=3
