"""
Pipeline Runner · 共用管線執行器

Reads a pipeline YAML definition and executes its steps in sequence.
Supports three step types:
- script:       Run a fixed shell command (mechanical work)
- claude:       Invoke Claude CLI for judgment/writing tasks
- claude-skill: Invoke Claude CLI with a specific skill

Features:
- hooks/pre_run.sh  runs before each step (exit code 10 = skip pipeline)
- hooks/post_run.sh runs after the pipeline (frontmatter write-back)
- .env is auto-loaded from the repo root (template: config/.env.template)
- Each run gets its own directory data/runs/<pipeline>/<timestamp>/ holding
  steps/<step_id>.json (full result) and steps/<step_id>.stdout.txt (full stdout)
- Later steps can reference earlier outputs via templates:
    {{steps.<id>.output}}       stdout inline (capped, safe for CLI args)
    {{steps.<id>.output_file}}  path to the full stdout file
    {{run_dir}} {{date}} {{timestamp}} {{pipeline}}
- Script steps receive env vars: PIPELINE_NAME, PIPELINE_STEP_ID,
  PIPELINE_RUN_DIR, PIPELINE_DATE
- Optional per-step `condition: env:VAR` — step runs only when VAR is set

Usage:
    python runner/pipeline_runner.py --pipeline pipelines/daily-job-schedule.yaml
    python runner/pipeline_runner.py --pipeline pipelines/daily-job-schedule.yaml --dry-run
    python runner/pipeline_runner.py --due     # run every cron pipeline whose time has come
    python runner/pipeline_runner.py --list    # show pipelines, schedules and due status
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import yaml
except ImportError:
    print("Error: PyYAML required. Install with: pip install pyyaml")
    sys.exit(1)

try:
    from dotenv import load_dotenv
except ImportError:  # python-dotenv optional — .env just won't auto-load
    load_dotenv = None

try:  # importable both as `python runner/pipeline_runner.py` and as a package module
    from runner.cron_schedule import is_due
except ImportError:
    from cron_schedule import is_due

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOKS_DIR = REPO_ROOT / "hooks"
DATA_DIR_ENV = "PIPELINE_DATA_DIR"

HOOK_SKIP_CODE = 10  # pre_run hook: pipeline already done → skip everything
HOOK_TIMEOUT = 60
DEFAULT_SCRIPT_TIMEOUT = 600
DEFAULT_CLAUDE_TIMEOUT = 300
DEFAULT_ALLOWED_TOOLS = "Read,Glob,Grep"
INLINE_OUTPUT_CAP = 4000  # max stdout chars inlined into later prompts/commands
CONSOLE_PREVIEW = 200

TEMPLATE_RE = re.compile(r"\{\{\s*([A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)*)\s*\}\}")


class PipelineSkip(Exception):
    """Raised when the pre_run hook signals the pipeline should be skipped."""


class PipelineRunner:
    """Executes a pipeline defined in YAML."""

    def __init__(self, pipeline_path: str, dry_run: bool = False, data_dir: str | None = None):
        self.pipeline_path = Path(pipeline_path)
        self.dry_run = dry_run
        self.config = self._load_config()
        self.start_time = datetime.now(timezone.utc)
        self.name = self.config["name"]

        data_dir = data_dir or os.environ.get(DATA_DIR_ENV) or (REPO_ROOT / "data")
        self.data_dir = Path(data_dir)
        self.run_dir = self.data_dir / "runs" / self.name / self.start_time.strftime("%Y%m%d_%H%M%S")

        now_local = datetime.now().astimezone()
        self.context = {
            "pipeline": self.name,
            "date": now_local.strftime("%Y-%m-%d"),
            "timestamp": now_local.isoformat(timespec="seconds"),
            "run_dir": str(self.run_dir),
            "steps": {},
        }

    # ------------------------------------------------------------------ config

    def _load_config(self) -> dict:
        """Load and validate the pipeline YAML."""
        if not self.pipeline_path.exists():
            raise FileNotFoundError(f"Pipeline not found: {self.pipeline_path}")

        with open(self.pipeline_path, encoding="utf-8") as f:
            config = yaml.safe_load(f)

        if not isinstance(config, dict):
            raise ValueError(f"Pipeline YAML is not a mapping: {self.pipeline_path}")

        required = ["name", "steps"]
        for key in required:
            if key not in config:
                raise ValueError(f"Pipeline missing required key: {key}")
        if not isinstance(config["steps"], list):
            raise ValueError("Pipeline 'steps' must be a list")

        return config

    # --------------------------------------------------------------- templates

    def render(self, text: str) -> str:
        """Replace {{dotted.key}} templates with run-context values.

        Unknown keys are left untouched so prompts can contain literal braces.
        """
        if not isinstance(text, str) or "{{" not in text:
            return text

        def sub(match: re.Match) -> str:
            value = self._lookup(match.group(1))
            return match.group(0) if value is None else str(value)

        return TEMPLATE_RE.sub(sub, text)

    def _lookup(self, dotted_key: str):
        node: object = self.context
        for part in dotted_key.split("."):
            if not isinstance(node, dict) or part not in node:
                return None
            node = node[part]
        return node

    # --------------------------------------------------------------- conditions

    def _check_condition(self, step: dict) -> tuple[bool, str | None]:
        """Evaluate a step's `condition`. v1 supports `env:VAR_NAME` only."""
        condition = str(step.get("condition", "")).strip()
        if not condition:
            return True, None
        if condition.startswith("env:"):
            var = condition[4:]
            if os.environ.get(var):
                return True, None
            return False, f"condition not met: env:{var} is not set"
        print(f"         WARN: unsupported condition '{condition}' "
              f"(supported: 'env:VAR') — running anyway")
        return True, None

    # -------------------------------------------------------------------- hooks

    def _run_hook(self, hook_file: str, *args: str):
        """Run a bash hook from hooks/. Returns None when it cannot run."""
        hook_path = HOOKS_DIR / hook_file
        bash = shutil.which("bash")
        if not hook_path.exists():
            print(f"         WARN: hook not found: {hook_path}")
            return None
        if not bash:
            print(f"         WARN: bash not found on PATH — skipping hook {hook_file}")
            return None

        proc = subprocess.run(
            [bash, str(hook_path), *args],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=HOOK_TIMEOUT, cwd=REPO_ROOT,
        )
        if proc.stdout.strip():
            for line in proc.stdout.strip().splitlines():
                print(f"         [hook] {line}")
        if proc.returncode not in (0, HOOK_SKIP_CODE) or proc.stderr.strip():
            for line in (proc.stderr or "").strip().splitlines():
                print(f"         [hook:stderr] {line}")
        return proc

    def _pre_step_hook(self, step_id: str) -> None:
        proc = self._run_hook("pre_run.sh", self.name, step_id)
        if proc is None:
            return
        if proc.returncode == HOOK_SKIP_CODE:
            raise PipelineSkip(f"pre_run hook requested skip at step '{step_id}'")
        if proc.returncode != 0:
            print(f"         WARN: pre_run hook exited {proc.returncode} (non-blocking)")

    def _post_run_hook(self, status: str, output_path: str) -> None:
        self._run_hook("post_run.sh", self.name, status, output_path)

    # -------------------------------------------------------------------- output

    def _resolve_output_path(self) -> str:
        """Render config output.path; Obsidian targets fall back to run_dir
        when OBSIDIAN_VAULT_PATH is unset (skeleton mode)."""
        output = self.config.get("output") or {}
        path_tpl = output.get("path")
        if not path_tpl:
            return ""
        rendered = self.render(str(path_tpl))
        if str(output.get("destination")) == "obsidian":
            vault = os.environ.get("OBSIDIAN_VAULT_PATH", "")
            if vault:
                return str(Path(vault) / rendered)
            return str(self.run_dir / Path(rendered).name)
        return rendered

    @staticmethod
    def _safe_step_id(step_id: str) -> str:
        return re.sub(r"[^A-Za-z0-9_.-]", "_", step_id)

    def _record_step(self, step_id: str, result: dict) -> None:
        """Persist the full result and expose outputs to later steps."""
        full_text = result.get("stdout") or result.get("output") or ""
        entry = {
            "status": result["status"],
            "output": full_text[:INLINE_OUTPUT_CAP],
            "output_file": "",
        }

        if not self.dry_run:
            step_dir = self.run_dir / "steps"
            step_dir.mkdir(parents=True, exist_ok=True)
            safe_id = self._safe_step_id(step_id)
            stdout_file = step_dir / f"{safe_id}.stdout.txt"
            stdout_file.write_text(full_text, encoding="utf-8")

            slim = {k: v for k, v in result.items() if k not in ("stdout", "output")}
            slim["stdout_file"] = str(stdout_file)
            (step_dir / f"{safe_id}.json").write_text(
                json.dumps(slim, indent=2, ensure_ascii=False), encoding="utf-8")
            entry["output_file"] = str(stdout_file)

        self.context["steps"][step_id] = entry

    # ------------------------------------------------------------------ execution

    def _step_env(self, step_id: str) -> dict:
        env = dict(os.environ)
        env.update({
            "PIPELINE_NAME": self.name,
            "PIPELINE_STEP_ID": step_id,
            "PIPELINE_RUN_DIR": str(self.run_dir),
            "PIPELINE_DATE": self.context["date"],
        })
        return env

    @staticmethod
    def _preview(text: str | None) -> str:
        line = " ".join((text or "").split())
        return line[:CONSOLE_PREVIEW] + ("…" if len(line) > CONSOLE_PREVIEW else "")

    def _execute_step(self, step: dict, step_id: str) -> dict:
        step_type = step.get("type", "claude")
        try:
            if step_type == "script":
                return self._run_script(step, step_id)
            if step_type == "claude-skill":
                return self._run_claude(step, step_id, skill_mode=True)
            if step_type == "claude":
                return self._run_claude(step, step_id)
            return {"id": step_id, "type": step_type, "status": "failed",
                    "error": f"Unknown step type: {step_type}"}
        except subprocess.TimeoutExpired:
            return {"id": step_id, "type": step_type, "status": "failed",
                    "error": f"Step timed out after {step.get('timeout', '?')}s"}
        except Exception as e:  # noqa: BLE001 — runner must survive bad steps
            return {"id": step_id, "type": step_type, "status": "failed", "error": str(e)}

    def _run_script(self, step: dict, step_id: str) -> dict:
        command = self.render(step.get("script", step.get("command", "")))
        if not command:
            return {"id": step_id, "type": "script", "status": "failed",
                    "error": "No script/command specified"}

        proc = subprocess.run(
            command, shell=True, capture_output=True, text=True,
            encoding="utf-8", errors="replace",
            timeout=step.get("timeout", DEFAULT_SCRIPT_TIMEOUT),
            cwd=REPO_ROOT, env=self._step_env(step_id),
        )
        return {
            "id": step_id, "type": "script", "command": command,
            "status": "ok" if proc.returncode == 0 else "failed",
            "returncode": proc.returncode,
            "stdout": proc.stdout, "stderr": proc.stderr,
        }

    def _run_claude(self, step: dict, step_id: str, skill_mode: bool = False) -> dict:
        claude = shutil.which("claude")
        if not claude:
            return {"id": step_id, "type": step.get("type", "claude"), "status": "failed",
                    "error": "claude CLI not found on PATH"}

        if skill_mode:
            skill = step.get("skill", "")
            base_prompt = self.render(step.get("prompt", step.get("description", f"Use skill: {skill}")))
            prompt = f"/{skill} {base_prompt}"
        else:
            prompt = self.render(step.get("prompt", ""))
            if not prompt:
                return {"id": step_id, "type": step.get("type", "claude"), "status": "failed",
                        "error": "No prompt specified"}

        cmd = [claude, "-p", prompt,
               "--allowedTools", step.get("allowed_tools", DEFAULT_ALLOWED_TOOLS)]
        proc = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=step.get("timeout", DEFAULT_CLAUDE_TIMEOUT),
            cwd=REPO_ROOT, env=self._step_env(step_id),
        )
        return {
            "id": step_id, "type": step.get("type", "claude"),
            "status": "ok" if proc.returncode == 0 else "failed",
            "returncode": proc.returncode,
            "output": proc.stdout, "stderr": proc.stderr,
        }

    # ----------------------------------------------------------------------- run

    def run(self) -> dict:
        """Execute all steps in sequence, then run the post_run hook."""
        steps = self.config["steps"]

        print(f"\n  {'='*50}")
        print(f"  Pipeline: {self.name}")
        print(f"  Started:  {self.start_time.isoformat()}")
        print(f"  Steps:    {len(steps)}")
        print(f"  {'='*50}\n")

        if not self.dry_run:
            self.run_dir.mkdir(parents=True, exist_ok=True)

        results = []
        status = "ok"
        try:
            for i, step in enumerate(steps, 1):
                step_id = step.get("id", f"step_{i}")
                step_type = step.get("type", "claude")
                description = step.get("description", "")

                print(f"  [{i}/{len(steps)}] {step_id} ({step_type})")
                if description:
                    print(f"         {description}")

                if self.dry_run:
                    print("         [DRY-RUN] Would execute this step")
                    result = {"id": step_id, "type": step_type, "status": "dry_run"}
                else:
                    self._pre_step_hook(step_id)
                    met, note = self._check_condition(step)
                    if not met:
                        print(f"         {note}")
                        result = {"id": step_id, "type": step_type, "status": "skipped"}
                    else:
                        result = self._execute_step(step, step_id)

                self._record_step(step_id, result)
                results.append(result)

                print(f"         Status: {result['status']}")
                preview = result.get("stdout") or result.get("output") or result.get("error")
                if preview:
                    print(f"         Output: {self._preview(preview)}")
                print()

        except PipelineSkip as e:
            status = "skipped"
            print(f"  SKIP: {e}\n")

        failed = sum(1 for r in results if r["status"] == "failed")
        if status == "ok" and failed:
            status = "failed"

        end_time = datetime.now(timezone.utc)
        summary = {
            "pipeline": self.name,
            "status": status,
            "started": self.start_time.isoformat(),
            "finished": end_time.isoformat(),
            "duration_seconds": round((end_time - self.start_time).total_seconds(), 1),
            "steps": results,
        }

        print(f"  {'='*50}")
        print(f"  Pipeline: {self.name}")
        print(f"  Duration: {summary['duration_seconds']}s")
        print(f"  Succeeded: {len(results) - failed} | Failed: {failed} | Status: {status}")
        print(f"  {'='*50}\n")

        if not self.dry_run:
            (self.run_dir / "summary.json").write_text(
                json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
            self._write_state(summary)

            hook_status = {"ok": "generated", "failed": "failed"}.get(status, status)
            self._post_run_hook(hook_status, self._resolve_output_path())
            print(f"  Run dir: {self.run_dir}")

        return summary

    def _write_state(self, summary: dict) -> None:
        """Track last-run time for the scheduler (--due)."""
        state_dir = self.data_dir / "last_runs"
        state_dir.mkdir(parents=True, exist_ok=True)
        state = {"pipeline": self.name, "last_run": summary["finished"], "status": summary["status"]}
        (state_dir / f"{self.name}.json").write_text(
            json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


# ------------------------------------------------------------------ scheduler

def discover_pipelines(pipelines_dir: str | Path) -> list[tuple[Path, dict]]:
    """All pipeline YAMLs under pipelines_dir with a name and steps key
    (placeholders with empty steps are included; callers filter)."""
    found = []
    for path in sorted(Path(pipelines_dir).rglob("*.yaml")):
        try:
            with open(path, encoding="utf-8") as f:
                cfg = yaml.safe_load(f)
        except yaml.YAMLError as e:
            print(f"  WARN: skipping unparseable {path}: {e}")
            continue
        if not isinstance(cfg, dict) or "name" not in cfg or "steps" not in cfg:
            continue
        found.append((path, cfg))
    return found


def read_last_run(data_dir: Path, pipeline_name: str) -> str | None:
    state_file = Path(data_dir) / "last_runs" / f"{pipeline_name}.json"
    if not state_file.exists():
        return None
    try:
        return json.loads(state_file.read_text(encoding="utf-8")).get("last_run")
    except (OSError, json.JSONDecodeError):
        return None


def _resolve_data_dir(args) -> Path:
    return Path(args.data_dir or os.environ.get(DATA_DIR_ENV) or (REPO_ROOT / "data"))


def _cron_trigger(cfg: dict) -> str:
    trigger = cfg.get("trigger") or {}
    return str(trigger.get("schedule", "")) if trigger.get("type") == "cron" else ""


def cmd_list(args) -> int:
    data_dir = _resolve_data_dir(args)
    now = datetime.now().astimezone()

    print(f"\n  {'Pipeline':<50} {'Trigger':<16} {'Schedule':<14} Due")
    print(f"  {'-'*50} {'-'*16} {'-'*14} {'-'*10}")
    for _path, cfg in discover_pipelines(args.pipelines_dir):
        trigger = cfg.get("trigger") or {}
        sched = _cron_trigger(cfg)
        due = ""
        if sched:
            try:
                due = "due" if is_due(sched, read_last_run(data_dir, cfg["name"]), now) else "-"
            except ValueError as e:
                due = f"! {e}"
        state = "placeholder" if not cfg["steps"] else str(cfg.get("status", "draft"))
        print(f"  {cfg['name']:<50} {trigger.get('type', '?'):<16} {sched or '-':<14} {due or state}")
    print()
    return 0


def cmd_due(args) -> int:
    data_dir = _resolve_data_dir(args)
    now = datetime.now().astimezone()

    due_pipelines = []
    for path, cfg in discover_pipelines(args.pipelines_dir):
        sched = _cron_trigger(cfg)
        if not sched or not cfg["steps"]:
            continue
        try:
            if is_due(sched, read_last_run(data_dir, cfg["name"]), now):
                due_pipelines.append((path, cfg["name"]))
        except ValueError as e:
            print(f"  WARN: {cfg['name']} has invalid schedule '{sched}': {e}")

    if not due_pipelines:
        print("  No pipelines due.")
        return 0

    failed = []
    for path, name in due_pipelines:
        print(f"  → {name} is due — running\n")
        summary = PipelineRunner(path, args.dry_run, args.data_dir).run()
        if summary["status"] == "failed":
            failed.append(name)

    if failed:
        print(f"  Failed pipelines: {', '.join(failed)}")
        return 1
    return 0


def main():
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (AttributeError, OSError):
            pass

    if load_dotenv is not None:
        load_dotenv(REPO_ROOT / ".env")

    parser = argparse.ArgumentParser(description="Pipeline Runner")
    parser.add_argument("--pipeline", help="Path to pipeline YAML")
    parser.add_argument("--due", action="store_true",
                        help="Run every cron-triggered pipeline whose schedule fired since its last run")
    parser.add_argument("--list", action="store_true", dest="list_pipelines",
                        help="List pipelines with trigger and due status")
    parser.add_argument("--pipelines-dir", default=str(REPO_ROOT / "pipelines"),
                        help="Pipelines directory for --due/--list (default: <repo>/pipelines)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would run")
    parser.add_argument("--data-dir", help=f"Data directory (default: ${{{DATA_DIR_ENV}}} or <repo>/data)")
    args = parser.parse_args()

    if args.list_pipelines:
        sys.exit(cmd_list(args))
    if args.due:
        sys.exit(cmd_due(args))
    if not args.pipeline:
        parser.error("need one of: --pipeline, --due, --list")

    try:
        runner = PipelineRunner(args.pipeline, args.dry_run, args.data_dir)
        summary = runner.run()
    except (FileNotFoundError, ValueError) as e:
        print(f"  Error: {e}")
        sys.exit(1)

    sys.exit(0 if summary["status"] in ("ok", "skipped") else 1)


if __name__ == "__main__":
    main()
