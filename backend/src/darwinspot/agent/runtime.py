from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any, TypeVar

from openai import AsyncOpenAI
from pydantic import BaseModel, ValidationError

from darwinspot.agent.prompts import PAIR_SELECTION_PROMPT, SYSTEM_PROMPT
from darwinspot.agent.schemas import AgentDecision, PairSelection
from darwinspot.config import validate_openai_base_url

ModelT = TypeVar("ModelT", bound=BaseModel)

class ModelResponseError(ValueError):
    """Raised when the model response cannot be parsed or validated."""


_JSON_FENCE_PATTERN = re.compile(
    r"```json[ \t]*\r?\n(?P<content>.*?)\r?\n```", re.IGNORECASE | re.DOTALL
)
_PAIR_SELECTION_SCHEMA = '{"pair":"BTCUSDT"}'
_AGENT_DECISION_SCHEMA = (
    '{"action":"BUY | SELL | HOLD","pair":"BTCUSDT | null",'
    '"order_type":"MARKET | LIMIT | null","side":"BUY | SELL | null",'
    '"quantity":"positive decimal | null","price":"positive decimal | null",'
    '"time_in_force":"GTC | null","rationale":"string",'
    '"evidence":["one or more concise evidence statements"],'
    '"confidence":"decimal 0..1","supporting_factors":["1..6 strings"],'
    '"risk_factors":["1..6 strings"],"mandate_version":"string | null"}'
)


def _normalize_json_content(content: str) -> str:
    normalized = content.strip()
    match = _JSON_FENCE_PATTERN.fullmatch(normalized)
    return match.group("content").strip() if match else normalized


def _response_content(response: Any, operation: str) -> str:
    choices: list[object] | None = getattr(response, "choices", None)
    if not isinstance(choices, list) or not choices:
        raise ModelResponseError(f"model returned an invalid {operation} response")
    choice = choices[0]
    message = getattr(choice, "message", None)
    message_object: object = message
    content = getattr(message_object, "content", None)
    if not isinstance(content, str) or not content.strip():
        raise ModelResponseError(f"model returned an empty or invalid {operation} response")
    return _normalize_json_content(content)


async def _validated_completion(  # noqa: UP047
    client: Any,
    model: str,
    *,
    operation: str,
    system_prompt: str,
    evidence: dict[str, Any],
    schema: str,
    validator: Callable[[str], ModelT],
) -> ModelT:
    base_messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": json.dumps(evidence, default=str)},
    ]
    messages = base_messages
    for attempt in range(2):
        response = await client.chat.completions.create(
            model=model,
            messages=messages,
            response_format={"type": "json_object"},
        )
        content = _response_content(response, operation)
        try:
            return validator(content)
        except ValidationError as exc:
            if attempt == 1:
                raise ModelResponseError(
                    f"model returned invalid {operation} JSON or schema"
                ) from exc
            messages = [
                *base_messages,
                {
                    "role": "user",
                    "content": (
                        f"Your previous {operation} response failed DARWIN's exact JSON schema. "
                        "Return one corrected JSON object only, with no explanation, extra keys, "
                        "or hidden reasoning. The exact allowed structure is: "
                        f"{schema}"
                    ),
                },
            ]
    raise AssertionError("schema validation loop must return or raise")


class AgentRuntime:
    def __init__(self, api_key: str, model: str, base_url: str | None = None) -> None:
        if not api_key.strip():
            raise ValueError("OPENAI_API_KEY must not be empty")
        if not model.strip():
            raise ValueError("OPENAI_MODEL must not be empty")
        validate_openai_base_url(base_url)
        self.client = (
            AsyncOpenAI(api_key=api_key, base_url=base_url)
            if base_url is not None
            else AsyncOpenAI(api_key=api_key)
        )
        self.model = model

    async def choose_pair(self, evidence: dict[str, Any]) -> PairSelection:
        return await _validated_completion(
            self.client,
            self.model,
            operation="pair selection",
            system_prompt=PAIR_SELECTION_PROMPT,
            evidence=evidence,
            schema=_PAIR_SELECTION_SCHEMA,
            validator=PairSelection.model_validate_json,
        )

    async def decide(self, evidence: dict[str, Any]) -> AgentDecision:
        return await _validated_completion(
            self.client,
            self.model,
            operation="decision",
            system_prompt=SYSTEM_PROMPT,
            evidence=evidence,
            schema=_AGENT_DECISION_SCHEMA,
            validator=AgentDecision.model_validate_json,
        )
