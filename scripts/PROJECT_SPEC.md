# WitnessReplay — Project Specification

## Tagline
**"Describe what you saw. I'll rebuild the scene."**

## What Is It?
WitnessReplay is a voice-driven interactive crime/accident scene reconstruction agent for the **Gemini Live Agent Challenge** hackathon. A witness speaks naturally about what they saw, and the AI generates progressive scene images, asks clarifying questions, and iteratively refines the visual reconstruction in real-time.

## Hackathon Category
**Live Agents 🗣️** — Real-time Interaction (Audio/Vision)

## Core Problem
Witnesses forget details over time. Traditional police sketches are slow and limited to faces. There is NO tool that reconstructs entire crime/accident SCENES from verbal testimony in real-time with AI-generated imagery and interactive correction loops.

## Mandatory Tech Requirements
- **Gemini model** (gemini-2.0-flash or gemini-2.5-pro)
- **Google GenAI SDK or ADK** (Agent Development Kit)
- **Google Cloud** (at minimum Cloud Run for hosting)
- **Gemini Live API** for real-time voice streaming

## Core Features (Agent 1 — Builder Must Implement)
1. **Voice Input via Gemini Live API**: WebSocket streaming, user speaks naturally, agent listens and processes in real-time. Supports interruptions.
2. **Scene Reconstruction Engine**: Takes verbal descriptions → generates scene images using Gemini's image generation (or Imagen via Vertex AI).
3. **Clarifying Question System**: Agent asks targeted questions: "Was the car red or blue?", "How far was the table from the door?"
4. **Iterative Refinement Loop**: User corrects: "No, the table was on the LEFT" → scene re-generates with correction applied.
5. **Progressive Timeline**: Builds a visual timeline of the event as described — "First this happened, then this..."
6. **Session Persistence**: Saves reconstruction sessions to Firestore/Cloud Storage so they can be revisited.
7. **Export System**: Generates a PDF/image report of the final reconstruction with witness notes.
8. **FastAPI Backend**: REST + WebSocket endpoints hosted on Google Cloud Run.
9. **Google Cloud Deployment**: Dockerfile, Cloud Run deployment config, infrastructure-as-code (Terraform or gcloud scripts).

## UX/UI Features (Agent 2 — Polisher Must Implement)
1. **Beautiful Web Frontend**: Modern, professional UI (React or vanilla JS with Tailwind CSS).
2. **Real-time Scene Canvas**: Large visual area showing the evolving scene reconstruction.
3. **Voice Waveform Visualizer**: Shows audio input waveform while user speaks.
4. **Timeline Sidebar**: Visual timeline showing each version of the scene with timestamps.
5. **Correction Highlight System**: When user corrects something, visually highlight what changed (before/after).
6. **Dark Mode / Professional Theme**: Law enforcement/forensic aesthetic — dark backgrounds, clean typography.
7. **Responsive Design**: Works on desktop and tablet.
8. **Loading States & Animations**: Smooth transitions between scene generations.
9. **Session History Panel**: List of past reconstruction sessions.
10. **Accessibility**: Keyboard navigation, screen reader support, high contrast.
11. **Onboarding Flow**: First-time user guide explaining how to use the tool.
12. **Sound Effects / Audio Feedback**: Subtle audio cues when scene updates, when agent is listening, etc.

## Tech Stack
- **Backend**: Python 3.11+, FastAPI, google-genai SDK or ADK
- **Frontend**: HTML/CSS/JS (or React), Tailwind CSS
- **AI**: Gemini 2.0 Flash / 2.5 Pro via Gemini Live API
- **Image Gen**: Gemini native image generation or Imagen 3 via Vertex AI
- **Database**: Firestore (session storage)
- **Storage**: Google Cloud Storage (generated images)
- **Deployment**: Docker → Google Cloud Run
- **IaC**: Terraform or gcloud CLI deploy scripts

## Project Structure
```
witnessreplay/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI app entry
│   │   ├── config.py            # Settings & env vars
│   │   ├── api/
│   │   │   ├── routes.py        # REST endpoints
│   │   │   └── websocket.py     # WebSocket for Live API
│   │   ├── agents/
│   │   │   ├── scene_agent.py   # Core reconstruction agent
│   │   │   └── prompts.py       # System prompts
│   │   ├── services/
│   │   │   ├── image_gen.py     # Image generation service
│   │   │   ├── storage.py       # Cloud Storage client
│   │   │   └── firestore.py     # Firestore client
│   │   └── models/
│   │       └── schemas.py       # Pydantic models
│   ├── requirements.txt
│   ├── Dockerfile
│   └── tests/
├── frontend/
│   ├── index.html
│   ├── css/
│   ├── js/
│   └── assets/
├── deploy/
│   ├── cloudbuild.yaml
│   ├── terraform/
│   └── deploy.sh
├── docs/
│   ├── architecture.md
│   └── architecture-diagram.png
├── README.md
├── .env.example
└── .gitignore
```

## GitHub Repository
- Owner: gil906
- Repo name: witnessreplay
- Must include: README with spin-up instructions, architecture diagram, .env.example

## Judging Criteria (CRITICAL — This Is How We Win)

### Innovation & Multimodal User Experience (40%) ← BIGGEST WEIGHT
Judges will ask:
- Does the project break the "text box" paradigm? → YES: Voice in, images out, voice corrections, refined images. No typing needed.
- Does the agent help "See, Hear, and Speak" in a way that feels seamless? → The agent LISTENS to the witness, SEES corrections, SPEAKS back with questions, and SHOWS generated scenes. All modalities must feel fluid, not turn-based.
- Does it have a distinct persona/voice? → Give the agent a DETECTIVE persona. Name it (e.g., "Detective Ray"). It should speak like a seasoned investigator: calm, methodical, reassuring. "I see. So the vehicle was heading east on Main Street. Let me update the scene..."
- Is the experience "Live" and context-aware? → The agent must remember EVERYTHING said in the session. It tracks all scene elements and their positions. When the witness says "actually the car was blue, not red" the agent must know exactly which car and update it.
- Does it feel disjointed and turn-based? → NO. Use streaming responses, show partial scene generation, use audio feedback while processing. Never leave the user staring at a blank screen.

**IMPLEMENTATION REQUIREMENTS for 40% criteria:**
- Real-time voice streaming (not record-then-send)
- Interruptible — user can speak while agent is responding
- Agent speaks back (text-to-speech or Gemini audio output)
- Generated images appear progressively (show loading → partial → complete)
- Scene state is maintained across the entire conversation
- Agent has a named persona with consistent personality
- Smooth transitions between states (listening → processing → showing → asking)

### Technical Implementation & Agent Architecture (30%)
Judges will ask:
- Does the code effectively utilize the Google GenAI SDK or ADK? → Use ADK properly with tool definitions, agent orchestration, and structured outputs. Don't just call the API raw.
- Is the backend robustly hosted on Google Cloud? → Cloud Run deployment with proper health checks, logging, and error handling.
- Is the agent logic sound? → Scene state machine must be bulletproof. Track elements, handle contradictions, manage conversation flow.
- Does it handle errors gracefully? → Network failures, API rate limits, invalid audio, session timeouts — all handled with user-friendly messages.
- Does the agent avoid hallucinations? → Ground the agent with structured scene data. Don't let it invent elements the witness didn't mention. Use confidence scores.
- Is there evidence of grounding? → Scene elements are tracked in a structured data model, not just free text.

**IMPLEMENTATION REQUIREMENTS for 30% criteria:**
- Clean, well-structured codebase with proper separation of concerns
- Comprehensive error handling at every layer
- Structured scene state (JSON schema for elements, positions, colors, confidence)
- Input validation and sanitization
- Proper logging and monitoring
- Health check endpoints
- Environment-based configuration
- Docker containerization
- Cloud Run deployment with IaC (Terraform or gcloud scripts)
- Rate limiting and request throttling

### Demo & Presentation (30%)
Judges will ask:
- Does the video define the problem and solution? → Start with: "Witnesses forget. Sketches are slow. WitnessReplay rebuilds entire scenes from voice in real-time."
- Is the architecture diagram clear? → Must show: Browser ↔ WebSocket ↔ FastAPI ↔ Gemini Live API ↔ Image Gen, plus Cloud Run, Firestore, GCS.
- Is there visual proof of Cloud deployment? → Show Cloud Run console, deployment logs, live URL.
- Does the video show the actual software working? → LIVE demo: person speaks, scene generates, person corrects, scene updates. No mockups.

**IMPLEMENTATION REQUIREMENTS for 30% criteria:**
- Architecture diagram (create as SVG or PNG in docs/)
- Professional README with screenshots section
- Demo-friendly UI — large scene display, visible state indicators, clear visual feedback
- The UI must LOOK impressive in a 4-minute video — dark theme, smooth animations, professional typography

## Bonus Points
- Blog post with #GeminiLiveAgentChallenge
- Automated Cloud deployment (IaC in repo)
- Google Developer Group signup

## Quality Standards
- All code must be production-quality with error handling
- No hardcoded credentials (use environment variables)
- Include comprehensive README with setup instructions
- Include .env.example with all required variables documented
- Docker must build and run successfully
- Frontend must be responsive and accessible
