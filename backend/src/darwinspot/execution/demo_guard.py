from __future__ import annotations

from darwinspot.config import get_settings


class DemoFinancialWriteBlocked(RuntimeError):
    """Raised when a financial mutation is attempted in DEMO_MODE."""


def ensure_financial_write_allowed() -> None:
    if get_settings().demo_mode:
        raise DemoFinancialWriteBlocked("financial writes are disabled while DEMO_MODE=true")
