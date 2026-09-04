from __future__ import annotations

from darwinspot.config import get_settings


class FinancialWriteBlocked(RuntimeError):
    """Raised before any financial mutation when the global write gate is closed."""

    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = reason_code
        super().__init__(message)


class DemoFinancialWriteBlocked(FinancialWriteBlocked):
    """Raised when a financial mutation is attempted in DEMO_MODE."""

    def __init__(self, message: str | None = None) -> None:
        super().__init__(
            "DEMO_EXECUTION_BLOCKED",
            message or "financial writes are disabled while DEMO_MODE=true",
        )


def ensure_financial_write_allowed() -> None:
    settings = get_settings()
    if settings.demo_mode:
        raise DemoFinancialWriteBlocked()
    if not settings.financial_writes_enabled:
        raise FinancialWriteBlocked(
            "FINANCIAL_WRITES_DISABLED",
            "financial writes are disabled while FINANCIAL_WRITES_ENABLED=false",
        )
