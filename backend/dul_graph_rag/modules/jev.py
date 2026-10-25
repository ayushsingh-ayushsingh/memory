from __future__ import annotations

import asyncio
import time
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
)

from .settings import S, Settings, get_settings


# %% Cell 15 — JEV CLIENT: batched Choice questions, budgeted, accounted
#
# Jev is the **only** component that maps free text onto ontology terms. This
# client exists to make that cheap and observable:
#
# * every question is a `Choice` with at most JEV_MAX_CHOICES options (10);
# * many questions travel in **one** request — the service evaluates them in
#   parallel, so the number of round trips stays minimal;
# * requests, questions and tokens are accounted for, so the notebook can
#   show what a mapping actually cost;
# * a failing request never sinks the batch: the error is recorded and the
#   remaining questions are answered.


class JevAnswer(BaseModel):
    """One answered Choice question."""

    model_config = ConfigDict(extra="forbid")

    question_id: str
    choice: str
    confidence: float
    probabilities: dict[str, float] = Field(default_factory=dict)


class JevUsage(BaseModel):
    """Token accounting for the whole run."""

    model_config = ConfigDict(extra="forbid")

    calls: int = 0
    questions: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    elapsed_s: float = 0.0
    errors: list[str] = Field(default_factory=list)

    def merge(self, other: "JevUsage") -> None:
        self.calls += other.calls
        self.questions += other.questions
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.elapsed_s += other.elapsed_s
        self.errors.extend(other.errors)

    def rows(self) -> list[dict[str, Any]]:
        """Notebook-ready one-row-per-counter view."""
        return [
            {"metric": "requests", "value": self.calls},
            {"metric": "questions", "value": self.questions},
            {"metric": "input tokens", "value": f"{self.input_tokens:,}"},
            {"metric": "output tokens", "value": f"{self.output_tokens:,}"},
            {"metric": "elapsed", "value": f"{self.elapsed_s:.1f}s"},
            {"metric": "errors", "value": "; ".join(self.errors) or "none"},
        ]


class JevCallResult(BaseModel):
    """Answers of one batched request."""

    model_config = ConfigDict(extra="forbid")

    answers: dict[str, JevAnswer] = Field(default_factory=dict)
    usage: JevUsage = Field(default_factory=JevUsage)


def build_choice(
    instructions: str,
    options: dict[str, str],
    max_choices: int | None = None,
) -> Any:
    """Build a `Choice` question, enforcing the option ceiling.

    `options` maps the option *key* (the value Jev returns) to its
    *description* (what the model reads to disambiguate). Keys must be
    unique and stable — they are how an answer is mapped back onto the
    ontology term.
    """
    from typesafe_sdk import Choice

    limit = max_choices if max_choices is not None else S.jev_max_choices
    if not options:
        raise ValueError("a Choice question needs at least one option")
    if len(options) > limit:
        raise ValueError(
            f"Choice question with {len(options)} options exceeds the limit of "
            f"{limit} (Jev accepts at most {limit} choices per question)"
        )
    return Choice(instructions=instructions, criteria=dict(options))


class JevClient:
    """Async wrapper around `AsyncTypeSafeClient` with batching + accounting."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.usage = JevUsage()
        self._client: Any = None

    # %% Lifecycle
    def _api_key(self) -> str:
        key = (self.settings.typesafe_api_key or "").strip()
        if not key:
            raise RuntimeError(
                "TYPESAFE_API_KEY missing: add it to the project .env file "
                "(Jev is required for every ontology mapping)"
            )
        return key

    async def __aenter__(self) -> "JevClient":
        from typesafe_sdk import AsyncTypeSafeClient, RetryPolicy

        self._client = AsyncTypeSafeClient(
            model=self.settings.jev_model,
            api_key=self._api_key(),
            retry=RetryPolicy(
                max_retries=self.settings.jev_api_retries,
                timeout=self.settings.jev_timeout_s,
            ),
            timeout=self.settings.jev_timeout_s,
        )
        await self._client.__aenter__()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        if self._client is not None:
            await self._client.__aexit__(*exc)
            self._client = None

    # %% Request
    async def ask(self, questions: dict[str, Any], state: str) -> JevCallResult:
        """Ask a batch of questions in one request."""
        if self._client is None:
            raise RuntimeError("JevClient must be used as an async context manager")
        result = JevCallResult()
        if not questions:
            return result
        started = time.perf_counter()
        try:
            response = await self._client.system_one(state=state, questions=questions)
        except Exception as exc:  # noqa: BLE001 — one failed batch must not sink the run
            result.usage.calls = 1
            result.usage.questions = len(questions)
            result.usage.elapsed_s = time.perf_counter() - started
            result.usage.errors.append(f"{type(exc).__name__}: {exc}")
            self.usage.merge(result.usage)
            return result
        for question_id, answer in response.choices.items():
            result.answers[question_id] = JevAnswer(
                question_id=question_id,
                choice=answer.choice,
                confidence=float(answer.confidence),
                probabilities=dict(answer.probabilities),
            )
        result.usage.calls = 1
        result.usage.questions = len(questions)
        result.usage.input_tokens = int(response.usage.input_tokens or 0)
        result.usage.output_tokens = int(response.usage.output_tokens or 0)
        result.usage.elapsed_s = time.perf_counter() - started
        self.usage.merge(result.usage)
        return result

    async def ask_batched(
        self, questions: dict[str, Any], state: str
    ) -> dict[str, JevAnswer]:
        """Ask many questions, split into budgeted requests, run concurrently.

        The service evaluates the questions of one request in parallel, so a
        single request is the cheapest option; the budget only exists to keep
        the request payload sane when there are hundreds of questions.
        """
        budget = max(1, self.settings.jev_max_questions_per_call)
        items = list(questions.items())
        chunks = [items[i : i + budget] for i in range(0, len(items), budget)]
        semaphore = asyncio.Semaphore(max(1, self.settings.jev_max_concurrency))

        async def worker(chunk: list[tuple[str, Any]]) -> JevCallResult:
            async with semaphore:
                return await self.ask(dict(chunk), state)

        results = await asyncio.gather(*(worker(chunk) for chunk in chunks))
        answers: dict[str, JevAnswer] = {}
        for result in results:
            answers.update(result.answers)
        return answers
