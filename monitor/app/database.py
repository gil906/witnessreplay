import sqlite3
import os
import threading
from datetime import datetime
from typing import Optional, List, Dict

DB_PATH = os.environ.get("DB_PATH", "/app/data/monitor.db")
_lock = threading.Lock()


def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agent TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            started_at TEXT,
            finished_at TEXT,
            duration_sec INTEGER,
            commit_sha TEXT,
            changes_summary TEXT,
            error_message TEXT,
            log_tail TEXT,
            cycle INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS config (
            key TEXT PRIMARY KEY,
            value TEXT
        );
        CREATE TABLE IF NOT EXISTS ideas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            priority TEXT NOT NULL DEFAULT 'medium',
            status TEXT NOT NULL DEFAULT 'pending',
            assigned_agent TEXT,
            created_at TEXT,
            implemented_at TEXT,
            implemented_by TEXT,
            implementation_notes TEXT
        );
        CREATE TABLE IF NOT EXISTS bugs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            severity TEXT NOT NULL DEFAULT 'medium',
            status TEXT NOT NULL DEFAULT 'open',
            found_by TEXT DEFAULT 'tester',
            assigned_agent TEXT,
            created_at TEXT,
            fixed_at TEXT,
            fixed_by TEXT,
            fix_notes TEXT,
            steps_to_reproduce TEXT,
            expected_behavior TEXT,
            actual_behavior TEXT
        );
    """)
    defaults = {
        "loop_active": "false",
        "delay_between_agents": "30",
        "delay_between_cycles": "120",
        "max_retries": "2",
    }
    for k, v in defaults.items():
        conn.execute("INSERT OR IGNORE INTO config (key, value) VALUES (?, ?)", (k, v))
    conn.commit()
    conn.close()


def get_config(key: str) -> Optional[str]:
    with _lock:
        conn = get_db()
        row = conn.execute("SELECT value FROM config WHERE key = ?", (key,)).fetchone()
        conn.close()
        return row["value"] if row else None


def set_config(key: str, value: str):
    with _lock:
        conn = get_db()
        conn.execute("INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)", (key, value))
        conn.commit()
        conn.close()


def create_run(agent: str, cycle: int = 0) -> int:
    with _lock:
        conn = get_db()
        cur = conn.execute(
            "INSERT INTO runs (agent, status, started_at, cycle) VALUES (?, 'running', ?, ?)",
            (agent, datetime.utcnow().isoformat(), cycle)
        )
        run_id = cur.lastrowid
        conn.commit()
        conn.close()
        return run_id


def update_run(run_id: int, **kwargs):
    with _lock:
        conn = get_db()
        sets = ", ".join(f"{k} = ?" for k in kwargs)
        vals = list(kwargs.values()) + [run_id]
        conn.execute(f"UPDATE runs SET {sets} WHERE id = ?", vals)
        conn.commit()
        conn.close()


def get_runs(limit: int = 50) -> List[Dict]:
    with _lock:
        conn = get_db()
        rows = conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        conn.close()
        return [dict(r) for r in rows]


def get_run(run_id: int) -> Optional[Dict]:
    with _lock:
        conn = get_db()
        row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        conn.close()
        return dict(row) if row else None


def get_all_config() -> Dict[str, str]:
    with _lock:
        conn = get_db()
        rows = conn.execute("SELECT key, value FROM config").fetchall()
        conn.close()
        return {r["key"]: r["value"] for r in rows}


def get_stats() -> Dict:
    with _lock:
        conn = get_db()
        total = conn.execute("SELECT COUNT(*) as c FROM runs").fetchone()["c"]
        completed = conn.execute("SELECT COUNT(*) as c FROM runs WHERE status='completed'").fetchone()["c"]
        failed = conn.execute("SELECT COUNT(*) as c FROM runs WHERE status='failed'").fetchone()["c"]
        last_run = conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()
        conn.close()
        return {
            "total_runs": total,
            "completed": completed,
            "failed": failed,
            "success_rate": round(completed / total * 100, 1) if total > 0 else 0,
            "last_run": dict(last_run) if last_run else None,
        }


# ── Ideas ───────────────────────────────────────────────────────
def create_idea(title: str, description: str, priority: str = "medium",
                assigned_agent: str = None) -> int:
    with _lock:
        conn = get_db()
        cur = conn.execute(
            "INSERT INTO ideas (title, description, priority, status, assigned_agent, created_at) "
            "VALUES (?, ?, ?, 'pending', ?, ?)",
            (title, description, priority, assigned_agent, datetime.utcnow().isoformat())
        )
        idea_id = cur.lastrowid
        conn.commit()
        conn.close()
        return idea_id


def get_ideas(status: str = None) -> List[Dict]:
    with _lock:
        conn = get_db()
        if status:
            rows = conn.execute(
                "SELECT * FROM ideas WHERE status = ? ORDER BY "
                "CASE priority WHEN 'critical' THEN 0 WHEN 'high' THEN 1 "
                "WHEN 'medium' THEN 2 WHEN 'low' THEN 3 END, id DESC", (status,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM ideas ORDER BY "
                "CASE status WHEN 'pending' THEN 0 WHEN 'in_progress' THEN 0 "
                "WHEN 'done' THEN 1 END, "
                "CASE priority WHEN 'critical' THEN 0 WHEN 'high' THEN 1 "
                "WHEN 'medium' THEN 2 WHEN 'low' THEN 3 END, id DESC"
            ).fetchall()
        conn.close()
        return [dict(r) for r in rows]


def update_idea(idea_id: int, **kwargs):
    with _lock:
        conn = get_db()
        sets = ", ".join(f"{k} = ?" for k in kwargs)
        vals = list(kwargs.values()) + [idea_id]
        conn.execute(f"UPDATE ideas SET {sets} WHERE id = ?", vals)
        conn.commit()
        conn.close()


def delete_idea(idea_id: int):
    with _lock:
        conn = get_db()
        conn.execute("DELETE FROM ideas WHERE id = ?", (idea_id,))
        conn.commit()
        conn.close()


def get_pending_ideas_text() -> str:
    """Get pending ideas formatted for agent prompts."""
    ideas = get_ideas(status="pending")
    if not ideas:
        return ""
    critical = [i for i in ideas if i['priority'] in ('critical', 'high')]
    lines = [
        "## 🚨 USER IDEAS — IMPLEMENT THESE FIRST BEFORE ANYTHING ELSE:\n",
        "STOP. Before you do ANY other work, implement ALL critical/high ideas below.",
        "Only after ALL critical/high ideas are done, move to medium/low ideas.",
        "Only after ALL ideas are done, work on your own improvements.\n",
    ]
    for i, idea in enumerate(ideas, 1):
        agent_hint = f" [assigned to: {idea['assigned_agent']}]" if idea['assigned_agent'] else ""
        lines.append(f"### Idea #{idea['id']}: {idea['title']} [{idea['priority'].upper()}]{agent_hint}")
        lines.append(idea['description'])
        lines.append("")
    lines.append("**IMPORTANT**: After implementing an idea, include 'Implemented Idea #N' in your git commit message (e.g., 'feat(feature): add model selector - Implemented Idea #1').")
    return "\n".join(lines)


# ── Bugs ────────────────────────────────────────────────────────
def create_bug(title: str, description: str, severity: str = "medium",
               found_by: str = "tester", steps_to_reproduce: str = None,
               expected_behavior: str = None, actual_behavior: str = None) -> int:
    with _lock:
        conn = get_db()
        cur = conn.execute(
            "INSERT INTO bugs (title, description, severity, status, found_by, "
            "steps_to_reproduce, expected_behavior, actual_behavior, created_at) "
            "VALUES (?, ?, ?, 'open', ?, ?, ?, ?, ?)",
            (title, description, severity, found_by, steps_to_reproduce,
             expected_behavior, actual_behavior, datetime.utcnow().isoformat())
        )
        bug_id = cur.lastrowid
        conn.commit()
        conn.close()
        return bug_id


def get_bugs(status: str = None) -> List[Dict]:
    with _lock:
        conn = get_db()
        if status:
            rows = conn.execute(
                "SELECT * FROM bugs WHERE status = ? ORDER BY "
                "CASE severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 "
                "WHEN 'medium' THEN 2 WHEN 'low' THEN 3 END, id DESC", (status,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM bugs ORDER BY "
                "CASE status WHEN 'open' THEN 0 WHEN 'in_progress' THEN 0 "
                "WHEN 'fixed' THEN 1 WHEN 'wontfix' THEN 2 END, "
                "CASE severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 "
                "WHEN 'medium' THEN 2 WHEN 'low' THEN 3 END, id DESC"
            ).fetchall()
        conn.close()
        return [dict(r) for r in rows]


def update_bug(bug_id: int, **kwargs):
    with _lock:
        conn = get_db()
        sets = ", ".join(f"{k} = ?" for k in kwargs)
        vals = list(kwargs.values()) + [bug_id]
        conn.execute(f"UPDATE bugs SET {sets} WHERE id = ?", vals)
        conn.commit()
        conn.close()


def delete_bug(bug_id: int):
    with _lock:
        conn = get_db()
        conn.execute("DELETE FROM bugs WHERE id = ?", (bug_id,))
        conn.commit()
        conn.close()


def get_open_bugs_text() -> str:
    """Get open bugs formatted for agent prompts (excludes info-level, capped at 15)."""
    all_bugs = get_bugs(status="open")
    # Filter out info-severity (positive findings, not real bugs)
    bugs = [b for b in all_bugs if b['severity'] != 'info']
    if not bugs:
        return ""
    
    # Already sorted by severity from get_bugs(), take top 15
    bugs = bugs[:15]
    
    lines = [
        "## 🔴 OPEN BUGS — FIX THESE FIRST BEFORE ANYTHING ELSE:\n",
        "STOP. Before you do ANY other work (features, polish, improvements),",
        "fix ALL critical and high severity bugs below.",
        "Only after ALL critical/high bugs are fixed, fix medium/low bugs.",
        "Only after ALL bugs are fixed, work on new features/ideas.",
        "**IMPORTANT**: Include 'Fixed Bug #N' in your commit message for each bug you fix.\n",
    ]
    for bug in bugs:
        lines.append(f"### Bug #{bug['id']}: {bug['title']} [{bug['severity'].upper()}]")
        lines.append(bug['description'][:500])  # Cap description length
        if bug.get('steps_to_reproduce'):
            lines.append(f"Steps to reproduce: {bug['steps_to_reproduce'][:300]}")
        if bug.get('expected_behavior'):
            lines.append(f"Expected: {bug['expected_behavior'][:200]}")
        if bug.get('actual_behavior'):
            lines.append(f"Actual: {bug['actual_behavior'][:200]}")
        lines.append("")
    
    remaining = len([b for b in all_bugs if b['severity'] != 'info']) - len(bugs)
    if remaining > 0:
        lines.append(f"*({remaining} more lower-priority bugs not shown)*")
    
    lines.append("After fixing a bug, include 'Fixed Bug #N' in your commit message.")
    return "\n".join(lines)


# ── Change History for Prompt Injection ─────────────────────────
def get_recent_changes_for_prompt(limit: int = 10) -> str:
    """Get recent completed runs as context so agents know what was already done."""
    with _lock:
        conn = get_db()
        rows = conn.execute(
            "SELECT agent, changes_summary, commit_sha, finished_at "
            "FROM runs WHERE status='completed' ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        conn.close()
    if not rows:
        return ""
    lines = ["## RECENT CHANGES (do NOT repeat these unless they were poorly done):\n"]
    for r in rows:
        lines.append(f"- **{r['agent']}** ({r['finished_at'] or '?'}): {r['commit_sha'] or 'no commit'}")
        summary = r['changes_summary'] or 'No details'
        for line in summary.split('\n')[:5]:
            lines.append(f"  {line}")
        lines.append("")
    return "\n".join(lines)
