# WitnessReplay 🎙️

**"Describe what you saw. I'll rebuild the scene."**

WitnessReplay is a voice-driven interactive crime/accident scene reconstruction agent built for the **Gemini Live Agent Challenge**. Witnesses speak naturally about what they saw, and the AI generates progressive scene images, asks clarifying questions, and iteratively refines the visual reconstruction in real-time.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## 🎯 Features

### ✨ Core Features
- ✅ **🎤 Real-Time Voice Input**: Gemini Live API with WebSocket streaming and interruption support
- ✅ **🎬 AI Scene Reconstruction**: Generate photorealistic scene images from verbal descriptions
- ✅ **🔍 Detective Ray Persona**: Professional AI agent with calm, methodical detective personality
- ✅ **❓ Intelligent Questioning**: Context-aware clarifying questions for precision
- ✅ **🔄 Iterative Refinement**: Natural language corrections instantly update the scene
- ✅ **📅 Visual Timeline**: Complete history of scene versions with thumbnails
- ✅ **💾 Session Persistence**: Firestore-backed session storage
- ✅ **📄 PDF Export**: Professional reports with scenes and witness statements
- ✅ **☁️ Cloud-Native**: Deploy to Google Cloud Run with one command

### 🎨 UX/UI Features (v2.0 - Polished)
- ✅ **Dark Forensic Theme**: Professional law enforcement aesthetic with glassmorphism
- ✅ **Real-Time Audio Visualizer**: Circular waveform visualization during recording
- ✅ **Animated Scene Transitions**: Smooth crossfades and loading states
- ✅ **Interactive Timeline**: Click any version to view, compare side-by-side
- ✅ **Session Management UI**: Beautiful session cards with thumbnails
- ✅ **Onboarding Flow**: Step-by-step tutorial for first-time users
- ✅ **Toast Notifications**: Real-time feedback for all operations
- ✅ **Keyboard Shortcuts**: Space to record, Esc to cancel, ? for help
- ✅ **Sound Effects**: Subtle audio feedback (toggleable)
- ✅ **Scene Controls**: Zoom, download, fullscreen on generated images
- ✅ **Responsive Design**: Works on desktop, tablet, and mobile
- ✅ **Accessibility**: ARIA labels, keyboard navigation, screen reader support
- ✅ **Progressive Web App**: Installable with offline manifest
- ✅ **Loading Skeletons**: Smooth skeleton loaders for async content
- ✅ **Stats Dashboard**: Version count, statement count, session duration

## 📸 Screenshots

### Main Interface
![Main Interface](docs/screenshots/main-interface.png)
*Professional 3-column layout: Timeline | Scene Display | Conversation*

### Voice Recording
![Voice Recording](docs/screenshots/recording.png)
*Real-time circular audio waveform visualizer*

### Scene Timeline
![Timeline](docs/screenshots/timeline.png)
*Progressive scene history with thumbnails and change indicators*

### Onboarding
![Onboarding](docs/screenshots/onboarding.png)
*Interactive tutorial introducing Detective Ray*

### Session Management
![Sessions](docs/screenshots/sessions.png)
*Browse and load past reconstruction sessions*

> **Note**: Screenshots will be added before final submission. UI is fully functional.

## 🏗️ Architecture

```
┌─────────────────┐
│   Frontend      │  Voice Input → WebSocket → Backend
│  (HTML/JS)      │  ← Scene Images ← Agent Responses
└────────┬────────┘
         │ WebSocket
         ▼
┌─────────────────┐
│  FastAPI        │  ┌──────────────────┐
│  Backend        │◄─┤ Gemini Live API  │
│                 │  │ (Voice→Text)     │
├─────────────────┤  └──────────────────┘
│ Scene Agent     │  ┌──────────────────┐
│ (Gemini 2.0)    │◄─┤ Image Generation │
│                 │  │ (Scene Images)   │
└────────┬────────┘  └──────────────────┘
         │
    ┌────┴────┬─────────────┐
    ▼         ▼             ▼
┌─────────┐ ┌──────────┐ ┌─────────┐
│Firestore│ │   GCS    │ │ Gemini  │
│Sessions │ │ Images   │ │ Models  │
└─────────┘ └──────────┘ └─────────┘
```

## 🚀 Quick Start

### Prerequisites

- Python 3.11+
- Google Cloud account
- Gemini API key
- Docker (optional, for containerized deployment)

### Local Development

1. **Clone the repository**
```bash
git clone https://github.com/gil906/witnessreplay.git
cd witnessreplay
```

2. **Set up backend**
```bash
cd backend
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

3. **Configure environment variables**
```bash
cp ../.env.example .env
# Edit .env and add your credentials:
# - GOOGLE_API_KEY (Gemini API key)
# - GCP_PROJECT_ID (your GCP project)
# - GCS_BUCKET (name for image storage)
```

4. **Run the backend**
```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8080
```

5. **Open the frontend**
```
http://localhost:8080
```

## ☁️ Cloud Deployment

### Option 1: Quick Deploy Script

```bash
cd deploy
export GCP_PROJECT_ID=your-project-id
export GCP_REGION=us-central1
./deploy.sh
```

### Option 2: Terraform (Infrastructure as Code)

```bash
cd deploy/terraform

terraform init

terraform plan \
  -var="project_id=your-project-id" \
  -var="gemini_api_key=your-api-key"

terraform apply \
  -var="project_id=your-project-id" \
  -var="gemini_api_key=your-api-key"
```

### Option 3: Cloud Build

```bash
gcloud builds submit --config deploy/cloudbuild.yaml .
```

## 📝 Environment Variables

| Variable | Description | Required | Default |
|----------|-------------|----------|---------|
| `GOOGLE_API_KEY` | Gemini API key | Yes | - |
| `GCP_PROJECT_ID` | Google Cloud project ID | Yes | - |
| `GCS_BUCKET` | Cloud Storage bucket for images | Yes | - |
| `FIRESTORE_COLLECTION` | Firestore collection name | No | `reconstruction_sessions` |
| `ENVIRONMENT` | Environment (dev/prod) | No | `development` |
| `DEBUG` | Debug mode | No | `true` |
| `PORT` | Server port | No | `8080` |
| `GEMINI_MODEL` | Gemini model name | No | `gemini-2.0-flash-exp` |

## 🔌 API Documentation

### REST Endpoints

- `GET /api/health` - Health check
- `GET /api/sessions` - List all sessions
- `POST /api/sessions` - Create new session
- `GET /api/sessions/{id}` - Get session details
- `PATCH /api/sessions/{id}` - Update session
- `DELETE /api/sessions/{id}` - Delete session
- `GET /api/sessions/{id}/export` - Export as PDF

### WebSocket Endpoint

`WS /ws/{session_id}`

**Client → Server Messages:**
```json
{
  "type": "audio|text|correction",
  "data": {
    "audio": "base64_audio_data",  // for audio type
    "text": "witness statement"     // for text/correction type
  }
}
```

**Server → Client Messages:**
```json
{
  "type": "text|scene_update|status|error",
  "data": {...},
  "timestamp": "2024-01-01T12:00:00Z"
}
```

## 🛠️ Development

### Project Structure

```
witnessreplay/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI app
│   │   ├── config.py            # Configuration
│   │   ├── api/
│   │   │   ├── routes.py        # REST endpoints
│   │   │   └── websocket.py     # WebSocket handler
│   │   ├── agents/
│   │   │   ├── scene_agent.py   # Core reconstruction agent
│   │   │   └── prompts.py       # System prompts
│   │   ├── services/
│   │   │   ├── image_gen.py     # Image generation
│   │   │   ├── storage.py       # Cloud Storage
│   │   │   └── firestore.py     # Firestore client
│   │   └── models/
│   │       └── schemas.py       # Pydantic models
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── index.html
│   ├── css/styles.css
│   ├── js/
│   │   ├── app.js               # Main application
│   │   └── audio.js             # Audio recording
│   └── assets/
├── deploy/
│   ├── deploy.sh                # Deployment script
│   ├── cloudbuild.yaml          # Cloud Build config
│   └── terraform/               # IaC
├── docs/
│   └── architecture.md
├── .env.example
├── .gitignore
└── README.md
```

### Tech Stack

- **Backend**: FastAPI, Python 3.11
- **AI**: Gemini 2.0 Flash (Live API)
- **Image Gen**: Gemini/Imagen (placeholder implementation)
- **Database**: Google Cloud Firestore
- **Storage**: Google Cloud Storage
- **Deployment**: Docker, Cloud Run
- **Frontend**: Vanilla JavaScript, Web Audio API

## 🧪 Testing

```bash
# Backend tests (when implemented)
cd backend
pytest

# Lint
black app/
flake8 app/
```

## 🤝 Contributing

This is a hackathon project, but contributions are welcome!

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📜 License

MIT License - see LICENSE file for details

## 🏆 Hackathon

Built for the **Gemini Live Agent Challenge**
- **Category**: Live Agents 🗣️ (Real-time Audio/Vision)
- **Tech**: Gemini 2.0, Google GenAI SDK, Cloud Run

## 👤 Author

**gil906**
- GitHub: [@gil906](https://github.com/gil906)

## 🙏 Acknowledgments

- Google Gemini team for the amazing AI capabilities
- FastAPI community
- All witnesses who inspired this project

---

**Built with ❤️ by gil906 for the Gemini Live Agent Challenge**

**v2.0 - Polished Edition** — Featuring Detective Ray's professional forensic interface
