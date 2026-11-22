"""Browser profiles for the dual load (cloaking detection)."""

from __future__ import annotations

from typing import Any

CHROME = "Chrome/141.0.0.0"
PROFILES: dict[str, dict[str, Any]] = {
    "mobile_ar": {
        "user_agent": (
            "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) "
            f"{CHROME} Mobile Safari/537.36"
        ),
        "viewport": {"width": 412, "height": 915},
        "is_mobile": True,
        "has_touch": True,
        "device_scale_factor": 1,
        "locale": "ar-AE",
        "timezone_id": "Asia/Dubai",
    },
    "desktop_en": {
        "user_agent": (
            f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) {CHROME} Safari/537.36"
        ),
        "viewport": {"width": 1366, "height": 768},
        "is_mobile": False,
        "has_touch": False,
        "device_scale_factor": 1,
        "locale": "en-US",
        "timezone_id": "Asia/Dubai",
    },
}
