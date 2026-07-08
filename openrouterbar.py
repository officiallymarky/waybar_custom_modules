#!/usr/bin/env python3
"""Waybar module for OpenRouter API-key usage."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from decimal import Decimal, InvalidOperation
from typing import Any

API_URL = "https://openrouter.ai/api/v1/key"
API_KEY_ENV_VAR = "OPENROUTER_API_KEY"
TIMEOUT_SECONDS = 10


def waybar_payload(text: str, tooltip: str, css_class: str = "") -> None:
    payload: dict[str, Any] = {
        "text": text,
        "tooltip": tooltip,
        "class": css_class,
    }
    print(json.dumps(payload))


def as_decimal(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    if value is None:
        return default
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return default


def format_usd(value: Decimal) -> str:
    if value >= Decimal("100"):
        return f"${value.quantize(Decimal('1')):,}"
    if value >= Decimal("10"):
        return f"${value.quantize(Decimal('0.1')):,}"
    return f"${value.quantize(Decimal('0.01')):,}"


def format_optional_usd(value: Any) -> str:
    if value is None:
        return "unlimited"
    return format_usd(as_decimal(value))


def request_key_usage(api_key: str) -> dict[str, Any]:
    request = urllib.request.Request(
        API_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "User-Agent": "waybar-openrouter/1.0",
        },
        method="GET",
    )

    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8"))


def key_data(response: dict[str, Any]) -> dict[str, Any]:
    data = response.get("data", {})
    return data if isinstance(data, dict) else {}


def css_class_for_usage(data: dict[str, Any]) -> str:
    monthly_usage = as_decimal(data.get("usage_monthly"))
    limit = data.get("limit")
    remaining = data.get("limit_remaining")

    if limit is None or remaining is None:
        return "idle" if monthly_usage == 0 else "good"

    limit_value = as_decimal(limit)
    remaining_value = as_decimal(remaining)
    if limit_value <= 0:
        return "critical"

    remaining_percent = (remaining_value / limit_value) * Decimal("100")
    if remaining_percent <= Decimal("10"):
        return "critical"
    if remaining_percent <= Decimal("25"):
        return "warning"
    return "idle" if monthly_usage == 0 else "good"


def render(response: dict[str, Any]) -> None:
    data = key_data(response)
    usage = as_decimal(data.get("usage"))
    usage_daily = as_decimal(data.get("usage_daily"))
    usage_weekly = as_decimal(data.get("usage_weekly"))
    usage_monthly = as_decimal(data.get("usage_monthly"))
    byok_usage_monthly = as_decimal(data.get("byok_usage_monthly"))

    text = f"OR {format_usd(usage_monthly)}"
    tooltip_lines = [
        "OpenRouter API key usage",
        f"Monthly usage: {format_usd(usage_monthly)}",
        f"Weekly usage: {format_usd(usage_weekly)}",
        f"Daily usage: {format_usd(usage_daily)}",
        f"All-time usage: {format_usd(usage)}",
        f"Limit: {format_optional_usd(data.get('limit'))}",
        f"Remaining: {format_optional_usd(data.get('limit_remaining'))}",
        f"Reset: {data.get('limit_reset') or 'never'}",
    ]
    if byok_usage_monthly:
        tooltip_lines.append(f"BYOK monthly usage: {format_usd(byok_usage_monthly)}")

    waybar_payload(text, "\n".join(tooltip_lines), css_class_for_usage(data))


def main() -> int:
    api_key = os.environ.get(API_KEY_ENV_VAR)
    if not api_key:
        waybar_payload(
            "OR no key",
            f"{API_KEY_ENV_VAR} is not set in Waybar's environment.",
            "critical",
        )
        return 0

    try:
        response = request_key_usage(api_key)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        waybar_payload("OR error", detail or f"OpenRouter HTTP {exc.code}", "critical")
        return 0
    except (OSError, TimeoutError, json.JSONDecodeError) as exc:
        waybar_payload("OR error", f"Failed to fetch OpenRouter key usage: {exc}", "critical")
        return 0

    render(response)
    return 0


if __name__ == "__main__":
    sys.exit(main())