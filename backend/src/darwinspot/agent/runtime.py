from __future__ import annotations

import json
from typing import Any

from openai import AsyncOpenAI

from darwinspot.agent.prompts import PAIR_SELECTION_PROMPT, SYSTEM_PROMPT
from darwinspot.agent.schemas import AgentDecision, PairSelection


class AgentRuntime:
    def __init__(self, api_key: str, model: str) -> None:
        self.client = AsyncOpenAI(api_key=api_key)
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
        content = response.choices[0].message.content
        if not content:
            raise ValueError("model returned an empty pair selection")
        return PairSelection.model_validate_json(content)

    async def decide(self, evidence: dict[str, Any]) -> AgentDecision:
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(evidence, default=str)},
            ],
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content
        if not content:
            raise ValueError("model returned an empty decision")
        return AgentDecision.model_validate_json(content)
