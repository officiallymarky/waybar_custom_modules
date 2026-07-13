#!/usr/bin/env python3
"""Waybar module for Codex usage — fetches data directly from the ChatGPT API.

Replaces the old approach that spawned `codex app-server` and used JSON-RPC.
Now does a single HTTPS GET to `https://chatgpt.com/backend-api/wham/usage`
using the access token from ~/.codex/auth.json.
5hr bar: colored by remaining % (shown only when the API reports a 5hr window).
Weekly bar: colored by scaled consumption — compares used% vs time-elapsed%
through the week so "ahead of schedule" and "behind schedule" differ even
at the same remaining %.

Shows available rate-limit resets in the label.
"""
import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone

API_URL = "https://chatgpt.com/backend-api/wham/usage"
AUTH_FILE = os.path.expanduser("~/.codex/auth.json")
USER_AGENT = "codexbar/2.0"


def load_auth() -> tuple[str, str] | None:
    """Read access_token and account_id from ~/.codex/auth.json."""
    try:
        with open(AUTH_FILE) as f:
            data = json.load(f)
        tok = data.get("tokens", {}).get("access_token") or data.get("OPENAI_API_KEY")
        acct = data.get("tokens", {}).get("account_id", "")
        if tok:
            return tok, acct
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        pass
    return None


def fetch_usage(access_token: str, account_id: str) -> dict | None:
    """GET the Codex usage endpoint. Returns parsed JSON or None."""
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    }
    if account_id:
        headers["ChatGPT-Account-Id"] = account_id

    req = urllib.request.Request(API_URL, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, OSError):
        return None


def make_bar(percentage: int, width: int = 8) -> str:
    """Simple filled/empty block bar."""
    filled = round((percentage / 100) * width)
    return "█" * filled + "░" * (width - filled)


def color_remaining(remaining_pct: float) -> str:
    """Color for a simple remaining-% threshold."""
    if remaining_pct >= 60:
        return "#089981"  # green
    if remaining_pct >= 30:
        return "#f9e2af"  # yellow
    return "#f23645"  # red


def color_weekly_scaled(used_pct: float, elapsed_pct: float) -> str:
    """Color the weekly bar by comparing consumption rate vs time elapsed.

    `adjusted = elapsed_pct - used_pct`:
      positive -> more time elapsed than budget used (ahead of schedule)
      negative -> more budget used than time elapsed (behind schedule)
    """
    remaining = 100 - used_pct

    # Absolute exhaustion guard — red regardless of schedule
    if remaining <= 10:
        return "#f23645"

    adjusted = elapsed_pct - used_pct

    if adjusted >= 15:
        return "#089981"  # comfortably ahead
    if adjusted >= -15:
        return "#f9e2af"  # on track
    return "#f23645"  # behind schedule


def compute_elapsed_pct(resets_at: int, window_seconds: int) -> float:
    """How much of the current window has elapsed, as a percentage (0-100)."""
    if window_seconds <= 0:
        return 0.0

    now = datetime.now(timezone.utc).timestamp()
    window_start = resets_at - window_seconds
    elapsed = now - window_start
    total = resets_at - window_start

    if total <= 0:
        return 0.0

    return max(0.0, min(100.0, (elapsed / total) * 100))


def human_until(ts_unix: int) -> str:
    """Human time until a Unix timestamp, e.g. 'in 4h', 'in 6d 23h'."""
    now = datetime.now(timezone.utc).timestamp()
    diff = int(ts_unix - now)
    if diff <= 0:
        return "now"
    days = diff // 86400
    hours = (diff % 86400) // 3600
    if days > 0:
        return f"in {days}d {hours}h" if hours else f"in {days}d"
    return f"in {hours}h" if hours else "in <1h"


def main():
    auth = load_auth()
    if auth is None:
        print(json.dumps({
            "text": "Codex(?) <span color=\"#666666\">????????</span>",
            "tooltip": "Codex usage: unavailable (no auth token in ~/.codex/auth.json)",
            "class": "",
        }))
        return

    access_token, account_id = auth
    data = fetch_usage(access_token, account_id)
    if data is None:
        print(json.dumps({
            "text": "Codex(?) <span color=\"#666666\">????????</span>",
            "tooltip": "Codex usage: unavailable (API request failed)",
            "class": "",
        }))
        return

    rl = data.get("rate_limit", {})
    primary_raw = rl.get("primary_window")
    secondary_raw = rl.get("secondary_window")

    # Detect whether primary is actually a 5hr window (limit_window_seconds ≈ 18000)
    # or was repurposed to a weekly window (as of Codex removing the 5hr window)
    primary_is_5hr = bool(
        primary_raw
        and isinstance(primary_raw, dict)
        and primary_raw.get("limit_window_seconds") == 18000
    )

    if primary_is_5hr:
        # Two bars: primary = 5hr, secondary = weekly
        primary_5hr = primary_raw
        weekly_raw = secondary_raw if isinstance(secondary_raw, dict) else {}
    else:
        # One bar: use the single window that exists (primary or secondary)
        primary_5hr = None
        weekly_raw = primary_raw if isinstance(primary_raw, dict) else (secondary_raw if isinstance(secondary_raw, dict) else {})

    weekly_used = weekly_raw.get("used_percent", 0)
    weekly_resets_at = weekly_raw.get("reset_at", 0)
    weekly_window_secs = weekly_raw.get("limit_window_seconds", 604800)

    weekly_elapsed_pct = compute_elapsed_pct(weekly_resets_at, weekly_window_secs)

    weekly_remaining = 100 - weekly_used
    weekly_color = color_remaining(weekly_remaining)
    weekly_bar = make_bar(weekly_remaining)
    weekly_desc = human_until(weekly_resets_at)

    reset_credits = data.get("rate_limit_reset_credits", {})
    reset_count = reset_credits.get("available_count") if reset_credits else None
    label = f"Codex({reset_count})" if reset_count is not None else "Codex(?)"

    if primary_5hr:
        primary_used = primary_5hr.get("used_percent", 0)
        primary_resets_at = primary_5hr.get("reset_at", 0)
        primary_window_secs = primary_5hr.get("limit_window_seconds", 18000)

        primary_remaining = 100 - primary_used
        primary_elapsed_pct = compute_elapsed_pct(primary_resets_at, primary_window_secs)
        primary_color = color_remaining(primary_remaining)
        primary_bar = make_bar(primary_remaining)
        primary_desc = human_until(primary_resets_at)

        # Module class based on primary (5hr is the urgent window)
        if primary_remaining <= 5:
            css_class = "critical"
        elif primary_remaining <= 20:
            css_class = "warning"
        else:
            css_class = ""

        primary_tooltip = (
            f"5hr window: {primary_remaining}% remaining "
            f"({primary_elapsed_pct:.0f}% of 5hr elapsed) — resets {primary_desc}"
        )

        if weekly_remaining < 0:
            secondary_tooltip = f"Weekly: exceeded by {-weekly_remaining}% — resets {weekly_desc}"
        else:
            secondary_tooltip = (
                f"Weekly: {weekly_remaining}% remaining "
                f"({weekly_elapsed_pct:.0f}% of week elapsed) — resets {weekly_desc}"
            )
        
        # weekly bar in two-bar mode uses rate-aware coloring
        weekly_color = color_weekly_scaled(weekly_used, weekly_elapsed_pct)

        tooltip = f"{primary_tooltip}\n{secondary_tooltip}"

        if reset_count is not None:
            tooltip += f"\nRate-limit resets: {reset_count} available"

        print(json.dumps({
            "text": f"{label} <span color=\"{primary_color}\">{primary_bar}</span>"
                    f" <span color=\"{weekly_color}\">{weekly_bar}</span>",
            "tooltip": tooltip,
            "class": css_class,
        }))
    else:
        # Single bar (weekly only)
        if weekly_remaining <= 5:
            css_class = "critical"
        elif weekly_remaining <= 20:
            css_class = "warning"
        else:
            css_class = ""

        if weekly_remaining < 0:
            tooltip = f"Weekly: exceeded by {-weekly_remaining}% — resets {weekly_desc}"
        else:
            tooltip = (
                f"Weekly: {weekly_remaining}% remaining "
                f"({weekly_elapsed_pct:.0f}% of week elapsed) — resets {weekly_desc}"
            )

        if reset_count is not None:
            tooltip += f"\nRate-limit resets: {reset_count} available"

        print(json.dumps({
            "text": f"{label} <span color=\"{weekly_color}\">{weekly_bar}</span>",
            "tooltip": tooltip,
            "class": css_class,
        }))


if __name__ == "__main__":
    main()
