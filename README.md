# 🛡️ WitnessReplay
### AI-Powered Witness Interview & Scene Reconstruction

> *Built for the [Gemini Live Agent Challenge](https://geminiliveagentchallenge.devpost.com/) 🏆*
> 
> Voice-driven, multimodal AI agent that transforms witness testimonies into structured crime scene reconstructions — ready for real-world law enforcement deployment.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

---

## 📋 Table of Contents

- [Problem Statement](#-problem-statement)
- [Solution](#-solution)
- [Architecture](#-architecture)
- [Key Features](#-key-features)
- [Tech Stack](#-tech-stack)
- [Gemini API Usage](#-gemini-api-usage)
- [Google Cloud Services](#-google-cloud-services)
- [Quick Start](#-quick-start)
- [Environment Variables](#-environment-variables)
- [API Endpoints](#-api-endpoints)
- [Project Structure](#-project-structure)
- [Security Features](#-security-features)
- [Recent Improvements](#-recent-improvements)
- [Demo](#-demo)
- [Future Roadmap](#-future-roadmap)
- [License](#-license)
- [Challenge Submission](#-challenge-submission)

---

## 🔍 Problem Statement

Witness interviews are one of the most critical — and most fragile — parts of any investigation.

- **Witnesses forget details** and give fragmented, non-linear accounts of events
- **Law enforcement spends hours** conducting and transcribing interviews manually
- **No standardized way** to combine multiple witness accounts into a coherent picture
- **Scene reconstruction is manual and error-prone**, relying on sketches and written notes
- **Language barriers** make it difficult to interview witnesses who don't speak English
- **Contradictions between accounts** are hard to detect across dozens of reports

These problems lead to incomplete investigations, missed evidence, and delayed justice.

---

## 💡 Solution

**WitnessReplay** is an AI-powered live agent that transforms how law enforcement gathers and analyzes witness testimony.

It works by:

1. **Conducting empathetic, structured interviews** as "Detective Ray" — an AI persona that guides witnesses through their account using proven interview techniques
2. **Supporting multimodal input** — voice recording, text chat, phone transcription, and email intake
3. **Automatically generating visual scene reconstructions** from testimony using Gemini's vision and generation capabilities
4. **Grouping related reports into cases** using AI analysis of content, time, and location
5. **Providing a law enforcement admin portal** with case management, report comparison, timeline visualization, and evidence export

The result: investigators get structured, searchable, visual case files in minutes instead of hours.

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                       WitnessReplay                         │
├──────────────┬────────────────────────┬─────────────────────┤
│   Frontend   │    FastAPI Backend     │   Google Cloud      │
├──────────────┼────────────────────────┼─────────────────────┤
│              │                        │                     │
│  Witness     │  Scene Agent           │  Gemini AI          │
│  Portal      │  (Detective Ray)       │  (GenAI SDK)        │
│  ──────────  │  ──────────────        │  ──────────         │
│  Voice Input │  Interview Logic       │  Chat Models        │
│  Text Chat   │  Scene Extraction      │  Vision Models      │
│  WebSocket   │  Contradiction Det.    │  Audio Transcribe   │
│              │  Model Auto-Fallback   │                     │
│              │                        │                     │
│  Admin       │  Case Manager          │  Firestore          │
│  Portal      │  ──────────────        │  (Database)         │
│  ──────────  │  Auto-grouping         │                     │
│  Cases View  │  AI Summaries          │  Cloud Storage      │
│  Reports     │  Incident Classify     │  (Images)           │
│  Analytics   │  Severity Scoring      │                     │
│  Timeline    │                        │  Cloud Run          │
│  Export      │  Services              │  (Hosting)          │
│              │  ──────────            │                     │
│              │  SQLite (fallback DB)  │  Cloud Build        │
│              │  Image Generation      │  (CI/CD)            │
│              │  Usage Tracking        │                     │
│              │  Model Selection       │                     │
│              │  API Key Rotation      │                     │
│              │  Audit Logging         │                     │
│              │                        │                     │
└──────────────┴────────────────────────┴─────────────────────┘
```

**Data Flow:**
```
Witness (Voice/Text) → WebSocket → Scene Agent → Gemini AI
                                       ↓
                              Scene Extraction (JSON)
                                       ↓
                              Image Generation → GCS
                                       ↓
                              Case Manager → Firestore/SQLite
                                       ↓
                              Admin Portal ← REST API
```

---

## ✨ Key Features

| Feature | Description |
|---------|-------------|
| 🎙️ **Multimodal Input** | Voice recording, text chat, phone transcription, email intake |
| 🤖 **AI Detective Interview** | Empathetic, structured questioning with Detective Ray persona |
| 🎨 **Scene Reconstruction** | AI-generated visual scene diagrams from testimony |
| 📁 **Automatic Case Grouping** | Gemini AI matches reports to cases by content, time, and location |
| 📊 **Admin Dashboard** | Case management, timeline, report comparison, analytics, evidence export |
| 🔒 **Security** | Bcrypt auth, rate limiting, CSP headers, path traversal protection, SQL injection hardening |
| 🌐 **Multi-language** | Auto-detects and responds in witness's language |
| 📱 **Mobile-First** | Optimized for iPhone/Android with responsive breakpoints down to 375px |
| ♿ **Accessible** | Focus traps, keyboard navigation, skip-to-content, ARIA attributes, reduced-motion support |
| ⚡ **Real-time** | WebSocket communication with heartbeat, auto-reconnection, and live scene updates |
| 💾 **Dual Storage** | SQLite (local fallback) + Firestore (cloud) — always available |
| 🔄 **Iterative Refinement** | Natural language corrections instantly update the scene |
| 📄 **Evidence Export** | PDF reports, JSON export, bulk CSV, law enforcement evidence format |
| 🎯 **Contradiction Detection** | AI identifies conflicting details across witness accounts |
| 📈 **Confidence Scoring** | Witness reliability and scene completeness assessment |
| 🔀 **Model Auto-Fallback** | Automatic fallback across Gemini models on rate limits |
| 📋 **Audit Trail** | Full audit logging for chain-of-custody compliance |

---

## 🛠️ Tech Stack

| Component | Technology |
|-----------|------------|
| **AI Engine** | Google Gemini (GenAI SDK) — 2.5-pro, 2.5-flash, 2.0-flash with auto-fallback |
| **Backend** | Python 3.11 + FastAPI |
| **Database** | Google Firestore + SQLite (dual backend) |
| **Storage** | Google Cloud Storage |
| **Real-time** | WebSocket (with heartbeat + exponential reconnection) |
| **Frontend** | Vanilla JS / HTML / CSS (no framework dependencies) |
| **Deployment** | Docker + Google Cloud Run |
| **CI/CD** | Google Cloud Build |
| **IaC** | Terraform |
| **Security** | bcrypt, CORS, CSP (no unsafe-eval), rate limiting, path traversal protection, prompt injection defense, request timeouts |

---

## 🤖 Gemini API Usage

### Models Used

| Task | Models (priority order) | Purpose |
|------|------------------------|---------|
| **Scene Reconstruction** | `gemini-2.5-pro` → `gemini-2.5-flash` → `gemini-2.0-flash-exp` → `gemini-2.0-flash` | High-quality scene analysis and extraction |
| **Chat / Interview** | `gemini-2.5-flash-lite` → `gemini-2.0-flash-lite` → `gemini-2.5-flash` | Fast, conversational witness interviews |
| **Vision / Audio** | `gemini-2.5-flash` | Audio transcription, image analysis |

### Gemini Features Leveraged

- **Multi-turn Chat Conversations** — Maintains interview context across the full witness session
- **Audio Transcription (Multimodal)** — Transcribes voice recordings (webm, ogg, wav, mp4) via `Part.from_bytes()`
- **Structured JSON Extraction** — Extracts scene elements, timeline, and metadata from unstructured testimony
- **Text Analysis for Case Matching** — Compares new reports against existing cases for auto-grouping
- **Incident Classification** — Categorizes incidents as accident, crime, incident, or other
- **Summary Generation** — Creates comprehensive multi-witness case summaries
- **Contradiction Detection** — Identifies conflicting details across multiple accounts
- **Automatic Model Fallback** — Switches models on 429/RESOURCE_EXHAUSTED errors with 60s cooldown

---

## ☁️ Google Cloud Services

| Service | Usage |
|---------|-------|
| **Firestore** | Document database for sessions, cases, statements, and audit logs |
| **Cloud Storage** | Hosting generated scene images |
| **Cloud Run** | Containerized application hosting (2Gi memory, 2 CPU) |
| **Cloud Build** | CI/CD pipeline for automated deployments |
| **Secret Manager** | Secure storage for API keys and credentials |

---

## 🚀 Quick Start

### Prerequisites

- Python 3.11+
- [Google Gemini API key](https://aistudio.google.com/apikey)
- Docker (recommended) or Python venv
- Google Cloud account (optional — for Firestore/GCS; SQLite works as fallback)

### Option 1: Docker (Recommended)

```bash
# Clone the repository
git clone https://github.com/gil906/witnessreplay.git
cd witnessreplay/project

# Configure environment
cp .env.example .env
# Edit .env — at minimum set GOOGLE_API_KEY and ADMIN_PASSWORD

# Run with Docker Compose
docker compose up --build -d

# Access the application
# Witness Portal:  http://localhost:8088
# Admin Portal:    http://localhost:8088/admin
# API Docs:        http://localhost:8088/docs
```

### Option 2: Local Development

```bash
# Clone and navigate
git clone https://github.com/gil906/witnessreplay.git
cd witnessreplay/project

# Set up Python environment
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Configure environment
cp ../.env.example .env
# Edit .env with your credentials

# Run the server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8080

# Open http://localhost:8080
```

### Option 3: Cloud Deploy

```bash
# Quick deploy to Cloud Run
cd deploy
export GCP_PROJECT_ID=your-project-id
export GCP_REGION=us-central1
./deploy.sh

# Or with Terraform
cd deploy/terraform
terraform init
terraform apply -var="project_id=your-project-id" -var="gemini_api_key=your-key"

# Or with Cloud Build
gcloud builds submit --config deploy/cloudbuild.yaml .
```

---

## 📝 Environment Variables

| Variable | Description | Required | Default |
|----------|-------------|----------|---------|
| `GOOGLE_API_KEY` | Gemini API key | **Yes** | — |
| `GOOGLE_API_KEYS` | Comma-separated keys for rotation | No | — |
| `GCP_PROJECT_ID` | Google Cloud project ID | For cloud features | — |
| `GCS_BUCKET` | Cloud Storage bucket for images | For cloud features | `witnessreplay-images` |
| `FIRESTORE_COLLECTION` | Firestore collection name | No | `reconstruction_sessions` |
| `ADMIN_PASSWORD` | Admin portal password | **Yes** | — |
| `ENVIRONMENT` | `development` or `production` | No | `production` |
| `DEBUG` | Enable debug mode | No | `false` |
| `PORT` | Server port | No | `8080` |
| `HOST` | Server host | No | `0.0.0.0` |
| `GEMINI_MODEL` | Default Gemini model | No | `gemini-2.5-flash` |
| `GEMINI_VISION_MODEL` | Vision/audio model | No | `gemini-2.5-flash` |
| `ALLOWED_ORIGINS` | CORS allowed origins | No | `http://localhost:8088,http://localhost:3000` |
| `ENFORCE_RATE_LIMITS` | Enable rate limiting | No | `true` |
| `MAX_REQUESTS_PER_MINUTE` | Rate limit threshold | No | `60` |
| `SESSION_TIMEOUT_MINUTES` | Session expiry | No | `60` |
| `MAX_SESSION_SIZE_MB` | Max session data size | No | `100` |
| `DATABASE_PATH` | SQLite database path | No | `/app/data/witnessreplay.db` |

---

## 🔌 API Endpoints

### Authentication
| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/auth/login` | Admin login |
| `POST` | `/api/auth/logout` | Admin logout |
| `GET` | `/api/auth/verify` | Verify authentication |

### Sessions (Witness Reports)
| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/sessions` | List all sessions |
| `POST` | `/api/sessions` | Create new session |
| `GET` | `/api/sessions/{id}` | Get session details |
| `PATCH` | `/api/sessions/{id}` | Update session |
| `DELETE` | `/api/sessions/{id}` | Delete session |

### Session Analysis
| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/sessions/{id}/insights` | Scene complexity, completeness |
| `GET` | `/api/sessions/{id}/timeline` | Temporal event timeline |
| `GET` | `/api/sessions/{id}/contradictions` | Detected contradictions |
| `GET` | `/api/sessions/{id}/confidence` | Confidence assessment |
| `GET` | `/api/sessions/{id}/next-question` | AI-suggested follow-up |
| `GET` | `/api/sessions/compare/{id1}/{id2}` | Compare two sessions |

### Export
| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/sessions/{id}/export` | PDF export |
| `GET` | `/api/sessions/{id}/export/json` | JSON export |
| `GET` | `/api/sessions/{id}/export/evidence` | Law enforcement evidence format |
| `GET` | `/api/sessions/export/bulk` | Bulk export (JSON/CSV) |

### Cases
| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/cases` | List cases |
| `GET` | `/api/cases/{id}` | Get case details |
| `PATCH` | `/api/cases/{id}` | Update case |
| `POST` | `/api/cases/{id}/summary` | Generate AI case summary |

### Models & System
| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/models` | List available models |
| `GET` | `/api/models/status` | Model availability status |
| `POST` | `/api/models/select` | Select active model |
| `GET` | `/api/health` | Health check |
| `GET` | `/api/metrics` | Performance metrics |
| `GET` | `/api/version` | API version |

### WebSocket
| Endpoint | Description |
|----------|-------------|
| `WS /ws/{session_id}` | Real-time interview communication |

**Client → Server:** `{ "type": "audio|text|correction", "data": { ... } }`  
**Server → Client:** `{ "type": "text|scene_update|status|error", "data": { ... } }`

---

## 📁 Project Structure

```
project/
├── backend/
│   ├── app/
│   │   ├── main.py                  # FastAPI app, middleware, security
│   │   ├── agents/
│   │   │   ├── scene_agent.py       # Core AI agent (Detective Ray)
│   │   │   └── prompts.py           # System prompts & interview logic
│   │   ├── models/
│   │   │   └── schemas.py           # Pydantic data models
│   │   ├── services/
│   │   │   ├── case_manager.py      # AI case grouping & classification
│   │   │   ├── database.py          # SQLite persistent storage
│   │   │   ├── firestore.py         # Firestore cloud storage
│   │   │   ├── storage.py           # Google Cloud Storage
│   │   │   ├── image_gen.py         # Scene image generation
│   │   │   ├── model_selector.py    # Automatic model fallback
│   │   │   ├── api_key_manager.py   # API key rotation
│   │   │   ├── usage_tracker.py     # Token & usage tracking
│   │   │   ├── contradiction_detector.py
│   │   │   ├── complexity_scorer.py
│   │   │   ├── question_generator.py
│   │   │   ├── evidence.py
│   │   │   ├── relationships.py
│   │   │   ├── metrics.py
│   │   │   └── cache.py
│   │   └── middleware/
│   │       └── request_logging.py   # Request logging & metrics
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── index.html                   # Witness portal
│   ├── admin.html                   # Admin / law enforcement portal
│   ├── css/
│   │   ├── styles.css               # Witness portal styles
│   │   └── admin.css                # Admin portal styles
│   └── js/
│       ├── app.js                   # Main application logic
│       ├── admin.js                 # Admin portal logic
│       ├── audio.js                 # Audio recording & TTS playback
│       ├── ui.js                    # UI manager (modals, focus traps, toasts)
│       └── vad.js                   # Voice Activity Detection
│   ├── sw.js                        # Service worker (offline, cache eviction)
├── deploy/
│   ├── deploy.sh                    # Cloud Run deployment script
│   ├── cloudbuild.yaml              # Cloud Build CI/CD pipeline
│   └── terraform/                   # Infrastructure as Code
├── tests/
│   ├── test_websocket.py
│   └── audio_fixtures/              # Test audio files
├── docs/
├── docker-compose.yml
├── .env.example
├── .gitignore
└── README.md
```

---

## 🔒 Security Features

| Feature | Implementation |
|---------|---------------|
| **Authentication** | Bcrypt password hashing for admin portal |
| **Rate Limiting** | Per-minute request limits with `429 Retry-After` headers |
| **Content Security Policy** | Strict CSP without `unsafe-eval`; script-src, style-src, connect-src locked down |
| **Security Headers** | `X-Content-Type-Options`, `X-Frame-Options: DENY`, `X-XSS-Protection`, `Referrer-Policy`, `Permissions-Policy` |
| **CORS** | Configurable allowed origins with production wildcard warning |
| **Path Traversal Protection** | `os.path.realpath()` + prefix validation on all file-serving endpoints |
| **SQL Injection Hardening** | Explicit column allowlist for dynamic SQL queries |
| **Prompt Injection Defense** | User input wrapped in `<witness_statement>` XML boundaries before AI processing |
| **Request Size Limits** | 10MB max request body |
| **Endpoint-Specific Timeouts** | 180s for AI/streaming, 60s for standard API, 10s for health checks |
| **GZip Compression** | Responses compressed above 500 bytes |
| **Input Validation** | Pydantic models for all API inputs |
| **Request IDs** | Unique UUID per request for tracing (`X-Request-ID` header) |
| **Cache Control** | Proper cache headers (static assets cached, API responses not) |
| **Audit Logging** | Full audit trail for all case/session modifications |
| **Microphone Permissions** | Browser permissions scoped to `self` only; gesture-gated on iOS Safari |

---

## 🎬 Demo

### Screenshots

| Witness Portal | Admin Dashboard |
|:---:|:---:|
| ![Main Interface](docs/screenshots/main-interface.png) | ![Admin Portal](docs/screenshots/admin.png) |
| *Voice & chat interview with Detective Ray* | *Case management and analytics* |

> **Note**: Screenshots will be added before final submission. The UI is fully functional.

### Demo Video

🎥 [Watch the demo on YouTube →](#) *(link to be added)*

---

## 🆕 Recent Improvements

### Mobile & Layout (v2.1)
- **iPhone-optimized layout** — Compact header (44px), collapsible voice dock, hidden power-user controls on small screens
- **375px breakpoint** — Dedicated tiny-phone layout for iPhone SE and small Android devices
- **Light theme polish** — Extended coverage to chat panel, voice dock, quick phrases, mobile menu, toasts, and connection popup
- **Mic button loading state** — Visual "Starting mic..." feedback with pulsing animation during initialization

### Accessibility
- **Modal focus traps** — Tab/Shift+Tab cycles through focusable elements; focus restores on close
- **Keyboard navigation** — `:focus-visible` outlines, Enter/Space on interactive elements, `aria-hidden`/`aria-busy` attributes
- **Prefers-reduced-motion** — Respects system animation preferences

### iOS Safari Compatibility
- **Microphone permission fix** — `getUserMedia` gated behind user gesture via `_micPermissionGranted` flag; prevents misleading "access denied" toast when auto-listen fires without a tap
- **VAD (Voice Activity Detection)** — Restart gated behind the same permission flag

### Performance & Reliability
- **Chat scroll performance** — `will-change` + CSS `contain` on transcript and message elements
- **AudioContext resilience** — Double-close guard, resume retry with backoff (3 attempts), auto-recreate if closed
- **Memory leak fixes** — `durationTimer`, `_autoSaveInterval`, `_autoListenTimer` cleared on page close
- **Service worker improvements** — Cache size eviction (100 max), skip API/WS caching, only cache 2xx, "Update available" banner on new SW activation

### Security Hardening
- **CSP** — Removed `unsafe-eval` from Content-Security-Policy
- **Path traversal** — `os.path.realpath()` + prefix check on image-serving endpoint
- **SQL injection** — Explicit column allowlist dict in user profile updates
- **Prompt injection** — User input wrapped in `<witness_statement>` XML tags before AI processing
- **CORS** — Production wildcard warning logged at startup

### Backend
- **Endpoint-specific timeouts** — 180s for AI/streaming/image generation, 60s for standard API, 10s for health checks
- **Docker** — Added health check, resource limits (2 CPU / 2G RAM), log rotation to docker-compose.yml

---

## 🗺️ Future Roadmap

- 🔴 **Gemini Live API Real-time Streaming** — True real-time voice conversation with interruption support
- 📹 **Video Testimony Support** — Analyze video recordings for visual evidence
- 🔗 **Law Enforcement Database Integration** — Connect with NIBRS, RMS, and CAD systems
- 👥 **Multi-agency Collaboration** — Share cases across departments with role-based access
- 🗺️ **GIS Map Integration** — Plot incidents on interactive maps with heat mapping
- 🧬 **Evidence Chain of Custody** — Full digital chain-of-custody tracking
- 📱 **Native Mobile App** — Dedicated iOS/Android app for field interviews
- 🔊 **Speaker Diarization** — Identify and separate multiple speakers in group interviews

---

## 📜 License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.

---

## 🏆 Challenge Submission

| | |
|---|---|
| **Challenge** | [Gemini Live Agent Challenge](https://geminiliveagentchallenge.devpost.com/) |
| **Category** | Live Agents 🗣️ — Real-time interaction with audio/vision |
| **Devpost** | [WitnessReplay Submission](https://devpost.com/software/witnessreplay) |
| **Repository** | [github.com/gil906/witnessreplay](https://github.com/gil906/witnessreplay) |
| **Author** | [@gil906](https://github.com/gil906) |

### What Makes This a Live Agent?

WitnessReplay is a **live AI agent** because it:
- **Listens** — Accepts real-time voice input and transcribes it using Gemini's multimodal capabilities
- **Understands** — Maintains full conversation context to ask intelligent follow-up questions
- **Acts** — Autonomously generates scene reconstructions, classifies incidents, and groups cases
- **Adapts** — Responds in the witness's language, adjusts questioning based on testimony, and refines scenes iteratively

---

## 🙏 Acknowledgments

- Google Gemini team for the powerful AI capabilities
- FastAPI community for the excellent web framework
- The law enforcement professionals who inspired this project

---

<p align="center">
  <b>Built with ❤️ for the Gemini Live Agent Challenge</b><br>
  <i>Transforming witness testimony into actionable intelligence</i>
</p>
