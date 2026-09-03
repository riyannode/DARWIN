from __future__ import annotations

import json
from typing import Any

from openai import AsyncOpenAI
from pydantic import ValidationError

from darwinspot.agent.prompts import PAIR_SELECTION_PROMPT, SYSTEM_PROMPT
from darwinspot.agent.schemas import AgentDecision, PairSelection
from darwinspot.config import validate_openai_base_url


class ModelResponseError(ValueError):
    """Raised when the model response cannot be parsed or validated."""



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
    return content


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
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": PAIR_SELECTION_PROMPT},
                {"role": "user", "content": json.dumps(evidence, default=str)},
            ],
            response_format={"type": "json_object"},
        )
        content = _response_content(response, "pair selection")
        try:
            return PairSelection.model_validate_json(content)
        except ValidationError as exc:
            raise ModelResponseError(
                "model returned invalid pair selection JSON or schema"
            ) from exc

    async def decide(self, evidence: dict[str, Any]) -> AgentDecision:
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(evidence, default=str)},
            ],
            response_format={"type": "json_object"},
        )
        content = _response_content(response, "decision")
        try:
            return AgentDecision.model_validate_json(content)
        except ValidationError as exc:
            raise ModelResponseError("model returned invalid decision JSON or schema") from exc
