"""Anthropic client, prompts, and structured outputs.

Conventions from CLAUDE.md:

- Default model :data:`MODEL`. Use the ``anthropic`` SDK — never raw HTTP.
- Structured outputs (``output_config.format``) so findings deserialize into
  :mod:`queryguard.models.finding` without ad-hoc parsing.
- Prompt caching: keep the system prompt and rule descriptions stable and cached;
  put the per-PR diff and query set *after* the cache breakpoint.
- Handle ``stop_reason == "refusal"`` before reading ``response.content``.
"""

from __future__ import annotations

from queryguard.models.finding import Finding

__all__ = ["MODEL", "request_findings"]

MODEL = "claude-opus-5"


def request_findings(system_prompt: str, user_content: str) -> list[Finding]:
    """Ask Claude for findings, returning them already validated.

    Callers get :class:`Finding` objects or an exception — never half-parsed
    model output. Note that findings are *claims*: the caller is responsible for
    verifying what is checkable and labelling ``confidence`` on what is not.
    """
    raise NotImplementedError("claude.request_findings is not implemented yet")
