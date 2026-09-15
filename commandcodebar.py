#!/usr/bin/env python3
"""Waybar module for Command Code usage — fetches data directly from the Command Code API.

Mirrors codexbar.py: two block bars (5hr, weekly) with independent coloring.
5hr bar: colored by remaining % of the window cap.
Weekly bar: colored independently by comparing budget used% vs time left%
through the week — green while used% stays at or below the time left, yellow
while behind by up to 15 points, red further behind (or nearly exhausted).

Command Code paces included monthly credits with rolling 5-hour and weekly
windows (https://commandcode.ai/docs/resources/usage-limits). Each window
opens on the first request and resets a fixed time later, so elapsed time is
derived from the window's reported reset timestamp.

Reads the API key from the COMMAND_CODE_API_KEY environment variable; waybar
must be started in a session that has it (see the README's environment.d note).
"""

import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from html import escape
from typing import Any

API_BASE_URL = "https://api.commandcode.ai"
CREDITS_URL = f"{API_BASE_URL}/alpha/billing/credits"
SUBSCRIPTION_URL = f"{API_BASE_URL}/alpha/billing/subscriptions"
API_KEY_ENV_VAR = "COMMAND_CODE_API_KEY"
USER_AGENT = "commandcodebar/1.0"
TIMEOUT_SECONDS = 10
AUTH_REJECTED = "API key rejected"

FIVE_HOUR_SECONDS = 5 * 3600
WEEKLY_SECONDS = 7 * 86400

GREEN = "#089981"
YELLOW = "#f9e2af"
RED = "#f23645"
GRAY = "#666666"

# Monthly credit allowance per plan, mirroring the CLI's own plan table. Only
# used for the single-bar fallback on plans that report no rolling windows.
PLAN_ALLOWANCE_USD = {
    "individual-go": 10.0,
    "individual-goat": 70.0,
    "individual-pro": 30.0,
    "individual-pro-v1": 80.0,
    "individual-provider": 15.0,
    "individual-max": 150.0,
    "individual-ultra": 300.0,
    "teams-pro": 40.0,
}

PLAN_DISPLAY_NAMES = {
    "individual-go": "Go",
    "individual-goat": "GOAT",
    "individual-pro": "Pro",
    "individual-pro-v1": "Pro",
    "individual-provider": "Provider",
    "individual-max": "Max",
    "individual-ultra": "Ultra",
    "teams-pro": "Teams Pro",
}

# Longest key first, so a suffixed id still resolves (mirrors the CLI, which
# matches with startsWith over keys sorted by length).
_PLAN_KEYS_BY_LENGTH = tuple(sorted(PLAN_ALLOWANCE_USD, key=len, reverse=True))


def load_api_key() -> str | None:
    """API key from the COMMAND_CODE_API_KEY environment variable."""
    key = os.environ.get(API_KEY_ENV_VAR, "").strip()
    return key or None


def fetch_json(url: str, api_key: str) -> tuple[dict[str, Any] | None, str | None]:
    """GET a JSON endpoint with bearer auth. Returns (payload, error message)."""
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            body = json.loads(response.read().decode())
    except urllib.error.HTTPError as error:
        if error.code in (401, 403):
            return None, AUTH_REJECTED
        return None, f"HTTP {error.code}"
    except urllib.error.URLError:
        return None, "network error"
    except json.JSONDecodeError:
        return None, "bad JSON"
    except OSError:
        return None, "connection failed"

    if not isinstance(body, dict):
        return None, "unexpected response shape"
    return body, None


def as_float(value: Any, default: float = 0.0) -> float:
    """Coerce a JSON number to float, ignoring bools and non-numerics."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return float(value)


def make_bar(percentage: float, width: int = 8) -> str:
    """Simple filled/empty block bar."""
    filled = round((max(0.0, min(100.0, percentage)) / 100) * width)
    return "█" * filled + "░" * (width - filled)


def color_remaining(remaining_pct: float) -> str:
    """Color for a simple remaining-% threshold."""
    if remaining_pct >= 60:
        return GREEN
    if remaining_pct >= 30:
        return YELLOW
    return RED


def color_weekly_scaled(used_pct: float, elapsed_pct: float) -> str:
    """Color the weekly bar by comparing budget used vs time left.

    `margin = time_left - used_pct`:
      positive -> more time left in the window than budget consumed (ahead)
      zero     -> exactly on pace
      negative -> more budget consumed than time left (behind schedule)
    """
    remaining = 100 - used_pct

    # Absolute exhaustion guard — red regardless of schedule
    if remaining <= 10:
        return RED

    time_left = 100 - elapsed_pct
    margin = time_left - used_pct

    if margin >= 0:
        return GREEN  # ahead of, or exactly on, schedule
    if margin >= -15:
        return YELLOW  # behind by up to 15 points
    return RED  # well behind schedule


def compute_elapsed_pct(resets_at: float, window_seconds: int) -> float:
    """How much of the current window has elapsed, as a percentage (0-100)."""
    if window_seconds <= 0 or resets_at <= 0:
        return 0.0

    now = datetime.now(timezone.utc).timestamp()
    window_start = resets_at - window_seconds
    total = resets_at - window_start

    if total <= 0:
        return 0.0

    return max(0.0, min(100.0, ((now - window_start) / total) * 100))


def human_until(ts_unix: float) -> str:
    """Human time until a Unix timestamp, e.g. 'in 4h', 'in 6d 23h'."""
    if ts_unix <= 0:
        return "unknown"
    diff = int(ts_unix - datetime.now(timezone.utc).timestamp())
    if diff <= 0:
        return "now"
    days = diff // 86400
    hours = (diff % 86400) // 3600
    if days > 0:
        return f"in {days}d {hours}h" if hours else f"in {days}d"
    return f"in {hours}h" if hours else "in <1h"


def human_days(seconds: float) -> str:
    """Human whole days from a duration in seconds, e.g. 'in 30d'."""
    days = int(seconds // 86400)
    return f"in {days}d" if days > 0 else "in <1d"


def parse_window(window: Any, window_seconds: int) -> dict[str, Any] | None:
    """Normalize one rolling window into percentages, balance and reset time."""
    if not isinstance(window, dict):
        return None

    cap = as_float(window.get("cap"))
    if cap <= 0:
        return None

    used = as_float(window.get("used"))
    used_pct = (used / cap) * 100
    resets_at = as_float(window.get("resetAt")) / 1000

    return {
        "used": used,
        "cap": cap,
        "used_pct": used_pct,
        "remaining_pct": max(0.0, min(100.0, 100 - used_pct)),
        "elapsed_pct": compute_elapsed_pct(resets_at, window_seconds),
        "resets_at": resets_at,
    }


def window_line(name: str, window_label: str, view: dict[str, Any]) -> str:
    """Tooltip line: usage % remaining next to the matching time % left."""
    reset_desc = human_until(view["resets_at"])
    remaining_pct = view["remaining_pct"]
    if remaining_pct <= 0:
        return f"{name}: 0% remaining — resets {reset_desc}"

    time_left = 100 - view["elapsed_pct"]
    return (
        f"{name}: {remaining_pct:.0f}% remaining "
        f"({time_left:.0f}% of {window_label} left) — resets {reset_desc}"
    )


def resolve_plan(plan_id: Any) -> tuple[str | None, float | None]:
    """(display name, monthly allowance) for a plan id, longest prefix first."""
    if not isinstance(plan_id, str) or not plan_id:
        return None, None

    normalized = plan_id.lower().replace("_", "-")
    for key in _PLAN_KEYS_BY_LENGTH:
        if normalized.startswith(key):
            return PLAN_DISPLAY_NAMES.get(key, key), PLAN_ALLOWANCE_USD[key]

    return plan_id, None


def credits_lines(credits: dict[str, Any], allowance: float | None) -> list[str]:
    """Tooltip lines for the monthly credit limit and any extra credits.

    `monthlyCredits` is what remains of the plan's monthly allowance, so the
    limit itself comes from the plan table; spent is the difference. Extra
    pay-as-you-go credits are never capped by the rolling windows, so they are
    reported separately.
    """
    monthly = as_float(credits.get("monthlyCredits"))
    purchased = as_float(credits.get("purchasedCredits"))
    free = as_float(credits.get("freeCredits"))

    if allowance:
        if monthly > allowance:
            # Bonus credits (e.g. promotional boosts) lift the balance above the
            # plan's own allowance; report the bonus instead of a bogus ratio.
            lines = [
                f"Monthly: {monthly:.2f} credits left "
                f"({allowance:.2f} plan + {monthly - allowance:.2f} bonus)"
            ]
        else:
            pool = max(allowance, monthly) + purchased + free
            spent = max(0.0, allowance - monthly)
            used_pct = min(100.0, (spent / pool) * 100) if pool > 0 else 0.0
            lines = [
                f"Monthly: {monthly:.2f} of {allowance:.2f} credits left "
                f"({used_pct:.0f}% used)"
            ]
    else:
        lines = [f"Monthly: {monthly:.2f} credits left"]

    extras = [
        f"{value:.2f} {label}"
        for label, value in (("purchased", purchased), ("free", free))
        if value > 0
    ]
    if extras:
        lines.append(f"Extra credits: {', '.join(extras)}")
        lines.append(f"Total available: {monthly + purchased + free:.2f}")

    return lines


def plan_line(subscription: dict[str, Any] | None) -> tuple[str | None, float | None]:
    """Plan display name and monthly allowance from the subscription payload."""
    if not isinstance(subscription, dict):
        return None, None

    data = subscription.get("data")
    if not isinstance(data, dict):
        return None, None

    name, allowance = resolve_plan(data.get("planId"))
    if name is None:
        return None, None

    period_end = data.get("currentPeriodEnd")
    if isinstance(period_end, str):
        try:
            end = datetime.fromisoformat(period_end.replace("Z", "+00:00"))
        except ValueError:
            pass
        else:
            seconds_left = end.timestamp() - datetime.now(timezone.utc).timestamp()
            name = f"{name} — renews {human_days(seconds_left)}"

    return name, allowance


def render_unavailable(reason: str) -> None:
    """Empty bar plus the reason on hover when usage cannot be determined."""
    print(
        json.dumps(
            {
                "text": f'CmdCode(?) <span color="{GRAY}">????????</span>',
                "tooltip": escape(f"Command Code usage: unavailable ({reason})"),
                "class": "",
            }
        )
    )


def main() -> None:
    api_key = load_api_key()
    if api_key is None:
        render_unavailable(f"no API key in ${API_KEY_ENV_VAR}")
        return

    credits_response, credits_error = fetch_json(CREDITS_URL, api_key)
    if credits_response is None:
        render_unavailable(credits_error or "API request failed")
        return

    credits_raw = credits_response.get("credits")
    credits: dict[str, Any] = credits_raw if isinstance(credits_raw, dict) else {}

    limits_raw = credits_response.get("windowLimits")
    limits: dict[str, Any] = limits_raw if isinstance(limits_raw, dict) else {}

    five_hour = parse_window(limits.get("fiveHour"), FIVE_HOUR_SECONDS)
    weekly = parse_window(limits.get("weekly"), WEEKLY_SECONDS)

    subscription, _ = fetch_json(SUBSCRIPTION_URL, api_key)
    plan_name, allowance = plan_line(subscription)

    bars: list[str] = []
    tooltip_lines: list[str] = []

    if five_hour is not None:
        color = color_remaining(five_hour["remaining_pct"])
        bars.append(
            f'<span color="{color}">{make_bar(five_hour["remaining_pct"])}</span>'
        )
        tooltip_lines.append(window_line("5hr window", "5hr", five_hour))

    if weekly is not None:
        color = color_weekly_scaled(weekly["used_pct"], weekly["elapsed_pct"])
        bars.append(f'<span color="{color}">{make_bar(weekly["remaining_pct"])}</span>')
        tooltip_lines.append(window_line("Weekly", "week", weekly))

    # Module class tracks the most urgent window — 5hr when the API reports it,
    # otherwise the weekly window, exactly like codexbar.
    if five_hour is not None:
        urgency_pct: float | None = five_hour["remaining_pct"]
    elif weekly is not None:
        urgency_pct = weekly["remaining_pct"]
    else:
        urgency_pct = None

    text = "CmdCode"

    if bars:
        text = f"{text} {' '.join(bars)}"
    else:
        # No rolling windows on this plan (pay-as-you-go / Provider): fall back
        # to the monthly credit balance.
        total = (
            as_float(credits.get("monthlyCredits"))
            + as_float(credits.get("purchasedCredits"))
            + as_float(credits.get("freeCredits"))
        )
        if allowance:
            remaining_pct = max(0.0, min(100.0, (total / allowance) * 100))
            color = color_remaining(remaining_pct)
            text = f'{text} <span color="{color}">{make_bar(remaining_pct)}</span>'
            urgency_pct = remaining_pct
        else:
            text = f'{text} <span color="{GREEN}">${total:.2f}</span>'

    tooltip_lines.extend(credits_lines(credits, allowance))
    if plan_name:
        tooltip_lines.insert(0, f"Plan: {plan_name}")

    if urgency_pct is None:
        css_class = ""
    elif urgency_pct <= 5:
        css_class = "critical"
    elif urgency_pct <= 20:
        css_class = "warning"
    else:
        css_class = ""

    print(
        json.dumps(
            {
                "text": text,
                "tooltip": escape("Command Code usage\n" + "\n".join(tooltip_lines)),
                "class": css_class,
            }
        )
    )


if __name__ == "__main__":
    main()
