# WitnessReplay Agent Monitor

Orchestrates three autonomous AI agents (Feature, UX, Tester) in a continuous improvement loop for the [WitnessReplay](https://github.com/gil906/witnessreplay) project.

## Features
- 🔄 Autonomous agent loop (Feature → UX → Tester → repeat)
- 💡 Ideas & 🐛 Bugs tracking with auto-completion from commit messages
- 🐳 Auto-rebuilds app container after backend changes + old image cleanup
- 📊 Real-time dashboard at port 9099
- ✏️ Editable agent prompts
- 📜 Full run history and git log

## Quick Start
```bash
docker compose up -d --build
# Dashboard at http://localhost:9099
```

## Architecture
- **Monitor** (FastAPI) — Dashboard, API, agent orchestration
- **Orchestrator** — Runs Copilot CLI agents, parses commits, manages Docker
- **Database** (SQLite) — Runs, ideas, bugs, config
