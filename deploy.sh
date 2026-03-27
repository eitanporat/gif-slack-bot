#!/bin/bash
set -e

PROJECT=ltx-dev-txt2img
REGION=us-central1
SERVICE=gif-slack-bot
IMAGE=gcr.io/$PROJECT/$SERVICE

echo "Building and pushing Docker image..."
gcloud builds submit --tag $IMAGE --project=$PROJECT

echo "Deploying to Cloud Run..."
gcloud run deploy $SERVICE \
  --image $IMAGE \
  --platform managed \
  --region $REGION \
  --project $PROJECT \
  --allow-unauthenticated \
  --timeout 300 \
  --concurrency 10 \
  --set-secrets="SLACK_BOT_TOKEN=SLACK_BOT_TOKEN:latest,SLACK_SIGNING_SECRET=SLACK_SIGNING_SECRET:latest,LTX_API_KEY=LTX_API_KEY:latest,LTX_API_URL=LTX_API_URL:latest"

echo "Service URL:"
gcloud run services describe $SERVICE --region $REGION --project $PROJECT --format="value(status.url)"
