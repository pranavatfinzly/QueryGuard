"""Structural guards on the reusable workflow every consumer repository calls.

The workflow is the org-wide blast radius: one bad edit reaches every repository on
its next PR. These tests pin the properties that must not regress silently.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

WORKFLOW = Path(".github/workflows/queryguard-review.yml")


def _load() -> dict[Any, Any]:
    loaded: dict[Any, Any] = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return loaded


def _call() -> dict[str, Any]:
    # YAML 1.1 reads the bare key `on` as the boolean True.
    call: dict[str, Any] = _load()[True]["workflow_call"]
    return call


def _steps() -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = _load()["jobs"]["review"]["steps"]
    return steps


def test_no_run_script_interpolates_an_expression() -> None:
    # `${{ ... }}` inside a `run:` body is spliced into the shell text before it runs,
    # so a crafted input (a branch name, a ref) becomes command injection. Values must
    # reach the script through `env:` instead.
    for step in _steps():
        script = step.get("run")
        if script is not None:
            assert "${{" not in script, f"step {step.get('name')!r} interpolates into run:"


def test_source_repo_and_ref_are_configurable_inputs() -> None:
    inputs = _call()["inputs"]

    assert inputs["queryguard-repo"]["default"] == "pranavatfinzly/QueryGuard"
    assert "queryguard-ref" in inputs


def test_private_install_token_is_an_optional_secret() -> None:
    secrets = _call()["secrets"]

    assert secrets["queryguard-token"]["required"] is False
    assert secrets["groq-api-key"]["required"] is False


def test_disable_llm_defaults_off_and_passes_no_llm() -> None:
    inputs = _call()["inputs"]
    review = next(step for step in _steps() if step.get("name") == "Review pull request")

    assert inputs["disable-llm"]["default"] is False
    assert "--no-llm" in review["env"]["NO_LLM_FLAG"]
    assert "$NO_LLM_FLAG" in review["run"]


def test_token_permissions_stay_minimal() -> None:
    assert _load()["permissions"] == {"contents": "read", "pull-requests": "write"}


def test_advisory_input_defaults_off_and_reaches_the_cli_as_an_env_var() -> None:
    inputs = _call()["inputs"]
    review = next(step for step in _steps() if step.get("name") == "Review pull request")

    assert inputs["advisory"]["default"] is False
    assert inputs["advisory"]["type"] == "boolean"
    assert "inputs.advisory" in review["env"]["QUERYGUARD_ADVISORY"]
