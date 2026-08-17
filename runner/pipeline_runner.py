"""
Pipeline Runner · 共用管線執行器

Reads a pipeline YAML definition and executes its steps in sequence.
Supports two step types:
- script: Run a fixed Python/shell script (mechanical work)
- claude: Invoke Claude CLI for judgment/writing tasks

Usage:
    python runner/pipeline_runner.py --pipeline pipelines/daily-job-schedule.yaml
    python runner/pipeline_runner.py --pipeline pipelines/daily-job-schedule.yaml --dry-run
"""
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

try:
    import yaml
except ImportError:
    print("Error: PyYAML required. Install with: pip install pyyaml")
    sys.exit(1)


class PipelineRunner:
    """Executes a pipeline defined in YAML."""

    def __init__(self, pipeline_path: str, dry_run: bool = False):
        self.pipeline_path = Path(pipeline_path)
        self.dry_run = dry_run
        self.config = self._load_config()
        self.start_time = datetime.utcnow()

    def _load_config(self) -> dict:
        """Load and validate the pipeline YAML."""
        if not self.pipeline_path.exists():
            raise FileNotFoundError(f"Pipeline not found: {self.pipeline_path}")

        with open(self.pipeline_path, encoding="utf-8") as f:
            config = yaml.safe_load(f)

        required = ["name", "steps"]
        for key in required:
            if key not in config:
                raise ValueError(f"Pipeline missing required key: {key}")

        return config

    def run(self) -> dict:
        """Execute all steps in sequence."""
        name = self.config["name"]
        steps = self.config["steps"]

        print(f"\n  {'='*50}")
        print(f"  Pipeline: {name}")
        print(f"  Started:  {self.start_time.isoformat()}")
        print(f"  Steps:    {len(steps)}")
        print(f"  {'='*50}\n")

        results = []
        for i, step in enumerate(steps, 1):
            step_id = step.get("id", f"step_{i}")
            step_type = step.get("type", "claude")
            description = step.get("description", "")

            print(f"  [{i}/{len(steps)}] {step_id} ({step_type})")
            if description:
                print(f"         {description}")

            if self.dry_run:
                print(f"         [DRY-RUN] Would execute: {step_type}")
                result = {"id": step_id, "type": step_type, "status": "dry_run"}
            else:
                result = self._execute_step(step)
                print(f"         Status: {result['status']}")

            results.append(result)
            print()

        # Summary
        end_time = datetime.utcnow()
        succeeded = sum(1 for r in results if r["status"] in ("ok", "dry_run"))
        failed = sum(1 for r in results if r["status"] == "failed")

        print(f"  {'='*50}")
        print(f"  Pipeline: {name}")
        print(f"  Duration: {(end_time - self.start_time).total_seconds():.1f}s")
        print(f"  Succeeded: {succeeded} | Failed: {failed}")
        print(f"  {'='*50}\n")

        return {
            "pipeline": name,
            "status": "ok" if failed == 0 else "failed",
            "started": self.start_time.isoformat(),
            "finished": end_time.isoformat(),
            "steps": results,
        }

    def _execute_step(self, step: dict) -> dict:
        """Execute a single step based on its type."""
        step_type = step.get("type", "claude")
        step_id = step.get("id", "unknown")

        try:
            if step_type == "script":
                return self._run_script(step)
            elif step_type == "claude-skill":
                return self._run_claude_skill(step)
            elif step_type == "claude":
                return self._run_claude(step)
            else:
                return {"id": step_id, "type": step_type, "status": "failed",
                        "error": f"Unknown step type: {step_type}"}
        except Exception as e:
            return {"id": step_id, "type": step_type, "status": "failed", "error": str(e)}

    def _run_script(self, step: dict) -> dict:
        """Run a fixed script (mechanical work)."""
        script = step.get("script", step.get("command", ""))
        if not script:
            return {"id": step["id"], "type": "script", "status": "failed",
                    "error": "No script/command specified"}

        result = subprocess.run(script, shell=True, capture_output=True, text=True)

        return {
            "id": step["id"],
            "type": "script",
            "status": "ok" if result.returncode == 0 else "failed",
            "stdout": result.stdout[:500],
            "stderr": result.stderr[:500] if result.returncode != 0 else "",
        }

    def _run_claude(self, step: dict) -> dict:
        """Invoke Claude CLI for judgment/writing tasks."""
        prompt = step.get("prompt", "")
        if not prompt:
            return {"id": step["id"], "type": "claude", "status": "failed",
                    "error": "No prompt specified"}

        # Build claude command
        cmd = ["claude", "-p", prompt]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

        return {
            "id": step["id"],
            "type": "claude",
            "status": "ok" if result.returncode == 0 else "failed",
            "output": result.stdout[:1000],
            "stderr": result.stderr[:500] if result.returncode != 0 else "",
        }

    def _run_claude_skill(self, step: dict) -> dict:
        """Invoke Claude CLI with a specific skill."""
        skill = step.get("skill", "")
        prompt = step.get("prompt", step.get("description", f"Use skill: {skill}"))

        cmd = ["claude", "-p", f"/{skill} {prompt}"]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

        return {
            "id": step["id"],
            "type": "claude-skill",
            "skill": skill,
            "status": "ok" if result.returncode == 0 else "failed",
            "output": result.stdout[:1000],
        }


def main():
    parser = argparse.ArgumentParser(description="Pipeline Runner")
    parser.add_argument("--pipeline", required=True, help="Path to pipeline YAML")
    parser.add_argument("--dry-run", action="store_true", help="Show what would run")
    args = parser.parse_args()

    try:
        runner = PipelineRunner(args.pipeline, args.dry_run)
        result = runner.run()

        # Save execution log
        log_dir = Path("data") / "execution_logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / f"{result['pipeline']}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
        log_file.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"  Log saved: {log_file}")

        sys.exit(0 if result["status"] == "ok" else 1)

    except (FileNotFoundError, ValueError) as e:
        print(f"  Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
