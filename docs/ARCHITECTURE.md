# WitnessReplay - System Architecture

## Overview

WitnessReplay is a cloud-native, real-time voice-driven scene reconstruction system built on Google Cloud Platform and the Gemini Live API.

## High-Level Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                         USER INTERFACE                                │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────┐    │
│  │  Timeline  │  │   Scene    │  │    Chat    │  │  Controls  │    │
│  │   Panel    │  │  Display   │  │   Panel    │  │   (Mic)    │    │
│  └────────────┘  └────────────┘  └────────────┘  └────────────┘    │
└─────────────────────────┬────────────────────────────────────────────┘
                          │ WebSocket + REST API
                          ▼
┌──────────────────────────────────────────────────────────────────────┐
│                      FASTAPI BACKEND                                  │
│  ┌────────────────┐  ┌──────────────┐  ┌──────────────────────┐    │
│  │  REST Routes   │  │  WebSocket   │  │  Request Logging     │    │
│  │  /api/*        │  │  /ws/{sid}   │  │  Middleware          │    │
│  └────────┬───────┘  └──────┬───────┘  └──────────────────────┘    │
│           │                  │                                        │
│           └──────────┬───────┘                                        │
│                      ▼                                                │
│           ┌────────────────────┐                                      │
│           │   Scene Agent      │  (Detective Ray Persona)             │
│           │   - Conversation   │                                      │
│           │   - State Mgmt     │                                      │
│           │   - Corrections    │                                      │
│           └────────┬───────────┘                                      │
│                    │                                                  │
│        ┌───────────┼───────────┐                                      │
│        ▼           ▼           ▼                                      │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐                                │
│  │ Image   │ │Storage  │ │Firestore│                                │
│  │  Gen    │ │Service  │ │Service  │                                │
│  └────┬────┘ └────┬────┘ └────┬────┘                                │
└───────┼───────────┼───────────┼───────────────────────────────────────┘
        │           │           │
        ▼           ▼           ▼
┌──────────────────────────────────────────────────────────────────────┐
│                    GOOGLE CLOUD SERVICES                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────────┐  │
│  │  Gemini API  │  │     GCS      │  │      Firestore           │  │
│  │  - Live API  │  │  (Images)    │  │  (Session Storage)       │  │
│  │  - Image Gen │  │              │  │                          │  │
│  └──────────────┘  └──────────────┘  └──────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────┘
```

## Component Details

### Frontend (Vanilla JS + CSS)

**Files:**
- `index.html` - Main UI structure
- `css/styles.css` - Professional dark theme with glassmorphism
- `js/app.js` - Application core, WebSocket management
- `js/ui.js` - UI utilities (toasts, modals, onboarding)
- `js/audio.js` - Audio recording and visualization
- `manifest.json` - PWA configuration

**Key Features:**
- Real-time WebSocket connection
- Circular audio waveform visualizer (Web Audio API)
- Interactive timeline with version history
- Session management UI
- Keyboard shortcuts (Space, Esc, ?)
- Toast notifications
- Onboarding flow
- Responsive design (mobile, tablet, desktop)

### Backend (FastAPI + Python 3.11)

**Structure:**
```
app/
├── main.py              # FastAPI app, CORS, static files
├── config.py            # Environment-based configuration
├── api/
│   ├── routes.py        # REST endpoints (CRUD sessions, export)
│   └── websocket.py     # WebSocket handler for real-time comms
├── agents/
│   ├── scene_agent.py   # Core reconstruction agent (Detective Ray)
│   └── prompts.py       # System prompts, persona definition
├── services/
│   ├── image_gen.py     # Image generation (Gemini/Imagen)
│   ├── storage.py       # GCS client for image storage
│   └── firestore.py     # Firestore client for sessions
└── models/
    └── schemas.py       # Pydantic models for validation
```

**API Endpoints:**
- `GET /api/health` - Health check
- `GET /api/sessions` - List sessions
- `POST /api/sessions` - Create session
- `GET /api/sessions/{id}` - Get session
- `PATCH /api/sessions/{id}` - Update session
- `DELETE /api/sessions/{id}` - Delete session
- `GET /api/sessions/{id}/export` - Export PDF
- `WS /ws/{session_id}` - WebSocket for real-time interaction

### Scene Agent (Detective Ray)

**Personality:**
- Calm, methodical detective
- Professional and reassuring tone
- Asks targeted, clarifying questions
- Acknowledges corrections naturally

**State Management:**
- Maintains conversation context
- Tracks all scene elements (objects, positions, colors)
- Handles corrections ("The car was blue, not red")
- Manages confidence scores

**Workflow:**
1. Listen to witness statement
2. Extract scene elements
3. Generate scene image
4. Ask clarifying questions
5. Process corrections
6. Update scene
7. Save version to timeline

### Data Flow

**Voice Input → Scene Generation:**
```
User speaks
    ↓
Browser records audio (MediaRecorder API)
    ↓
Send base64 audio via WebSocket
    ↓
Backend receives audio
    ↓
Gemini Live API transcribes audio → text
    ↓
Scene Agent processes text
    ↓
Extract scene elements (structured JSON)
    ↓
Generate scene image (Gemini/Imagen)
    ↓
Upload image to GCS
    ↓
Save to Firestore
    ↓
Send image URL + description via WebSocket
    ↓
Frontend displays scene + adds to timeline
```

**Correction Handling:**
```
User: "Actually, the car was blue, not red"
    ↓
Scene Agent identifies correction
    ↓
Update scene state: car.color = "blue"
    ↓
Re-generate scene with correction
    ↓
Send updated scene
    ↓
Timeline shows new version with change indicator
```

## Database Schema (Firestore)

**Collection: `reconstruction_sessions`**

```json
{
  "id": "uuid",
  "title": "Session 2024-01-15 10:30",
  "created_at": "2024-01-15T10:30:00Z",
  "updated_at": "2024-01-15T10:45:00Z",
  "status": "active | completed | archived",
  "metadata": {
    "witness_name": "optional",
    "location": "optional",
    "case_number": "optional"
  },
  "witness_statements": [
    {
      "timestamp": "2024-01-15T10:31:00Z",
      "text": "I saw a blue car...",
      "audio_url": "gs://bucket/audio/xyz.webm"
    }
  ],
  "scene_versions": [
    {
      "version": 1,
      "timestamp": "2024-01-15T10:32:00Z",
      "description": "Blue sedan on Main St...",
      "image_url": "gs://bucket/scenes/abc.png",
      "scene_data": {
        "elements": [
          {
            "type": "vehicle",
            "color": "blue",
            "position": "center-left",
            "confidence": 0.95
          }
        ]
      },
      "changes": "Initial generation"
    }
  ]
}
```

## Cloud Infrastructure

### Deployment Options

**Option 1: Cloud Run (Recommended)**
```bash
gcloud builds submit --config deploy/cloudbuild.yaml .
gcloud run deploy witnessreplay \
  --source . \
  --region us-central1 \
  --allow-unauthenticated
```

**Option 2: Terraform**
```hcl
resource "google_cloud_run_service" "witnessreplay" {
  name     = "witnessreplay"
  location = var.region
  
  template {
    spec {
      containers {
        image = "gcr.io/${var.project_id}/witnessreplay:latest"
        env {
          name  = "GOOGLE_API_KEY"
          value = var.gemini_api_key
        }
      }
    }
  }
}
```

### Required GCP Services

- **Cloud Run**: Backend hosting
- **Cloud Storage**: Image storage
- **Firestore**: Session persistence
- **Cloud Build**: CI/CD
- **Gemini API**: AI capabilities
- **Secret Manager**: Credentials (optional)

### Environment Variables

See `.env.example` for complete list.

## Security Considerations

- API keys stored in environment variables
- CORS configured for allowed origins
- Input validation on all endpoints
- Rate limiting (planned)
- Session isolation
- Secure WebSocket connections (WSS in production)

## Performance Optimizations

- WebSocket for real-time communication (lower latency than HTTP polling)
- Image compression before storage
- Firestore indexes for fast session queries
- Frontend: Lazy loading, skeleton loaders
- Backend: Async/await for non-blocking I/O

## Monitoring & Logging

- Structured logging (JSON format)
- Request ID middleware for tracing
- Health check endpoint
- Service health indicators (Firestore, GCS, Gemini API)

## Future Enhancements

- [ ] Video scene generation
- [ ] Multi-witness collaboration
- [ ] 3D scene reconstruction
- [ ] Mobile app (React Native)
- [ ] Advanced analytics dashboard
- [ ] Integration with law enforcement systems

---

**Last Updated**: 2024 (Polisher Agent v2.0)
