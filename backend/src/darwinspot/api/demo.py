from __future__ import annotations

from fastapi import APIRouter, HTTPException

from darwinspot.config import get_settings
from darwinspot.demo.scenarios import build_demo_result, demo_summaries

router = APIRouter(prefix="/api/demo", tags=["demo"])


def _require_demo_mode() -> None:
    if not get_settings().demo_mode:
        raise HTTPException(status_code=404, detail="demo mode is disabled")


@router.get("")
def demo_overview() -> dict[str, object]:
    _require_demo_mode()
    return {
        "mode": "DEMO_MODE",
        "scenarios": demo_summaries(),
    }


@router.get("/scenarios")
def demo_scenarios() -> list[dict[str, object]]:
    _require_demo_mode()
    return demo_summaries()


@router.get("/scenarios/{scenario_id}")
def demo_scenario(scenario_id: str) -> dict[str, object]:
    _require_demo_mode()
    try:
        return build_demo_result(scenario_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="demo scenario not found") from exc
