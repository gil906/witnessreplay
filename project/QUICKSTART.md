# Quick Start Guide

## Prerequisites
- Python 3.11+
- Google Cloud account
- Gemini API key from [Google AI Studio](https://makersuite.google.com/app/apikey)

## Local Development (5 minutes)

### 1. Clone and Setup
```bash
cd /mnt/media/witnessreplay/project
cd backend
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure Environment
```bash
# Create .env file in the backend directory
cat > .env << EOF
GOOGLE_API_KEY=your_gemini_api_key_here
GCP_PROJECT_ID=your-gcp-project-id
GCS_BUCKET=witnessreplay-images
FIRESTORE_COLLECTION=reconstruction_sessions
ENVIRONMENT=development
DEBUG=true
EOF
```

### 3. Run the Application
```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8080
```

### 4. Open in Browser
```
http://localhost:8080
```

## Cloud Deployment (10 minutes)

### Option 1: Quick Deploy Script
```bash
cd deploy
export GCP_PROJECT_ID=your-project-id
export GCP_REGION=us-central1
./deploy.sh
```

### Option 2: Terraform
```bash
cd deploy/terraform
terraform init
terraform apply -var="project_id=your-project-id" -var="gemini_api_key=your-key"
```

### Option 3: Cloud Build
```bash
gcloud builds submit --config deploy/cloudbuild.yaml .
```

## Testing the Application

### 1. Create a Session
```bash
curl -X POST http://localhost:8080/api/sessions \
  -H "Content-Type: application/json" \
  -d '{"title": "Test Scene"}'
```

### 2. Use the Web Interface
1. Open http://localhost:8080
2. Click "New Session"
3. Click "Start Speaking" or type in text input
4. Describe a scene
5. Watch the agent ask questions and generate reconstructions

### 3. Check Health
```bash
curl http://localhost:8080/api/health
```

## Environment Variables Reference

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GOOGLE_API_KEY` | Yes | - | Gemini API key |
| `GCP_PROJECT_ID` | Yes* | - | GCP project ID (*optional for local dev) |
| `GCS_BUCKET` | No | witnessreplay-images | Cloud Storage bucket name |
| `FIRESTORE_COLLECTION` | No | reconstruction_sessions | Firestore collection |
| `ENVIRONMENT` | No | development | Environment (development/production) |
| `DEBUG` | No | true | Enable debug logging |
| `PORT` | No | 8080 | Server port |
| `HOST` | No | 0.0.0.0 | Server host |

## Troubleshooting

### Import Errors
```bash
# Make sure you're in the venv
source venv/bin/activate
# Reinstall dependencies
pip install -r requirements.txt
```

### GCP Services Not Available
- For local development, the app will work without GCP services
- Sessions won't persist (in-memory only)
- Images won't be stored (placeholder only)
- This is fine for testing the conversation flow

### Port Already in Use
```bash
# Use a different port
uvicorn app.main:app --reload --port 8081
```

### WebSocket Connection Issues
- Check that you're using the same protocol (http/https)
- Verify CORS settings in config.py
- Check browser console for errors

## API Examples

### List Sessions
```bash
curl http://localhost:8080/api/sessions
```

### Get Session Details
```bash
curl http://localhost:8080/api/sessions/{session_id}
```

### Export to PDF
```bash
curl http://localhost:8080/api/sessions/{session_id}/export -o scene.pdf
```

### WebSocket Test (JavaScript)
```javascript
const ws = new WebSocket('ws://localhost:8080/ws/your-session-id');
ws.onopen = () => {
    ws.send(JSON.stringify({
        type: 'text',
        data: {text: 'I saw a red car'}
    }));
};
ws.onmessage = (event) => {
    console.log('Received:', JSON.parse(event.data));
};
```

## Development Tips

### Watch Logs
```bash
# The app logs to stdout
# In production, view Cloud Run logs:
gcloud logging tail "resource.type=cloud_run_revision"
```

### Test Without GCP
The app works locally without GCP services enabled. Just ignore the warnings:
- Firestore client not initialized
- GCS client not initialized
- Image generation not available

Sessions will be stored in memory and images will be placeholders.

### Modify Agent Prompts
Edit `backend/app/agents/prompts.py` to customize the agent's behavior.

### Add New Endpoints
1. Add route in `backend/app/api/routes.py`
2. Use the FastAPI dependency injection
3. Return Pydantic models for automatic validation

## Next Steps
- Read the full README.md
- Check out docs/architecture.md
- Explore the code in backend/app/
- Try the frontend at http://localhost:8080
- Deploy to Cloud Run for production use

## Support
For issues or questions, check:
- README.md for full documentation
- docs/architecture.md for technical details
- GitHub Issues (when repo is published)
