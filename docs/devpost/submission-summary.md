# WitnessReplay Devpost Submission Summary

## One-line pitch

WitnessReplay is a live multimodal investigation agent that interviews witnesses in natural voice, asks better follow-up questions, and turns testimony into structured reports, scene reconstructions, and exportable case artifacts.

## What the project does

WitnessReplay is built around **Detective Ray**, a voice-first AI investigator. A witness opens the app, hears Detective Ray greet them first, and can then speak naturally instead of filling out a rigid form. The system listens, transcribes, asks clarifying questions, keeps track of missing required details such as time and location, and updates the transcript and audio reply in real time.

As the interview continues, WitnessReplay extracts structured information about the incident, groups related reports into cases, highlights contradictions, generates summaries, and can create scene reconstructions from the testimony and uploaded evidence. The result is a smoother witness experience up front and a more actionable investigative record on the back end.

## Key features and functionality

- **Live voice conversation with interruption support** so the witness can talk naturally and cut in without a brittle turn-taking flow.
- **Multimodal inputs** including voice, typed testimony, uploaded evidence photos, and hand-drawn sketches.
- **Multimodal outputs** including spoken Detective Ray replies, live transcript updates, generated scene previews, structured evidence metadata, and investigator exports.
- **Investigation-specific guardrails** that reduce duplicate questions, require missing core details such as incident time, and avoid ending the interview until the witness clearly confirms they are done.
- **Case and admin workflows** including report grouping, contradictions, summaries, timelines, review tools, and export endpoints for PDF/JSON/evidence-style output.
- **Mobile-first conversation UX** with auto-listen, wake lock support, bottom-pinned transcript behavior, and consistent media-audio playback for Detective Ray.

## Technologies used

- **Google GenAI SDK (`google-genai`)** for Gemini-powered conversation, transcription, reasoning, TTS, and image-generation flows.
- **Gemini Live / native-audio path** for real-time conversational interaction.
- **FastAPI + Python 3.11** backend with REST + WebSocket communication.
- **Vanilla JavaScript / HTML / CSS** frontend optimized for mobile voice interviewing.
- **SQLite** for default local durability.
- **Google Cloud Firestore** integration for cloud-backed session storage when configured.
- **Google Cloud Storage** integration for media/image storage when configured.
- **Cloud Build + Cloud Run + Terraform assets** for Google Cloud deployment workflows.
- **Docker Compose** for reproducible local and self-hosted environments.

## Data sources used

WitnessReplay does not depend on a prepackaged external dataset for the core interview flow. Its primary data sources are:

- **User-provided witness testimony** captured through live voice or typed text.
- **User-uploaded evidence files** such as images and sketches provided during the interview.
- **Structured metadata extracted from the conversation** during the active session.
- **Optional cloud persistence layers** such as Firestore and GCS when deployment settings enable them.

In other words, the application works on the witness's own incident narrative and supporting evidence rather than on a static training corpus bundled with the app.

## Findings and learnings

A major learning from building WitnessReplay is that a strong live-agent experience needs more than a good prompt. The best results came from combining Gemini's multimodal capabilities with deterministic product guardrails:

- We added explicit protections against duplicate questions and premature conversation completion.
- We learned that required investigative details like incident time need deterministic enforcement, not just prompt suggestions.
- We improved the mobile UX by treating the transcript like a modern messaging app: keep it pinned to the latest turn unless the user intentionally scrolls away.
- We found that mixed browser-audio routes can create inconsistent volume on phones, so Detective Ray now stays on a single media-audio path for more predictable playback.
- We tightened the voice flow so Detective Ray feels more human: shorter acknowledgments, smoother follow-ups, and less form-like repetition.

## Why this fits the Gemini Live Agent Challenge

WitnessReplay is a **Live Agent** project because it goes beyond text-in/text-out interactions:

- It **hears** spoken witness testimony.
- It **speaks** back in a live conversational style.
- It **handles interruptions and follow-up questioning** in real time.
- It **uses multimodal evidence inputs** and can generate visual scene outputs.
- It **connects live conversation to a concrete workflow** used by investigators, not just a chat experience.

## Submission asset links

- **Repository:** <https://github.com/gil906/witnessreplay>
- **Architecture diagram:** [docs/devpost/architecture-diagram.svg](./architecture-diagram.svg)
- **Google Cloud proof doc:** [docs/devpost/google-cloud-proof.md](./google-cloud-proof.md)
- **Submission checklist:** [docs/devpost/submission-checklist.md](./submission-checklist.md)
