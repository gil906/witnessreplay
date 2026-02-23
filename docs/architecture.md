# WitnessReplay - System Architecture

## Overview

WitnessReplay is a multimodal AI agent that transforms verbal witness testimony into visual scene reconstructions through an iterative, real-time conversation.

## Architecture Layers

### 1. Frontend Layer (User Interface)

**Technology**: Vanilla JavaScript, Web Audio API, WebSocket

**Components**:
- **Audio Capture**: MediaRecorder API for microphone input
- **WebSocket Client**: Real-time bidirectional communication
- **Scene Display**: Dynamic image rendering area
- **Timeline**: Version history of scene reconstructions
- **Chat Interface**: Conversation transcript and text fallback

**Flow**:
```
User speaks → Audio captured → Sent via WebSocket → Backend processes
Backend responds → Scene image + text → Displayed to user
```

### 2. API Layer (FastAPI Backend)

**Technology**: FastAPI, Python 3.11, Uvicorn

**Endpoints**:
- REST API for session CRUD operations
- WebSocket endpoint for real-time communication
- Health check and monitoring endpoints

**Middleware**:
- CORS handling for cross-origin requests
- Request ID tracking for debugging
- Error handling and logging

**Flow**:
```
HTTP Request → CORS Middleware → Route Handler → Service Layer → Response
WebSocket → Connection Handler → Message Router → Agent → Response Stream
```

### 3. Agent Layer (Core Intelligence)

**Technology**: Google Gemini 2.0 Flash, GenAI SDK

**Components**:

#### Scene Reconstruction Agent
- **Role**: Conduct witness interview, extract scene information
- **Capabilities**:
  - Natural language understanding
  - Clarifying question generation
  - Scene element tracking
  - Correction handling
  - Conversation state management

**Prompt Engineering**:
- System prompt defines agent behavior and expertise
- Structured output extraction for scene elements
- Few-shot examples for question formulation
- Context management for multi-turn conversations

**Flow**:
```
User statement → Agent processes → Extracts scene info
                ↓
        Updates scene model
                ↓
        Generates response (question or confirmation)
                ↓
        Triggers image generation (when ready)
```

### 4. Service Layer

#### Image Generation Service
**Technology**: Gemini Vision Model (placeholder for Imagen 3)

**Current Implementation**: 
- Placeholder image generation with scene text overlay
- Ready to integrate with Vertex AI Imagen 3

**Production Integration**:
```python
# Future: Vertex AI Imagen 3
from google.cloud import aiplatform
prediction = aiplatform.ImageGenerationModel.predict(prompt)
```

**Flow**:
```
Scene description + elements → Detailed prompt construction
                              ↓
                    Image generation model
                              ↓
                    PNG image bytes returned
```

#### Storage Service
**Technology**: Google Cloud Storage

**Operations**:
- Upload generated scene images
- Upload audio recordings (optional)
- Public URL generation
- Lifecycle management (90-day retention)

**Security**:
- Bucket-level public read access for images
- Service account authentication
- CORS configuration for browser access

#### Firestore Service
**Technology**: Google Cloud Firestore

**Data Model**:
```
reconstruction_sessions/
  {session_id}/
    - id: string
    - title: string
    - created_at: timestamp
    - updated_at: timestamp
    - status: "active" | "completed" | "archived"
    - witness_statements: array
      - id, text, timestamp, is_correction
    - scene_versions: array
      - version, description, image_url, elements, timestamp
    - timeline: array
      - sequence, description, timestamp
    - current_scene_elements: array
      - type, description, position, color, confidence
```

**Operations**:
- Session CRUD
- Real-time updates
- Query optimization
- Transaction support for consistency

### 5. Data Flow

#### Voice Input Flow
```
1. User clicks "Start Speaking"
2. Browser requests microphone access
3. MediaRecorder captures audio chunks
4. Audio buffered locally
5. User clicks "Stop" or pauses
6. Audio blob converted to base64
7. Sent via WebSocket to backend
8. [Future] Streamed to Gemini Live API for transcription
9. Transcribed text processed by Scene Agent
10. Agent response sent back to client
```

#### Scene Generation Flow
```
1. Agent determines scene is ready for visualization
2. Agent.get_scene_summary() returns current state
3. Image Generation Service receives:
   - Scene description (natural language)
   - Scene elements (structured data)
   - Is correction flag
4. Service constructs detailed prompt
5. Image generated (currently placeholder)
6. Image uploaded to GCS
7. Public URL returned
8. Scene version saved to Firestore
9. WebSocket message sent to client with image URL
10. Client displays image and updates timeline
```

#### Correction Flow
```
1. User: "No, the car was RED not blue"
2. WebSocket sends: {type: "correction", data: {text: "..."}}
3. Agent processes with correction flag
4. Agent updates internal scene model
5. Agent confirms: "Got it, updating to red car"
6. New scene image generated
7. Version incremented
8. New version added to timeline
9. UI highlights what changed
```

### 6. Deployment Architecture

#### Development
```
Local Machine
├── Backend: http://localhost:8080
├── Frontend: Served by FastAPI static files
└── External Services:
    ├── Gemini API (cloud)
    ├── Firestore (cloud or emulator)
    └── GCS (cloud or mock)
```

#### Production (Google Cloud Run)
```
Internet → Cloud Load Balancer
              ↓
         Cloud Run Service
         (Container: witnessreplay)
              ↓
    ┌─────────┴─────────────┐
    ▼                       ▼
Firestore              Cloud Storage
(Sessions)             (Images)
    ↓                       ↓
Service Account with IAM roles
```

**Security**:
- API key stored in Secret Manager
- Service account with least privilege
- HTTPS enforced
- CORS configured for allowed origins

**Scalability**:
- Auto-scaling: 0-10 instances
- 2 vCPU, 2GB RAM per instance
- WebSocket connection pooling
- Firestore handles concurrent reads/writes
- GCS serves images via CDN

### 7. Error Handling Strategy

**Levels**:
1. **Client-side**: Retry logic, graceful degradation, user feedback
2. **API Layer**: Exception handlers, status codes, error messages
3. **Service Layer**: Fallback mechanisms, logging, alerting
4. **External Services**: Timeout handling, circuit breakers

**Example**:
```
Image generation fails
→ Log error with context
→ Return placeholder or previous version
→ Notify user: "Having trouble generating image, trying again..."
→ Retry with exponential backoff
→ If still fails: Continue conversation, mark image as "pending"
```

## Technology Choices

### Why Gemini 2.0 Flash?
- Native multimodal capabilities (voice + vision + text)
- Live API for real-time streaming
- Fast response times for conversational UX
- Built-in context management

### Why FastAPI?
- Native async/await for WebSocket handling
- Automatic API documentation
- Pydantic for data validation
- High performance for real-time apps

### Why Cloud Run?
- Serverless (pay per use)
- Auto-scaling to zero
- WebSocket support
- Integrated with GCP services
- Simple deployment from Docker

### Why Firestore?
- Real-time synchronization
- Flexible document model
- Offline support (future mobile app)
- Automatic scaling
- Strong consistency

## Future Enhancements

1. **Imagen 3 Integration**: Replace placeholder with real image generation
2. **Gemini Live API**: Stream audio directly instead of chunking
3. **Multi-witness Support**: Combine testimony from multiple witnesses
4. **3D Scene Reconstruction**: Generate 3D models instead of 2D images
5. **Video Generation**: Animate the sequence of events
6. **Mobile App**: Native iOS/Android with offline support
7. **Collaboration**: Real-time multi-user sessions
8. **Export Formats**: 3D models, AR experiences, courtroom presentations

## Performance Metrics

**Target SLAs**:
- WebSocket connection: < 1s
- Agent response: < 3s (text)
- Image generation: < 10s
- Session load: < 500ms
- PDF export: < 5s

**Monitoring**:
- Cloud Run metrics (latency, errors, instances)
- Custom metrics (image gen time, agent accuracy)
- Error tracking (Sentry or Cloud Error Reporting)
- User analytics (session duration, correction rate)
