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
- [How It Works Today](#-how-it-works-today)
- [Architecture](#-architecture)
- [Key Features](#-key-features)
- [Tech Stack](#-tech-stack)
- [AI Pipeline](#-ai-pipeline)
- [Cloud & Storage Integrations](#-cloud--storage-integrations)
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

**WitnessReplay** is a voice-first witness interview system built around **Detective Ray**, an AI interviewer that can greet a witness, listen hands-free, ask smarter follow-up questions, and turn the conversation into structured case data.

It works by:

1. **Starting with a spoken Detective Ray greeting** so the witness immediately knows the app is ready.
2. **Switching into automatic listening** with browser-side voice activity detection tuned for speech onset, speech end, and background-noise rejection.
3. **Streaming Detective Ray's replies as text and audio** so the conversation feels faster and more natural.
4. **Extracting structured incident details** like who, what, when, where, vehicles, clothing, injuries, and timeline clues.
5. **Grouping related reports into cases** and generating case/report scene recreations when the testimony contains enough concrete detail.
6. **Giving investigators a cleaner admin workspace** for reviewing cases, reports, summaries, exports, and scene previews.

The result: investigators get a smoother witness interview flow up front and cleaner, more actionable case files on the back end.

---

## 🗣️ How It Works Today

1. **Witness opens the app** and Detective Ray speaks first.
2. **Auto-listen begins** so the witness can respond without pressing the mic again.
3. **Smart VAD captures the full utterance** and waits for a real pause before triggering Ray's next turn.
4. **Ray responds in chat and audio** using the live voice pipeline, with chat auto-scrolling to the latest turn.
5. **The backend extracts evidence and incident structure** into a report that can later be grouped into a case.
6. **Scene previews are generated only from real model output**. If no real image provider succeeds, WitnessReplay leaves the preview blank instead of saving a fake template image.
7. **Admins review the result** through the case/report workspace with Google or GitHub OAuth plus manual username/password sign-in.

---

## 🏗️ Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                           WitnessReplay                         │
├──────────────────┬──────────────────────────┬───────────────────┤
│ Witness Frontend │ FastAPI Backend          │ AI & Integrations │
├──────────────────┼──────────────────────────┼───────────────────┤
│                  │                          │                   │
│ Detective Ray UI │ Scene agent + prompts    │ Gemini Flash      │
│ Auto-listen/VAD  │ Session + case services  │ Gemini Live audio │
│ Chat transcript  │ Auth + admin API         │ Gemini TTS        │
│ Native audio/TTS │ Scene extraction         │ Gemini image APIs │
│ Wake lock        │ Image pipeline + storage │ Hugging Face SDXL │
│ Admin workspace  │ Cleanup / audit logic    │ Firestore (opt.)  │
│                  │ SQLite persistence       │ GCS (optional)    │
│                  │ Docker-ready app         │ GitHub Actions    │
│                  │                          │ self-hosted deploy│
└──────────────────┴──────────────────────────┴───────────────────┘
```

**Data Flow:**
```
Witness voice/text → Browser VAD + WebSocket → Detective Ray agent → Gemini models
                                                   ↓
                                   Structured report + evidence extraction
                                                   ↓
                                 Case matching / summaries / scene prompts
                                                   ↓
                     Scene image pipeline (Gemini/Imagen → HF fallback when needed)
                                                   ↓
                                 SQLite/Firestore storage → Admin REST workspace
```

---

## ✨ Key Features

| Feature | Description |
|---------|-------------|
| 🎙️ **Hands-free witness interview** | Detective Ray greets first, then automatically listens for the witness response. |
| 🧠 **Smart voice turn-taking** | Browser VAD is tuned to catch speech onset, detect end-of-turn pauses, and ignore common background noise. |
| 🔊 **Natural live voice responses** | Faster text-to-audio flow with native streaming audio when available and Gemini TTS fallback when needed. |
| 💬 **Chat + audio in sync** | Transcript updates immediately, auto-scroll stays pinned to the latest turn, and audio follows without manual refresh. |
| 🎨 **Real scene recreations** | Case/report previews use real model output only; fake template placeholders are intentionally rejected. |
| 📁 **Automatic case grouping** | Reports are matched into cases using incident content, timing, location, and shared details. |
| 👮 **Cleaner admin workspace** | Focused case/report review UI with search, filters, workload tools, exports, and less dashboard noise. |
| 🔐 **Flexible admin auth** | Google OAuth, GitHub OAuth, plus manual username/password fallback for admin access. |
| 📱 **Mobile-first interviewing** | Responsive witness flow with wake lock support so the device stays awake during active voice conversation. |
| 💾 **Practical persistence** | SQLite is the default durable store, with optional Firestore/GCS support when cloud services are configured. |
| 📄 **Investigation outputs** | PDF/JSON/CSV exports, AI summaries, timelines, contradictions, and structured evidence metadata. |
| 🔀 **Provider fallback chain** | Multi-key Gemini failover plus Hugging Face image fallback when Google image capacity is unavailable. |

---

## 🛠️ Tech Stack

| Component | Technology |
|-----------|------------|
| **AI Engine** | Google Gemini models for chat, live audio, extraction, and TTS; Hugging Face SDXL fallback for scene images |
| **Backend** | Python 3.11 + FastAPI |
| **Database** | SQLite by default, with optional Firestore integration |
| **Image Storage** | Local `/data/images` storage, with optional Google Cloud Storage support |
| **Real-time** | WebSocket interview channel with heartbeat/reconnect handling |
| **Frontend** | Vanilla JS / HTML / CSS |
| **Deployment** | Docker Compose on self-hosted Linux / Raspberry Pi |
| **CI/CD** | GitHub Actions (`.github/workflows/deploy-pi.yml`) |
| **IaC** | Terraform assets remain available for cloud-oriented setups |
| **Security** | bcrypt, OAuth, CORS, CSP (no `unsafe-eval`), rate limiting, path traversal protection, prompt-injection defense, request timeouts |

---

## 🤖 AI Pipeline

### Live Models and Fallbacks

| Task | Current pipeline | Purpose |
|------|------------------|---------|
| **Live witness conversation** | Gemini live/native-audio model (`LIVE_MODEL`) | Low-latency Detective Ray audio turns and conversational flow |
| **Fast chat + extraction** | Gemini Flash / Flash Lite family | Interview reasoning, follow-up questions, structured report extraction |
| **TTS fallback** | Gemini TTS model (`TTS_MODEL`) | Spoken replies when native streaming audio is unavailable |
| **Scene prompt extraction** | Gemini multimodal models | Convert witness testimony into scene-recreation prompts |
| **Scene image rendering** | Google image providers first, then Hugging Face SDXL fallback | Keep real case/report previews available without storing fake template images |

### What the AI layer does

- **Maintains multi-turn Detective Ray context** across the witness session.
- **Transcribes and interprets voice input** using multimodal Gemini capabilities.
- **Extracts structured scene data** such as people, vehicles, timing, locations, and evidence.
- **Suggests and asks follow-up questions** when key investigative details are still missing.
- **Matches reports into cases** using content, time, and location similarity.
- **Generates summaries and contradictions** for investigators reviewing multiple accounts.
- **Falls back across providers** when keys hit quota or a scene image provider is unavailable.

---

## ☁️ Cloud & Storage Integrations

| Service | Usage |
|---------|-------|
| **SQLite** | Default durable store for sessions, cases, statements, images, and background tasks |
| **Firestore** | Optional cloud-backed document storage for synced session/case data |
| **Local image storage** | Primary storage for generated case/report previews in self-hosted deployments |
| **Google Cloud Storage** | Optional remote storage for generated images |
| **GitHub Actions** | Push-to-deploy workflow for the self-hosted Raspberry Pi environment |

---

## 🚀 Quick Start

### Prerequisites

- Python 3.11+
- [Google Gemini API key](https://aistudio.google.com/apikey)
- Docker (recommended) or Python venv
- Hugging Face token *(optional but recommended for image fallback)*
- Google Cloud account *(optional — only needed if you want Firestore/GCS integrations)*

### Option 1: Docker (Recommended)

```bash
# Clone the repository
git clone https://github.com/gil906/witnessreplay.git
cd witnessreplay

# Configure environment
cp .env.example .env
# Edit `.env` — at minimum set a Gemini key and `ADMIN_PASSWORD`
# Optional but recommended: set `HUGGINGFACE_API_TOKEN`

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
cd witnessreplay

# Set up Python environment
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Configure environment
cd ..
cp .env.example .env
# Edit `.env` with your credentials

# Run the server
cd backend
uvicorn app.main:app --reload --host 0.0.0.0 --port 8080

# Open http://localhost:8080
```

### Option 3: Self-hosted Production Deploy

```bash
# Push to master to trigger the Raspberry Pi deploy workflow
git push origin master

# The GitHub Actions workflow:
# - syncs the repo to /mnt/media/witnessreplay
# - preserves the existing private .env
# - rebuilds the Docker image
# - restarts the witnessreplay container
# - waits for /api/health to stay healthy
```

> The repository still contains cloud-oriented assets under `deploy/`, but the current live app is deployed through the self-hosted GitHub Actions workflow.

---

## 📝 Environment Variables

| Variable | Description | Required | Default |
|----------|-------------|----------|---------|
| `GOOGLE_API_KEY` | Primary/default Gemini API key for backward compatibility | **Yes*** | — |
| `GOOGLE_API_KEYS` | Legacy comma-separated Gemini keys for rotation | No | — |
| `GOOGLE_API_PRIMARY_KEY` | Primary Gemini API key (highest priority) | **Yes*** | — |
| `GOOGLE_API_SECONDARY_KEY` | Secondary Gemini API key for automatic failover | No | — |
| `GOOGLE_API_TERTIARY_KEY` | Tertiary Gemini API key for final failover | No | — |
| `GOOGLE_API_PRIMARY_EMAIL` | Label email for primary account status views | No | — |
| `GOOGLE_API_SECONDARY_EMAIL` | Label email for secondary account status views | No | — |
| `GOOGLE_API_TERTIARY_EMAIL` | Label email for tertiary account status views | No | — |
| `GOOGLE_API_PRIMARY_PROJECT_ID` | Google project ID for primary Gemini account | No | — |
| `GOOGLE_API_SECONDARY_PROJECT_ID` | Google project ID for secondary Gemini account | No | — |
| `GOOGLE_API_TERTIARY_PROJECT_ID` | Google project ID for tertiary Gemini account | No | — |
| `GOOGLE_API_ACCOUNTS_JSON` | Advanced JSON account config override | No | — |
| `HUGGINGFACE_API_TOKEN` | Enables the SDXL scene-image fallback when Google image generation is unavailable | No | — |
| `GCP_PROJECT_ID` | Google Cloud project ID | For optional cloud features | — |
| `GCS_BUCKET` | Cloud Storage bucket for images | For optional cloud features | `witnessreplay-images` |
| `FIRESTORE_COLLECTION` | Firestore collection name | No | `reconstruction_sessions` |
| `ADMIN_PASSWORD` | Manual admin password | **Yes** | — |
| `ADMIN_PUBLIC_BASE_URL` | Public base URL used for OAuth callback generation | Recommended in production | — |
| `ADMIN_GOOGLE_CLIENT_ID` | Google OAuth client ID for admin login | No | — |
| `ADMIN_GOOGLE_CLIENT_SECRET` | Google OAuth client secret for admin login | No | — |
| `ADMIN_GITHUB_CLIENT_ID` | GitHub OAuth client ID for admin login | No | — |
| `ADMIN_GITHUB_CLIENT_SECRET` | GitHub OAuth client secret for admin login | No | — |
| `ENVIRONMENT` | `development` or `production` | No | `production` |
| `DEBUG` | Enable debug mode | No | `false` |
| `PORT` | Server port | No | `8080` |
| `HOST` | Server host | No | `0.0.0.0` |
| `GEMINI_MODEL` | Default general-purpose Gemini model | No | `gemini-3-flash` |
| `GEMINI_VISION_MODEL` | Vision/audio Gemini model | No | `gemini-3-flash` |
| `GEMINI_LITE_MODEL` | Fast low-cost interview model | No | `gemini-2.5-flash-lite` |
| `TTS_MODEL` | Gemini TTS fallback voice model | No | `gemini-2.5-flash-preview-tts` |
| `LIVE_MODEL` | Gemini live/native-audio model | No | `gemini-2.5-flash-exp-native-audio-thinking` |
| `ALLOWED_ORIGINS` | CORS allowed origins | No | `http://localhost:8088,http://localhost:3000` |
| `ENFORCE_RATE_LIMITS` | Enable rate limiting | No | `true` |
| `MAX_REQUESTS_PER_MINUTE` | Rate limit threshold | No | `60` |
| `SESSION_TIMEOUT_MINUTES` | Session expiry | No | `60` |
| `MAX_SESSION_SIZE_MB` | Max session data size | No | `100` |
| `DATABASE_PATH` | SQLite database path | No | `/app/data/witnessreplay.db` |

\* Set either `GOOGLE_API_KEY` or `GOOGLE_API_PRIMARY_KEY`. If you provide Primary/Secondary/Tertiary keys, the app now prefers Primary first and automatically fails over when a model/account hits quota or a `429`.

---

## 🔌 API Endpoints

### Authentication
| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/auth/login` | Manual admin login |
| `POST` | `/api/auth/register` | Create an admin account |
| `POST` | `/api/auth/forgot-password` | Start password reset flow |
| `GET` | `/api/auth/oauth/providers` | Check which OAuth providers are configured |
| `GET` | `/api/auth/oauth/{provider}/start` | Begin Google or GitHub OAuth |
| `GET` | `/api/auth/oauth/{provider}/callback` | OAuth callback handler |
| `POST` | `/api/auth/oauth` | Exchange verified OAuth profile for admin session |
| `POST` | `/api/auth/logout` | Admin logout |
| `GET` | `/api/auth/verify` | Verify authentication |
| `GET` | `/api/auth/me` | Return the authenticated admin profile |

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
witnessreplay/
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
│   │   │   ├── image_gen.py         # Scene image generation helpers
│   │   │   ├── imagen_service.py    # Google scene-image orchestration
│   │   │   ├── huggingface_image_service.py  # HF SDXL fallback for scene images
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
│   ├── deploy.sh                    # Legacy/optional cloud deployment helper
│   ├── cloudbuild.yaml              # Legacy/optional cloud build pipeline
│   └── terraform/                   # Infrastructure as Code assets
├── .github/
│   └── workflows/
│       └── deploy-pi.yml            # Self-hosted Raspberry Pi deploy workflow
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
| *Voice & chat interview with Detective Ray* | *Case and report review workspace* |

> **Note**: Screenshots will be added before final submission. The UI is fully functional.

### Demo Video

🎥 [Watch the demo on YouTube →](#) *(link to be added)*

---

## 🆕 Recent Improvements

### Voice conversation flow
- **Detective Ray greets first** and the witness flow immediately rolls into hands-free listening.
- **Speech onset capture is smoother** so the beginning of a witness response is less likely to be clipped.
- **Native audio streaming is preferred** for faster, more natural Detective Ray replies, with Gemini TTS fallback still available.
- **Chat auto-scroll is pinned to the latest turn** when new messages arrive and when playback starts.
- **Wake lock support keeps the screen awake** during active voice conversation sessions.

### Scene previews and case quality
- **Fake template previews are blocked** — case/report images now use real model output only.
- **Hugging Face SDXL fallback was added** so scene generation can still succeed when Google image quota is exhausted.
- **Prompt cleanup improved** so generated scene descriptions are based on cleaner witness detail instead of transcript filler.
- **Empty/noise sessions are removed from admin review** instead of cluttering the report list with `0 statements` entries.

### Admin experience
- **Google and GitHub admin OAuth** now sit alongside manual username/password auth.
- **The admin login flow is simpler** with social sign-in presented first.
- **Top-level admin dashboard noise was removed** so the case/report workspace is easier to scan.

### Reliability and security
- **Request validation and cleanup paths were hardened** around session closing, preview selection, and report listing.
- **The Docker deployment flow includes health-gated restarts** through the Raspberry Pi GitHub Actions workflow.
- **Core browser hardening remains in place**: CSP, path traversal protection, prompt-injection boundaries, and rate limiting.

---

## 🗺️ Future Roadmap

- 📹 **Video Testimony Support** — Analyze video recordings for visual evidence
- 🧑‍🤝‍🧑 **Speaker Diarization** — Separate multiple nearby speakers in challenging environments
- 🔗 **Law Enforcement Database Integration** — Connect with NIBRS, RMS, and CAD systems
- 👥 **Multi-agency Collaboration** — Share cases across departments with role-based access
- 🗺️ **GIS Map Integration** — Plot incidents on interactive maps with heat mapping
- 🧬 **Evidence Chain of Custody** — Full digital chain-of-custody tracking
- 📱 **Native Mobile App** — Dedicated iOS/Android app for field interviews
- 🔇 **Ambient noise classification** — Better separate true witness speech from road noise, wind, and crowd chatter

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

### Devpost-ready submission files

| Submission need | File | How to use it |
|---|---|---|
| **Text description** | [`docs/devpost/submission-summary.txt`](docs/devpost/submission-summary.txt) | Paste into the Devpost text-description field |
| **Formatted project summary** | [`docs/devpost/submission-summary.md`](docs/devpost/submission-summary.md) | Repo-friendly version of the same submission summary |
| **Google Cloud proof** | [`docs/devpost/google-cloud-proof.md`](docs/devpost/google-cloud-proof.md) | Use this file's GitHub URL in the Devpost proof field |
| **Architecture diagram** | [`docs/devpost/architecture-diagram.svg`](docs/devpost/architecture-diagram.svg) | Upload to the file upload or image carousel |
| **Submission checklist** | [`docs/devpost/submission-checklist.md`](docs/devpost/submission-checklist.md) | Final pass before you click submit |
| **One-command bundle export** | [`tools/export_devpost_bundle.py`](tools/export_devpost_bundle.py) | Builds a zip bundle with the submission assets |

### Export a single Devpost bundle

```bash
python3 tools/export_devpost_bundle.py
```

Generated output:

- `dist/devpost/witnessreplay-devpost-submission/`
- `dist/devpost/witnessreplay-devpost-submission.zip`

The bundle includes the README, submission summary, architecture diagram, Google Cloud proof doc, and the core reference files that back up the challenge submission.

### Google Cloud references for judges

If you want judges to verify the Google Cloud path directly in the repository, start with:

- [`docs/devpost/google-cloud-proof.md`](docs/devpost/google-cloud-proof.md)
- [`deploy/cloudbuild.yaml`](deploy/cloudbuild.yaml)
- [`deploy/terraform/main.tf`](deploy/terraform/main.tf)
- [`backend/app/services/firestore.py`](backend/app/services/firestore.py)
- [`backend/app/services/storage.py`](backend/app/services/storage.py)

The repo also contains a self-hosted Docker/GitHub Actions deployment path for day-to-day iteration, but the files above are the Google Cloud-specific references to highlight for the challenge.

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
