from __future__ import annotations

import json
import logging
from typing import Any

_logger = logging.getLogger("darwinspot.audit")
_SENSITIVE_PARTS = ("token", "secret", "password", "credential", "authorization", "key")


def log_event(event_code: str, **metadata: Any) -> None:
    safe_metadata = {
        key: "[redacted]" if any(part in key.lower() for part in _SENSITIVE_PARTS) else value
        for key, value in metadata.items()
    }
    _logger.info(
        json.dumps(
            {"component": "darwinspot", "eventCode": event_code, "metadata": safe_metadata},
            default=str,
            sort_keys=True,
        )
    )
