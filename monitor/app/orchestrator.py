import subprocess
import threading
import os
import logging
import time
import re
import asyncio
from datetime import datetime

from . import database as db
from .notifier import send_alert

logger = logging.getLogger(__name__)

PROJECT_DIR = os.environ.get("PROJECT_DIR", "/mnt/media/witnessreplay/project")
SCRIPTS_DIR = os.environ.get("SCRIPTS_DIR", "/mnt/media/witnessreplay/scripts")
PROMPTS_DIR = os.environ.get("PROMPTS_DIR", "/app/prompts")
GITHUB_USER = os.environ.get("GITHUB_USER", "gil906")
GITHUB_REPO = os.environ.get("GITHUB_REPO", "witnessreplay")


class AgentOrchestrator:
    def __init__(self):
        self.loop_thread = None
        self.stop_event = threading.Event()
        self.current_agent = None
        self.current_process = None
        self.current_run_id = None
        self.cycle_count = 0
        self.status = "idle"
        self._event_loop = None

    def start_loop(self):
        if self.loop_thread and self.loop_thread.is_alive():
            return False
        self.stop_event.clear()
        db.set_config("loop_active", "true")
        self.loop_thread = threading.Thread(target=self._loop, daemon=True)
        self.loop_thread.start()
        self.status = "running"
        return True

    def stop_loop(self):
        self.stop_event.set()
        db.set_config("loop_active", "false")
        self.status = "stopping"
        if self.current_process:
            try:
                import signal
                pid = self.current_process.pid
                # Kill the entire process group to stop copilot and its children
                try:
                    os.killpg(os.getpgid(pid), signal.SIGTERM)
                except (ProcessLookupError, PermissionError):
                    pass
                self.current_process.wait(timeout=10)
            except Exception:
                try:
                    self.current_process.kill()
                    self.current_process.wait(timeout=5)
                except Exception:
                    pass
        if self.current_run_id:
            db.update_run(self.current_run_id,
                          status="cancelled",
                          finished_at=datetime.utcnow().isoformat(),
                          error_message="Stopped by user")
        self.status = "stopped"
        self.current_agent = None
        self.current_run_id = None

    def _loop(self):
        self._event_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._event_loop)

        while not self.stop_event.is_set():
            self.cycle_count += 1
            logger.info(f"=== Cycle {self.cycle_count} starting ===")

            # Run Feature Agent
            if self.stop_event.is_set():
                break
            success = self._run_agent("feature")
            if not success and not self.stop_event.is_set():
                self._send_alert_sync("feature", "Feature agent failed")
                delay = 60
            else:
                delay = int(db.get_config("delay_between_agents") or "30")

            if self._wait(delay):
                break

            # Run UX Agent
            if self.stop_event.is_set():
                break
            success = self._run_agent("ux")
            if not success and not self.stop_event.is_set():
                self._send_alert_sync("ux", "UX agent failed")
                delay = 60
            else:
                delay = int(db.get_config("delay_between_agents") or "30")

            if self._wait(delay):
                break

            # Run Tester Agent
            if self.stop_event.is_set():
                break
            success = self._run_agent("tester")
            if not success and not self.stop_event.is_set():
                self._send_alert_sync("tester", "Tester agent failed")
                delay = 60
            else:
                delay = int(db.get_config("delay_between_cycles") or "120")

            self.status = "waiting"
            if self._wait(delay):
                break
            self.status = "running"

        self.status = "stopped"
        try:
            self._event_loop.close()
        except Exception:
            pass

    def _wait(self, seconds):
        for _ in range(seconds):
            if self.stop_event.is_set():
                return True
            time.sleep(1)
        return False

    def _run_agent(self, agent_name: str) -> bool:
        self.current_agent = agent_name
        self.status = f"running:{agent_name}"

        prompt_file = os.path.join(PROMPTS_DIR, f"{agent_name}_agent.md")
        if not os.path.exists(prompt_file):
            logger.error(f"Prompt file not found: {prompt_file}")
            self.current_agent = None
            return False

        with open(prompt_file) as f:
            prompt = f.read()

        # Inject pending user ideas into the prompt
        ideas_text = db.get_pending_ideas_text()
        if ideas_text:
            prompt = prompt + "\n\n" + ideas_text

        # Inject recent change history so agent knows what was done before
        changes_text = db.get_recent_changes_for_prompt(limit=10)
        if changes_text:
            prompt = prompt + "\n\n" + changes_text

        # Inject open bugs so agents fix them
        bugs_text = db.get_open_bugs_text()
        if bugs_text:
            prompt = prompt + "\n\n" + bugs_text

        run_id = db.create_run(agent_name, self.cycle_count)
        self.current_run_id = run_id
        max_retries = int(db.get_config("max_retries") or "2")
        start_time = time.time()

        for attempt in range(1, max_retries + 1):
            if self.stop_event.is_set():
                db.update_run(run_id, status="cancelled",
                              finished_at=datetime.utcnow().isoformat())
                self.current_agent = None
                self.current_run_id = None
                return False

            logger.info(f"Running {agent_name} (attempt {attempt}/{max_retries})")

            try:
                ts = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
                log_file = f"/app/data/logs/{agent_name}_{ts}.log"
                os.makedirs(os.path.dirname(log_file), exist_ok=True)

                cmd = [
                    "/usr/local/bin/copilot",
                    "-p", prompt,
                    "--yolo",
                    "--no-ask-user",
                    "--model", "claude-sonnet-4.5",
                    "--add-dir", PROJECT_DIR,
                    "--add-dir", SCRIPTS_DIR,
                    "--no-auto-update",
                    "--share", log_file.replace('.log', '.session.md'),
                ]

                with open(log_file, 'w') as lf:
                    self.current_process = subprocess.Popen(
                        cmd, stdout=lf, stderr=subprocess.STDOUT, cwd=PROJECT_DIR,
                        preexec_fn=os.setsid  # Create new process group for clean kill
                    )
                    exit_code = self.current_process.wait()
                    self.current_process = None

                if exit_code == 0:
                    self._ensure_committed(agent_name)
                    self._parse_commit_for_completions(agent_name)
                    changes = self._get_changes_stat()
                    self._git_push()
                    if "backend/" in changes:
                        self._restart_app_container()

                    log_tail = ""
                    try:
                        with open(log_file) as lf:
                            content = lf.read()
                            log_tail = content[-4000:]
                    except Exception:
                        pass

                    elapsed = int(time.time() - start_time)
                    db.update_run(run_id,
                                  status="completed",
                                  finished_at=datetime.utcnow().isoformat(),
                                  duration_sec=elapsed,
                                  commit_sha=self._get_last_commit(),
                                  changes_summary=changes,
                                  log_tail=log_tail)

                    self._update_agent_state(agent_name, "completed", changes)
                    self.current_agent = None
                    self.current_run_id = None
                    return True
                else:
                    logger.warning(f"{agent_name} exited with code {exit_code}")
                    if attempt < max_retries:
                        time.sleep(15)

            except Exception as e:
                logger.error(f"Error running {agent_name}: {e}")
                if attempt < max_retries:
                    time.sleep(15)

        elapsed = int(time.time() - start_time)
        db.update_run(run_id,
                      status="failed",
                      finished_at=datetime.utcnow().isoformat(),
                      duration_sec=elapsed,
                      error_message=f"Failed after {max_retries} attempts")
        self.current_agent = None
        self.current_run_id = None
        return False

    def _ensure_committed(self, agent_name: str):
        try:
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                capture_output=True, text=True, cwd=PROJECT_DIR, timeout=15
            )
            if result.stdout.strip():
                subprocess.run(["git", "add", "-A"], cwd=PROJECT_DIR, timeout=15)
                subprocess.run([
                    "git", "commit", "-m",
                    f"feat({agent_name}): continuous improvement cycle {self.cycle_count}\n\n"
                    f"Automated improvements by {agent_name} agent.\n\n"
                    f"Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
                ], cwd=PROJECT_DIR, timeout=30)
        except Exception as e:
            logger.warning(f"ensure_committed: {e}")

    def _get_changes_stat(self) -> str:
        try:
            result = subprocess.run(
                ["git", "--no-pager", "diff", "--stat", "HEAD~1"],
                capture_output=True, text=True, cwd=PROJECT_DIR, timeout=15
            )
            return result.stdout.strip() or "No changes detected"
        except Exception:
            return "Could not determine changes"

    def _get_last_commit(self) -> str:
        try:
            result = subprocess.run(
                ["git", "--no-pager", "log", "-1", "--format=%h %s"],
                capture_output=True, text=True, cwd=PROJECT_DIR, timeout=10
            )
            return result.stdout.strip()
        except Exception:
            return ""

    def _git_push(self):
        try:
            result = subprocess.run(
                ["git", "push", "origin", "master"],
                capture_output=True, text=True, cwd=PROJECT_DIR, timeout=60
            )
            if result.returncode != 0:
                logger.warning(f"git push stderr: {result.stderr}")
        except Exception as e:
            logger.error(f"Git push failed: {e}")

    def _parse_commit_for_completions(self, agent_name: str):
        """Parse the last commit message to auto-close ideas and bugs."""
        try:
            result = subprocess.run(
                ["git", "log", "-1", "--format=%B"],
                capture_output=True, text=True, cwd=PROJECT_DIR, timeout=10
            )
            msg = result.stdout.strip()
            if not msg:
                return

            idea_ids = re.findall(r'idea\s*#(\d+)', msg, re.IGNORECASE)
            for idea_id in idea_ids:
                db.update_idea(int(idea_id), status="done",
                               implemented_at=datetime.utcnow().isoformat(),
                               implemented_by=agent_name)
                logger.info(f"Marked idea #{idea_id} as done (by {agent_name})")

            bug_ids = re.findall(r'bug\s*#(\d+)', msg, re.IGNORECASE)
            for bug_id in bug_ids:
                db.update_bug(int(bug_id), status="fixed",
                              fixed_at=datetime.utcnow().isoformat(),
                              fixed_by=agent_name)
                logger.info(f"Marked bug #{bug_id} as fixed (by {agent_name})")
        except Exception as e:
            logger.warning(f"Failed to parse commit for completions: {e}")

    def _restart_app_container(self):
        """Rebuild the witnessreplay Docker container and schedule old image cleanup."""
        try:
            # Get current image ID before rebuild
            old_image_id = self._get_container_image_id("witnessreplay")
            logger.info(f"Backend changes detected. Current image: {old_image_id or 'unknown'}")

            # Rebuild and recreate the container
            logger.info("Rebuilding witnessreplay container...")
            result = subprocess.run(
                ["docker", "compose", "up", "-d", "--build"],
                capture_output=True, text=True, cwd=PROJECT_DIR, timeout=300
            )
            if result.returncode != 0:
                logger.warning(f"Container rebuild failed: {result.stderr}")
                return

            # Wait for container to start and verify health
            time.sleep(15)
            new_image_id = self._get_container_image_id("witnessreplay")

            if not new_image_id:
                logger.warning("Container not running after rebuild")
                return

            if new_image_id == old_image_id:
                logger.info("Image unchanged after rebuild (no code diff)")
                return

            logger.info(f"New image running: {new_image_id} (old: {old_image_id})")

            # Verify new container is healthy
            if not self._verify_container_healthy("witnessreplay"):
                logger.warning("New container is not healthy, skipping old image cleanup")
                return

            # Schedule old image cleanup after 30 minutes
            if old_image_id:
                self._schedule_image_cleanup(old_image_id, new_image_id, delay_minutes=30)

        except Exception as e:
            logger.error(f"Failed to rebuild container: {e}")

    def _get_container_image_id(self, container_name: str) -> str:
        """Get the image ID of a running container."""
        try:
            result = subprocess.run(
                ["docker", "inspect", container_name, "--format", "{{.Image}}"],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception:
            pass
        return ""

    def _verify_container_healthy(self, container_name: str) -> bool:
        """Verify a container is running and responding."""
        try:
            # Check container status
            result = subprocess.run(
                ["docker", "inspect", container_name, "--format", "{{.State.Status}}"],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode != 0 or result.stdout.strip() != "running":
                return False
            # Check health endpoint
            result = subprocess.run(
                ["curl", "-sf", "--max-time", "5", "http://localhost:8088/api/health"],
                capture_output=True, text=True, timeout=10
            )
            return result.returncode == 0
        except Exception:
            return False

    def _schedule_image_cleanup(self, old_image_id: str, new_image_id: str, delay_minutes: int = 30):
        """Schedule deletion of old image after verifying new one is still running."""
        def _cleanup():
            time.sleep(delay_minutes * 60)
            try:
                # Verify new image is STILL running (not rolled back)
                current_id = self._get_container_image_id("witnessreplay")
                if current_id != new_image_id:
                    logger.info(f"Image cleanup skipped: container no longer running expected image "
                                f"(expected {new_image_id[:20]}, got {current_id[:20]})")
                    return

                # Verify container has been up for at least 30 minutes
                uptime = self._get_container_uptime("witnessreplay")
                if uptime < delay_minutes * 60:
                    logger.info(f"Image cleanup skipped: container uptime ({uptime}s) < {delay_minutes}m")
                    return

                # Delete the old image
                logger.info(f"Cleaning up old image: {old_image_id[:20]}...")
                result = subprocess.run(
                    ["docker", "rmi", old_image_id],
                    capture_output=True, text=True, timeout=30
                )
                if result.returncode == 0:
                    logger.info(f"Old image {old_image_id[:20]} deleted successfully")
                else:
                    logger.warning(f"Old image cleanup failed: {result.stderr.strip()}")

                # Also prune any dangling images
                subprocess.run(
                    ["docker", "image", "prune", "-f"],
                    capture_output=True, text=True, timeout=30
                )
            except Exception as e:
                logger.error(f"Image cleanup error: {e}")

        t = threading.Thread(target=_cleanup, daemon=True)
        t.start()
        logger.info(f"Scheduled cleanup of old image {old_image_id[:20]} in {delay_minutes} minutes")

    def _get_container_uptime(self, container_name: str) -> int:
        """Get container uptime in seconds."""
        try:
            result = subprocess.run(
                ["docker", "inspect", container_name, "--format", "{{.State.StartedAt}}"],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                started = result.stdout.strip()
                # Parse ISO format: 2026-02-24T01:21:29.649Z
                from datetime import timezone
                started_dt = datetime.fromisoformat(started.replace('Z', '+00:00'))
                now_dt = datetime.now(timezone.utc)
                return int((now_dt - started_dt).total_seconds())
        except Exception:
            pass
        return 0

    def _update_agent_state(self, agent_name: str, status: str, changes: str):
        state_file = os.path.join(SCRIPTS_DIR, "AGENT_STATE.md")
        try:
            ts = datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')
            entry = f"\n### [{ts}] {agent_name} — {status}\n```\n{changes[:500]}\n```\n"
            with open(state_file, 'a') as f:
                f.write(entry)
        except Exception as e:
            logger.warning(f"Failed to update AGENT_STATE: {e}")

        # If tester agent completed, read bug_report.json and create bug entries
        if agent_name == "tester":
            self._process_tester_bugs()

    def _send_alert_sync(self, agent_name: str, error_msg: str):
        try:
            html = f"""
            <h2 style="color:#f44336;">⚠️ WitnessReplay Agent Failed</h2>
            <table style="border-collapse:collapse;">
                <tr><td style="padding:8px;font-weight:bold;">Agent:</td><td style="padding:8px;">{agent_name}</td></tr>
                <tr><td style="padding:8px;font-weight:bold;">Cycle:</td><td style="padding:8px;">{self.cycle_count}</td></tr>
                <tr><td style="padding:8px;font-weight:bold;">Error:</td><td style="padding:8px;">{error_msg}</td></tr>
                <tr><td style="padding:8px;font-weight:bold;">Time:</td><td style="padding:8px;">{datetime.utcnow().isoformat()}</td></tr>
            </table>
            <p>Check the <a href="http://192.168.68.68:9099">WitnessReplay Monitor</a> for details.</p>
            """
            self._event_loop.run_until_complete(
                send_alert("⚠️ WitnessReplay Stopped Working", html)
            )
        except Exception as e:
            logger.error(f"Failed to send alert: {e}")

    def _process_tester_bugs(self):
        """Read tester's bug_report.json and create bug entries in the database."""
        import json
        bug_report_path = os.path.join(PROJECT_DIR, "tests", "bug_report.json")
        try:
            if not os.path.exists(bug_report_path):
                logger.info("No bug_report.json found from tester")
                return

            with open(bug_report_path) as f:
                report = json.load(f)

            bugs = report.get("bugs", [])
            created = 0
            for bug in bugs:
                title = bug.get("title", "Untitled bug")
                # Skip if a bug with this exact title already exists and is open
                existing = db.get_bugs(status="open")
                if any(b["title"] == title for b in existing):
                    logger.info(f"Bug already exists: {title}")
                    continue

                db.create_bug(
                    title=title,
                    description=bug.get("description", ""),
                    severity=bug.get("severity", "medium"),
                    found_by="tester",
                    steps_to_reproduce=bug.get("steps_to_reproduce"),
                    expected_behavior=bug.get("expected_behavior"),
                    actual_behavior=bug.get("actual_behavior"),
                )
                created += 1

            logger.info(f"Processed tester bug report: {created} new bugs created from {len(bugs)} found")

            # Archive the report after processing
            archive_path = bug_report_path + f".{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.processed"
            os.rename(bug_report_path, archive_path)

        except Exception as e:
            logger.error(f"Failed to process tester bug report: {e}")

    def run_single_agent(self, agent_name: str) -> bool:
        if self.current_agent:
            return False
        # Clear stop event so the agent can actually run
        self.stop_event.clear()
        t = threading.Thread(target=self._run_single_wrapper, args=(agent_name,), daemon=True)
        t.start()
        return True

    def _run_single_wrapper(self, agent_name: str):
        """Wrapper for single agent runs — sets up event loop and resets state after."""
        self._event_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._event_loop)
        try:
            self._run_agent(agent_name)
        finally:
            self.current_agent = None
            self.current_run_id = None
            self.status = "stopped"
            try:
                self._event_loop.close()
            except Exception:
                pass

    def get_status(self) -> dict:
        return {
            "status": self.status,
            "current_agent": self.current_agent,
            "current_run_id": self.current_run_id,
            "cycle_count": self.cycle_count,
            "loop_active": self.loop_thread is not None and self.loop_thread.is_alive(),
        }


orchestrator = AgentOrchestrator()
