"""Tests for runner/pipeline_runner.py (config, templates, execution, hooks)."""
import json
import subprocess

import pytest

from runner.pipeline_runner import PipelineRunner

CHAIN_YAML = """\
name: test-echo
version: 0.1.0
steps:
  - id: first
    type: script
    script: python -c "print('hello-artifact')"
  - id: second
    type: script
    script: python -c "print('got:' + open(r'''{{steps.first.output_file}}''').read().strip())"
  - id: gated
    type: script
    script: python -c "print('never')"
    condition: env:TEST_CONDITION_UNSET_VAR
"""


def make_runner(tmp_path, yaml_text=CHAIN_YAML, dry_run=False):
    pipeline = tmp_path / "pipeline.yaml"
    pipeline.write_text(yaml_text, encoding="utf-8")
    return PipelineRunner(str(pipeline), dry_run=dry_run, data_dir=str(tmp_path / "data"))


class TestConfigLoading:
    def test_missing_file(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            PipelineRunner(str(tmp_path / "nope.yaml"))

    def test_missing_steps_key(self, tmp_path):
        p = tmp_path / "p.yaml"
        p.write_text("name: x\n", encoding="utf-8")
        with pytest.raises(ValueError, match="steps"):
            PipelineRunner(str(p))

    def test_steps_not_a_list(self, tmp_path):
        p = tmp_path / "p.yaml"
        p.write_text("name: x\nsteps: 3\n", encoding="utf-8")
        with pytest.raises(ValueError, match="list"):
            PipelineRunner(str(p))


class TestTemplates:
    def test_unknown_key_left_untouched(self, tmp_path):
        runner = make_runner(tmp_path)
        assert runner.render("literal {{not.a.key}} stays") == "literal {{not.a.key}} stays"

    def test_known_keys_resolved(self, tmp_path):
        runner = make_runner(tmp_path)
        runner.context["steps"]["s1"] = {"output": "X", "output_file": "f.txt", "status": "ok"}
        rendered = runner.render("{{pipeline}} {{date}} {{steps.s1.output_file}}")
        assert "test-echo" in rendered
        assert runner.context["date"] in rendered
        assert "f.txt" in rendered


class TestRun:
    def test_dry_run_executes_and_writes_nothing(self, tmp_path):
        runner = make_runner(tmp_path, dry_run=True)
        summary = runner.run()

        assert summary["status"] == "ok"
        assert all(step["status"] == "dry_run" for step in summary["steps"])
        assert not (tmp_path / "data" / "runs").exists()

    def test_script_chain_artifacts_and_state(self, tmp_path):
        runner = make_runner(tmp_path)
        summary = runner.run()

        assert summary["status"] == "ok"
        statuses = {step["id"]: step["status"] for step in summary["steps"]}
        assert statuses == {"first": "ok", "second": "ok", "gated": "skipped"}

        # step output chained into the next step via output_file
        second = next(s for s in summary["steps"] if s["id"] == "second")
        assert "got:hello-artifact" in second["stdout"]

        # full stdout persisted per step, plus summary and scheduler state
        assert (runner.run_dir / "steps" / "first.stdout.txt").read_text(
            encoding="utf-8").strip() == "hello-artifact"
        assert (runner.run_dir / "summary.json").exists()
        state = json.loads(
            (tmp_path / "data" / "last_runs" / "test-echo.json").read_text(encoding="utf-8"))
        assert state["pipeline"] == "test-echo"
        assert state["status"] == "ok"

    def test_unknown_step_type_fails_pipeline(self, tmp_path):
        runner = make_runner(tmp_path, "name: t\nsteps: [{id: bad, type: nope}]\n")
        summary = runner.run()
        assert summary["status"] == "failed"
        assert "Unknown step type" in summary["steps"][0]["error"]

    def test_script_step_without_command_fails(self, tmp_path):
        runner = make_runner(tmp_path, "name: t\nsteps: [{id: s, type: script}]\n")
        summary = runner.run()
        assert summary["status"] == "failed"

    def test_pre_run_hook_skip_code_marks_pipeline_skipped(self, tmp_path, monkeypatch):
        def fake_hook(self, hook_file, *args):
            return subprocess.CompletedProcess(args=[hook_file], returncode=10)

        monkeypatch.setattr(PipelineRunner, "_run_hook", fake_hook)
        runner = make_runner(tmp_path)
        summary = runner.run()
        assert summary["status"] == "skipped"
        assert not (runner.run_dir / "steps").exists()

    def test_condition_env_gate(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TEST_CONDITION_UNSET_VAR", "1")
        runner = make_runner(tmp_path)
        summary = runner.run()
        statuses = {step["id"]: step["status"] for step in summary["steps"]}
        assert statuses["gated"] == "ok"
