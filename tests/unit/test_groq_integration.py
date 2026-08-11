"""GroqExplanationProvider against a fake Groq client — no network, ever.

Deliberately not a ``MagicMock``, for the same reason ``tests/conftest.py``'s
PyGithub stand-in isn't one: the point of these tests is that the provider reads
the shape the real ``groq`` SDK returns and handles the shape it raises, and a
mock agrees with whatever it is asked. ``FakeGroqClient`` implements exactly the
one call the provider makes (``chat.completions.create``) and nothing else.
"""

from __future__ import annotations

import json
from typing import cast

import httpx
from groq import APIConnectionError as GroqAPIConnectionError
from groq import APIStatusError as GroqAPIStatusError
from groq import APITimeoutError as GroqAPITimeoutError
from groq import AuthenticationError, Groq, RateLimitError
from groq import InternalServerError as GroqInternalServerError

from queryguard.config import DEFAULT_GROQ_MODEL, override_settings
from queryguard.integrations.groq import GroqExplanationProvider, create_default_llm_provider
from queryguard.models.finding import Evidence, Finding, Severity
from queryguard.models.java_structure import ArgumentDependency, IterationKind
from queryguard.models.nplusone import EvidenceTier, NPlusOneCandidate, NPlusOneKind
from queryguard.models.query import Provenance
from queryguard.pipeline.nplusone import render_candidate

_REQUEST = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")

VALID_RESPONSE = json.dumps(
    {
        "summary": "This loop issues one query per parent.",
        "why_it_matters": "Each iteration costs a database round trip.",
        "evidence_explanation": "The call sits inside a for-each loop that opens at line 19.",
        "recommendation": "Batch the lookup with a single query.",
    }
)


def candidate(**overrides: object) -> NPlusOneCandidate:
    base: dict[str, object] = {
        "kind": NPlusOneKind.REPOSITORY_CALL_IN_LOOP,
        "tier": EvidenceTier.MEDIUM_HIGH,
        "file": "src/main/java/com/example/service/ExampleService.java",
        "line": 20,
        "enclosing_type": "ExampleService",
        "enclosing_method": "run",
        "repository_type": "ThingRepository",
        "method_name": "findByParentId",
        "iteration_kind": IterationKind.ENHANCED_FOR,
        "iteration_line": 19,
        "element_identifier": "parent",
        "loop_depth": 1,
        "dependency": ArgumentDependency.LOOP_ELEMENT_ARGUMENT,
        "dependency_detail": "`parent` flows into the argument list",
    }
    return NPlusOneCandidate(**{**base, **overrides})  # type: ignore[arg-type]


def finding_for(candidate_: NPlusOneCandidate) -> Finding:
    return render_candidate(candidate_)


class _FakeMessage:
    def __init__(self, content: str | None) -> None:
        self.content = content


class _FakeChoice:
    def __init__(self, content: str | None) -> None:
        self.message = _FakeMessage(content)


class _FakeChatCompletion:
    def __init__(self, content: str | None) -> None:
        self.choices = [_FakeChoice(content)] if content is not None else []


class _FakeCompletions:
    """Stands in for ``client.chat.completions``.

    ``responses`` is consumed one per call, in order, so a test covering
    multiple candidates can hand back a different answer for each — or a
    single value is repeated for every call.
    """

    def __init__(
        self,
        *,
        content: str | list[str | None] | None = None,
        raises: BaseException | list[BaseException | None] | None = None,
    ) -> None:
        self._content = content
        self._raises = raises
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> _FakeChatCompletion:
        index = len(self.calls)
        self.calls.append(kwargs)

        error = self._raises[index] if isinstance(self._raises, list) else self._raises
        if error is not None:
            raise error

        content = self._content[index] if isinstance(self._content, list) else self._content
        return _FakeChatCompletion(content)


class _FakeChat:
    def __init__(self, completions: _FakeCompletions) -> None:
        self.completions = completions


class FakeGroqClient:
    """A ``groq.Groq`` stand-in implementing only ``chat.completions.create``."""

    def __init__(
        self,
        *,
        content: str | list[str | None] | None = None,
        raises: BaseException | list[BaseException | None] | None = None,
    ) -> None:
        self.completions = _FakeCompletions(content=content, raises=raises)
        self.chat = _FakeChat(self.completions)

    @property
    def client(self) -> Groq:
        """This fake, typed as the real client the provider's signature declares."""
        return cast(Groq, self)


def provider_with(
    client: FakeGroqClient, *, model: str = "llama-3.3-70b-versatile"
) -> GroqExplanationProvider:
    return GroqExplanationProvider(model=model, client=client.client)


# --- 1. Successful explanation ---------------------------------------------------


def test_a_successful_call_produces_an_explanation() -> None:
    fake = FakeGroqClient(content=VALID_RESPONSE)
    provider = provider_with(fake)
    thing = candidate()

    result = provider.explain_nplusone([(thing, finding_for(thing))])

    explanation = result[thing.identity]
    assert explanation.summary == "This loop issues one query per parent."
    assert "database round trip" in explanation.reasoning
    assert explanation.remediation == ("Batch the lookup with a single query.",)


def test_the_system_prompt_and_structured_output_are_sent() -> None:
    fake = FakeGroqClient(content=VALID_RESPONSE)
    provider = provider_with(fake, model="llama-3.3-70b-versatile")
    thing = candidate()

    provider.explain_nplusone([(thing, finding_for(thing))])

    (call,) = fake.completions.calls
    assert call["model"] == "llama-3.3-70b-versatile"
    messages = call["messages"]
    assert isinstance(messages, list)
    assert messages[0]["role"] == "system"
    assert "You are an explanation layer for QueryGuard" in str(messages[0]["content"])
    response_format = call["response_format"]
    assert isinstance(response_format, dict)
    assert response_format["type"] == "json_schema"


# --- 2. Missing GROQ_API_KEY -------------------------------------------------------


def test_the_default_provider_factory_returns_none_without_a_key() -> None:
    with override_settings(github_token="t"):
        assert create_default_llm_provider() is None


def test_the_default_provider_factory_constructs_a_real_provider_when_configured() -> None:
    with override_settings(github_token="t", groq_api_key="gsk_test_key"):
        provider = create_default_llm_provider()

    assert provider is not None
    assert provider._model == DEFAULT_GROQ_MODEL


def test_the_default_provider_factory_honours_a_configured_model() -> None:
    with override_settings(
        github_token="t", groq_api_key="gsk_test_key", groq_model="mixtral-8x7b-32768"
    ):
        provider = create_default_llm_provider()

    assert provider is not None
    assert provider._model == "mixtral-8x7b-32768"


# --- 3-6. Provider-side failures: never raise, always skip ------------------------


def test_an_authentication_failure_is_skipped_not_raised() -> None:
    error = AuthenticationError(
        "invalid api key", response=httpx.Response(401, request=_REQUEST), body=None
    )
    fake = FakeGroqClient(raises=error)
    provider = provider_with(fake)
    thing = candidate()

    result = provider.explain_nplusone([(thing, finding_for(thing))])

    assert result == {}


def test_a_rate_limit_is_skipped_not_raised() -> None:
    error = RateLimitError(
        "rate limited", response=httpx.Response(429, request=_REQUEST), body=None
    )
    fake = FakeGroqClient(raises=error)
    provider = provider_with(fake)
    thing = candidate()

    result = provider.explain_nplusone([(thing, finding_for(thing))])

    assert result == {}


def test_a_network_timeout_is_skipped_not_raised() -> None:
    error = GroqAPITimeoutError(request=_REQUEST)
    fake = FakeGroqClient(raises=error)
    provider = provider_with(fake)
    thing = candidate()

    result = provider.explain_nplusone([(thing, finding_for(thing))])

    assert result == {}


def test_a_network_connection_failure_is_skipped_not_raised() -> None:
    error = GroqAPIConnectionError(request=_REQUEST)
    fake = FakeGroqClient(raises=error)
    provider = provider_with(fake)
    thing = candidate()

    result = provider.explain_nplusone([(thing, finding_for(thing))])

    assert result == {}


def test_a_generic_api_failure_is_skipped_not_raised() -> None:
    error = GroqInternalServerError(
        "internal error", response=httpx.Response(500, request=_REQUEST), body=None
    )
    fake = FakeGroqClient(raises=error)
    provider = provider_with(fake)
    thing = candidate()

    result = provider.explain_nplusone([(thing, finding_for(thing))])

    assert result == {}


def test_a_bare_api_status_error_is_skipped_not_raised() -> None:
    error = GroqAPIStatusError(
        "unusual status", response=httpx.Response(418, request=_REQUEST), body=None
    )
    fake = FakeGroqClient(raises=error)
    provider = provider_with(fake)
    thing = candidate()

    result = provider.explain_nplusone([(thing, finding_for(thing))])

    assert result == {}


# --- 7. Malformed JSON -------------------------------------------------------------


def test_malformed_json_is_discarded_not_raised() -> None:
    fake = FakeGroqClient(content="{not valid json")
    provider = provider_with(fake)
    thing = candidate()

    result = provider.explain_nplusone([(thing, finding_for(thing))])

    assert result == {}


def test_an_empty_response_is_discarded_not_raised() -> None:
    fake = FakeGroqClient(content=None)
    provider = provider_with(fake)
    thing = candidate()

    result = provider.explain_nplusone([(thing, finding_for(thing))])

    assert result == {}


# --- 8. Invalid structured response -------------------------------------------------


def test_a_response_missing_the_required_summary_is_discarded() -> None:
    fake = FakeGroqClient(content=json.dumps({"why_it_matters": "it matters"}))
    provider = provider_with(fake)
    thing = candidate()

    result = provider.explain_nplusone([(thing, finding_for(thing))])

    assert result == {}


def test_a_response_with_a_blank_summary_is_discarded() -> None:
    fake = FakeGroqClient(content=json.dumps({"summary": "   "}))
    provider = provider_with(fake)
    thing = candidate()

    result = provider.explain_nplusone([(thing, finding_for(thing))])

    assert result == {}


def test_a_response_that_is_valid_json_but_not_an_object_is_discarded() -> None:
    fake = FakeGroqClient(content=json.dumps(["not", "an", "object"]))
    provider = provider_with(fake)
    thing = candidate()

    result = provider.explain_nplusone([(thing, finding_for(thing))])

    assert result == {}


# --- 18. Multiple N+1 findings ------------------------------------------------------


def test_multiple_candidates_each_get_an_independent_call_and_answer() -> None:
    first = candidate()
    second = candidate(
        file="src/main/java/com/example/service/OtherService.java",
        method_name="findByOtherId",
        repository_type="OtherRepository",
    )
    fake = FakeGroqClient(
        content=[
            json.dumps(
                {
                    "summary": "First explanation.",
                    "why_it_matters": "",
                    "evidence_explanation": "",
                    "recommendation": "",
                }
            ),
            json.dumps(
                {
                    "summary": "Second explanation.",
                    "why_it_matters": "",
                    "evidence_explanation": "",
                    "recommendation": "",
                }
            ),
        ]
    )
    provider = provider_with(fake)

    result = provider.explain_nplusone([(first, finding_for(first)), (second, finding_for(second))])

    assert result[first.identity].summary == "First explanation."
    assert result[second.identity].summary == "Second explanation."
    assert len(fake.completions.calls) == 2


def test_one_candidates_failure_does_not_cost_the_others_their_explanation() -> None:
    first = candidate()
    second = candidate(
        file="src/main/java/com/example/service/OtherService.java",
        method_name="findByOtherId",
        repository_type="OtherRepository",
    )
    error = AuthenticationError(
        "invalid api key", response=httpx.Response(401, request=_REQUEST), body=None
    )
    fake = FakeGroqClient(content=[None, VALID_RESPONSE], raises=[error, None])
    provider = provider_with(fake)

    result = provider.explain_nplusone([(first, finding_for(first)), (second, finding_for(second))])

    assert first.identity not in result
    assert second.identity in result


# --- No candidates: no call at all --------------------------------------------------


def test_no_candidates_means_no_call_at_all() -> None:
    fake = FakeGroqClient(content=VALID_RESPONSE)
    provider = provider_with(fake)

    result = provider.explain_nplusone([])

    assert result == {}
    assert fake.completions.calls == []


# --- The request payload carries the rendered finding too --------------------------


def test_the_request_includes_the_rendered_findings_severity_and_suggestions() -> None:
    from queryguard.integrations.llm import build_nplusone_request

    thing = candidate()
    payload = build_nplusone_request(thing, finding=finding_for(thing))

    finding_payload = payload["finding"]
    assert isinstance(finding_payload, dict)
    assert finding_payload["severity"] == Severity.HIGH.value
    assert finding_payload["rule_id"] == "nplusone-repository-call-in-loop"
    assert finding_payload["suggestions"]


def test_a_request_with_no_finding_omits_the_finding_key() -> None:
    from queryguard.integrations.llm import build_nplusone_request

    payload = build_nplusone_request(candidate())

    assert "finding" not in payload


def test_finding_evidence_and_provenance_are_untouched_by_the_provider_boundary() -> None:
    # The provider only ever sees a Finding to *read*; nothing about its own
    # request shape lets it write one back. This is a structural sanity check
    # that Evidence stays an ordinary immutable model, not a claim about Groq.
    thing = candidate()
    rendered = finding_for(thing)
    assert isinstance(rendered.evidence[0], Evidence)
    assert isinstance(rendered.provenance, Provenance)
