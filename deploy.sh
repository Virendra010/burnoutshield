#!/bin/bash

# Configuration
REGION="us-central1"
SERVICE_NAME="burnoutshield"
PROJECT_ID=burnoutshield

echo "🚀 Deploying BurnoutShield to Google Cloud Run ($REGION)..."

# Ensure token.json exists so the container starts fully authenticated
if [ ! -f "token.json" ]; then
    echo "⚠️ Warning: token.json not found! You won't be connected to Google Workspace in the cloud."
    echo "Please test locally first and click 'Connect Google' to generate the token."
    read -p "Deploy anyway without Google Calendar/Gmail data? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Deploy from source code
gcloud run deploy $SERVICE_NAME \
    --source . \
    --region=$REGION \
    --allow-unauthenticated \
    --set-env-vars="GOOGLE_CLOUD_PROJECT=$PROJECT_ID,GOOGLE_CALENDAR_ENABLED=true,GOOGLE_GMAIL_ENABLED=true,FLASK_SECRET=prod-secret-key-$(date +%s)"

echo "✅ Deployment complete!"
echo "If you get 'Internal Server Error' when accessing the URL, ensure your Google APIs are enabled."
