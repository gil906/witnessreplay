import os
import subprocess
import logging
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from . import database as db
from .orchestrator import orchestrator

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger("wr-monitor")

app = FastAPI(title="WitnessReplay Monitor", docs_url="/docs")

TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates")
templates = Jinja2Templates(directory=TEMPLATE_DIR)

PROJECT_DIR = os.environ.get("PROJECT_DIR", "/mnt/media/witnessreplay/project")
PROMPTS_DIR = os.environ.get("PROMPTS_DIR", "/app/prompts")


@app.on_event("startup")
async def startup():
    db.init_db()
    logger.info("WitnessReplay Monitor started on port 9090")


# ── Dashboard ───────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    return templates.TemplateResponse("dashboard.html", {"request": request})


# ── Status & Stats ──────────────────────────────────────────────
@app.get("/api/status")
async def get_status():
    s = orchestrator.get_status()
    s["stats"] = db.get_stats()
    s["config"] = db.get_all_config()
    return s


# ── Run History ─────────────────────────────────────────────────
@app.get("/api/runs")
async def get_runs(limit: int = 50):
    return db.get_runs(limit)


@app.get("/api/runs/{run_id}")
async def get_run(run_id: int):
    run = db.get_run(run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    return run


# ── Loop Control ────────────────────────────────────────────────
@app.post("/api/loop/start")
async def start_loop():
    if orchestrator.start_loop():
        return {"ok": True, "msg": "Loop started"}
    return {"ok": False, "msg": "Loop already running"}


@app.post("/api/loop/stop")
async def stop_loop():
    orchestrator.stop_loop()
    return {"ok": True, "msg": "Loop stopped"}


# ── Manual Agent Run ────────────────────────────────────────────
@app.post("/api/agent/{name}/run")
async def run_agent(name: str):
    if name not in ("feature", "ux", "tester"):
        raise HTTPException(400, "Agent must be 'feature', 'ux', or 'tester'")
    if orchestrator.run_single_agent(name):
        return {"ok": True, "msg": f"{name} agent started"}
    return {"ok": False, "msg": "An agent is already running"}


# ── Prompts ─────────────────────────────────────────────────────
@app.get("/api/prompts/{name}")
async def get_prompt(name: str):
    if name not in ("feature", "ux", "tester"):
        raise HTTPException(400)
    path = os.path.join(PROMPTS_DIR, f"{name}_agent.md")
    if not os.path.exists(path):
        return {"name": name, "content": "# Prompt not found\nCreate this file."}
    with open(path) as f:
        return {"name": name, "content": f.read()}


@app.put("/api/prompts/{name}")
async def update_prompt(name: str, request: Request):
    if name not in ("feature", "ux", "tester"):
        raise HTTPException(400)
    body = await request.json()
    path = os.path.join(PROMPTS_DIR, f"{name}_agent.md")
    with open(path, 'w') as f:
        f.write(body.get("content", ""))
    return {"ok": True, "msg": "Prompt saved"}


# ── Config ──────────────────────────────────────────────────────
@app.post("/api/config")
async def update_config(request: Request):
    body = await request.json()
    for key, value in body.items():
        db.set_config(key, str(value))
    return {"ok": True}


# ── Git Log ─────────────────────────────────────────────────────
@app.get("/api/git/log")
async def get_git_log():
    try:
        result = subprocess.run(
            ["git", "--no-pager", "log", "--oneline", "--all", "-30"],
            capture_output=True, text=True, cwd=PROJECT_DIR, timeout=10
        )
        lines = [l for l in result.stdout.strip().split("\n") if l]
        return {"log": lines}
    except Exception:
        return {"log": []}


# ── Changes Summary ─────────────────────────────────────────────
@app.get("/api/changes")
async def get_changes():
    runs = db.get_runs(200)
    completed = [r for r in runs if r["status"] == "completed"]
    feature_runs = [r for r in completed if r["agent"] == "feature"]
    ux_runs = [r for r in completed if r["agent"] == "ux"]
    tester_runs = [r for r in completed if r["agent"] == "tester"]
    return {
        "total_completed": len(completed),
        "feature_runs": len(feature_runs),
        "ux_runs": len(ux_runs),
        "tester_runs": len(tester_runs),
        "recent": [
            {
                "id": r["id"], "agent": r["agent"],
                "summary": r["changes_summary"] or "",
                "commit": r["commit_sha"] or "",
                "date": r["finished_at"],
                "duration": r["duration_sec"],
            }
            for r in completed[:20]
        ],
    }


# ── Project README ──────────────────────────────────────────────
@app.get("/api/project/readme")
async def get_readme():
    path = os.path.join(PROJECT_DIR, "README.md")
    if os.path.exists(path):
        with open(path) as f:
            return {"content": f.read()[:10000]}
    return {"content": "No README found."}


# ── Health ──────────────────────────────────────────────────────
@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "wr-monitor"}


# ── Ideas ───────────────────────────────────────────────────────
@app.get("/api/ideas")
async def get_ideas(status: str = None):
    return db.get_ideas(status)


@app.post("/api/ideas")
async def create_idea(request: Request):
    body = await request.json()
    title = body.get("title", "").strip()
    desc = body.get("description", "").strip()
    if not title or not desc:
        raise HTTPException(400, "Title and description required")
    idea_id = db.create_idea(
        title=title,
        description=desc,
        priority=body.get("priority", "medium"),
        assigned_agent=body.get("assigned_agent"),
    )
    return {"ok": True, "id": idea_id}


@app.put("/api/ideas/{idea_id}")
async def update_idea(idea_id: int, request: Request):
    body = await request.json()
    allowed = {"title", "description", "priority", "status",
               "assigned_agent", "implemented_at", "implemented_by", "implementation_notes"}
    updates = {k: v for k, v in body.items() if k in allowed}
    if not updates:
        raise HTTPException(400, "No valid fields to update")
    db.update_idea(idea_id, **updates)
    return {"ok": True}


@app.delete("/api/ideas/{idea_id}")
async def delete_idea(idea_id: int):
    db.delete_idea(idea_id)
    return {"ok": True}


# ── Bugs ────────────────────────────────────────────────────────
@app.get("/api/bugs")
async def get_bugs(status: str = None):
    return db.get_bugs(status)


@app.post("/api/bugs")
async def create_bug(request: Request):
    body = await request.json()
    title = body.get("title", "").strip()
    desc = body.get("description", "").strip()
    if not title or not desc:
        raise HTTPException(400, "Title and description required")
    bug_id = db.create_bug(
        title=title,
        description=desc,
        severity=body.get("severity", "medium"),
        found_by=body.get("found_by", "tester"),
        steps_to_reproduce=body.get("steps_to_reproduce"),
        expected_behavior=body.get("expected_behavior"),
        actual_behavior=body.get("actual_behavior"),
    )
    return {"ok": True, "id": bug_id}


@app.put("/api/bugs/{bug_id}")
async def update_bug(bug_id: int, request: Request):
    body = await request.json()
    allowed = {"title", "description", "severity", "status",
               "assigned_agent", "fixed_at", "fixed_by", "fix_notes",
               "steps_to_reproduce", "expected_behavior", "actual_behavior"}
    updates = {k: v for k, v in body.items() if k in allowed}
    if not updates:
        raise HTTPException(400, "No valid fields to update")
    db.update_bug(bug_id, **updates)
    return {"ok": True}


@app.delete("/api/bugs/{bug_id}")
async def delete_bug(bug_id: int):
    db.delete_bug(bug_id)
    return {"ok": True}
