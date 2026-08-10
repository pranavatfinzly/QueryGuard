"""Configuration — the only module in QueryGuard that reads the environment.

Every secret and every environment-dependent value enters the process here and
nowhere else. That is a testable claim, not a convention:
``test_config.py::test_config_is_the_only_module_that_reads_the_environment``
walks the source tree and fails if any other module touches ``os.environ``.

Why one module: a token read at its point of use is a token with no single place
to audit, no single place to redact, and no way to answer "what does this process
need in order to run?" without reading everything. Centralizing it also means the
masking below is the *only* thing that has to be right for a secret to stay out
of a log line.

Secrets are :class:`~pydantic.SecretStr`, so the value is unreachable without an
explicit ``.get_secret_value()``. Leaking one becomes something you have to type
on purpose rather than something you get by interpolating a variable.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from pydantic import SecretStr
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

__all__ = [
    "MissingConfiguration",
    "Settings",
    "get_settings",
    "override_settings",
    "reset_settings_cache",
    "validate_required",
]

#: Env var that marks a run as not needing real configuration. Set to ``test`` to
#: import QueryGuard without a token — for a test run, a lint pass, or ``--help``.
ENVIRONMENT_VARIABLE = "QUERYGUARD_ENV"

#: Value of :data:`ENVIRONMENT_VARIABLE` that disables the import-time check.
TEST_ENVIRONMENT = "test"

#: Fields that must be set for QueryGuard to do its job, and what each is for.
#: Ordered, because the startup error lists them in this order.
REQUIRED_FIELDS: tuple[tuple[str, str, str], ...] = (
    (
        "github_token",
        "GITHUB_TOKEN",
        "read pull requests and post the review comment",
    ),
)

#: Set while a hermetic :class:`Settings` is being built. A ContextVar rather than
#: a module flag so a test isolating its own settings cannot make a concurrent
#: real load silently ignore the environment.
_ISOLATED: ContextVar[bool] = ContextVar("queryguard_settings_isolated", default=False)

_cached: Settings | None = None
_override: Settings | None = None


class MissingConfiguration(RuntimeError):
    """Raised when a value QueryGuard cannot run without is absent."""


class Settings(BaseSettings):
    """Everything QueryGuard reads from its environment.

    Frozen, like the stage contracts in :mod:`queryguard.models`: configuration
    that can be edited at runtime is configuration that cannot be reasoned about
    from the startup log.

    Fields are populated from environment variables of the same name, upper-cased
    (``github_token`` from ``GITHUB_TOKEN``), then from a ``.env`` file at the
    working directory. Unrecognized environment variables are ignored — this
    process does not own the environment it runs in.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
        case_sensitive=False,
    )

    github_token: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Choose where values come from, so isolation is a property of the class.

        Under :meth:`isolated` only explicitly passed values are used. Without
        this, ``Settings(github_token="fake")`` still reads the *real* environment
        for every field it was not given — so a test overriding one value would
        silently inherit whatever the developer happened to have exported, and
        pass or fail depending on whose machine it ran on.
        """
        if _ISOLATED.get():
            return (init_settings,)
        return (init_settings, env_settings, dotenv_settings, file_secret_settings)

    @classmethod
    def isolated(cls, **values: Any) -> Settings:
        """Build settings from ``values`` alone, ignoring the environment entirely.

        The constructor tests should use. Anything not passed takes its declared
        default rather than whatever is exported in the shell.
        """
        token = _ISOLATED.set(True)
        try:
            return cls(**values)
        finally:
            _ISOLATED.reset(token)

    @classmethod
    def from_mapping(cls, environ: Mapping[str, str]) -> Settings:
        """Build settings from an explicit environment-shaped mapping.

        For tests that want to exercise the environment-variable *names* —
        ``{"GITHUB_TOKEN": "..."}`` — without exporting anything real.
        """
        lowered = {key.lower(): value for key, value in environ.items()}
        return cls.isolated(**{name: lowered[name] for name in cls.model_fields if name in lowered})

    def require_github_token(self) -> str:
        """The GitHub token, or a clear failure naming what to set."""
        return self._require("github_token")

    def require_anthropic_api_key(self) -> str:
        """The Anthropic API key, or a clear failure naming what to set.

        Optional at startup and required at the point of use: the N+1 stage is the
        only thing that needs it, and a run that never reaches that stage should
        not be blocked on a key it will not use.
        """
        return self._require("anthropic_api_key")

    def _require(self, field: str) -> str:
        secret: SecretStr | None = getattr(self, field)
        if secret is None or not secret.get_secret_value():
            raise MissingConfiguration(_missing_message([field]))
        return secret.get_secret_value()

    def missing_required(self) -> tuple[str, ...]:
        """Names of the required fields this configuration does not carry."""
        return tuple(
            field for field, _, _ in REQUIRED_FIELDS if not _is_present(getattr(self, field, None))
        )

    def __repr__(self) -> str:
        """A representation safe to log, verbatim, at any level.

        Secrets are reduced to whether they are set. That distinction is the part
        worth logging — "the token is missing" is the answer to most startup
        questions — and it reveals nothing. No prefix, no suffix, no length: every
        character of a token that reaches a log is a character an attacker does
        not have to guess, and a log line outlives the process that wrote it.
        """
        rendered = ", ".join(
            f"{name}={_display(getattr(self, name, None))}" for name in type(self).model_fields
        )
        return f"{type(self).__name__}({rendered})"

    __str__ = __repr__


def _display(value: object) -> str:
    """Render one field for :meth:`Settings.__repr__`, masking secrets."""
    if isinstance(value, SecretStr):
        return "'<set>'" if value.get_secret_value() else "'<empty>'"
    if value is None:
        return "<unset>"
    return repr(value)


def _is_present(value: object) -> bool:
    """Whether a field carries a usable value rather than being absent or blank."""
    if value is None:
        return False
    if isinstance(value, SecretStr):
        return bool(value.get_secret_value())
    return True


def _missing_message(fields: list[str] | tuple[str, ...]) -> str:
    """A startup error that says what is missing, why, and how to supply it."""
    described = {field: (variable, purpose) for field, variable, purpose in REQUIRED_FIELDS}

    lines = ["QueryGuard is missing required configuration:", ""]
    for field in fields:
        variable, purpose = described.get(field, (field.upper(), "run this stage"))
        lines.append(f"  {variable} — needed to {purpose}")

    lines += [
        "",
        "Set it in the environment, or in a .env file beside the repository root:",
        "",
        *[f"    {described.get(field, (field.upper(), ''))[0]}=..." for field in fields],
        "",
        f"To import QueryGuard without configuration, set {ENVIRONMENT_VARIABLE}="
        f"{TEST_ENVIRONMENT}.",
    ]
    return "\n".join(lines)


def get_settings() -> Settings:
    """The process-wide settings, loaded once.

    Cached rather than re-read, so one run cannot see two different values for
    the same variable. Prefer this over constructing :class:`Settings` directly;
    a caller that builds its own has stopped sharing the process's configuration.
    """
    global _cached

    if _override is not None:
        return _override
    if _cached is None:
        _cached = Settings()
    return _cached


def reset_settings_cache() -> None:
    """Drop the cached settings so the next read re-loads the environment."""
    global _cached
    _cached = None


@contextmanager
def override_settings(**values: Any) -> Iterator[Settings]:
    """Replace the process settings for the duration of a block.

    Hermetic: only the values passed here are used, and the real environment is
    not consulted for the rest. Restores whatever was in place on exit, including
    a previous override, so nesting works.

        with override_settings(github_token="test-token") as settings:
            ...
    """
    global _override

    previous = _override
    _override = Settings.isolated(**values)
    try:
        yield _override
    finally:
        _override = previous


def validate_required(settings: Settings | None = None) -> Settings:
    """Check that everything QueryGuard cannot run without is present.

    The explicit form of the import-time check below, for a caller that wants to
    decide *when* configuration is verified — an application startup hook, a CLI
    entry point — rather than inheriting the moment of import.
    """
    resolved = settings if settings is not None else get_settings()
    missing = resolved.missing_required()
    if missing:
        raise MissingConfiguration(_missing_message(missing))
    return resolved


def _running_under_test() -> bool:
    """Whether this process is a test run, a lint pass, or otherwise unconfigured.

    ``pytest in sys.modules`` rather than ``PYTEST_CURRENT_TEST``, because the
    latter is only set once a test is *executing* — import happens during
    collection, before any of them are.
    """
    if os.environ.get(ENVIRONMENT_VARIABLE, "").strip().lower() == TEST_ENVIRONMENT:
        return True
    return "pytest" in sys.modules or "unittest" in sys.modules


def _validate_at_import() -> None:
    """Fail fast at import when a real run is missing its configuration.

    Deliberately import-time, so a misconfigured deployment dies at startup
    rather than after cloning a reference database and analyzing a diff. It is
    skipped for test and tooling runs; without that, importing anything under
    ``queryguard`` would require a GitHub token, and ``pytest`` could not even
    collect.

    A caveat worth knowing: because this raises during import, the traceback
    points at an ``import`` line rather than at whatever needed the value. That
    is the cost of failing early, and :func:`validate_required` is the opt-in
    alternative for callers who would rather choose the moment themselves.
    """
    if _running_under_test():
        return
    validate_required()


_validate_at_import()
