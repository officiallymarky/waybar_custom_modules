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
import base64
import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone

API_URL = "https://chatgpt.com/backend-api/wham/usage"
AUTH_FILE = os.path.expanduser("~/.codex/auth.json")
USER_AGENT = "codexbar/2.0"
FORECAST_API_URL = "https://www.willcodexquotareset.com/api/forecast"


AUTH0_DOMAIN = "https://auth.openai.com"


def refresh_auth() -> tuple[str, str] | None:
    """Refresh the access_token via the Auth0 refresh_token endpoint.

    Updates ~/.codex/auth.json in place and returns (access_token, account_id).
    """
    try:
        with open(AUTH_FILE) as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None

    tokens = data.get("tokens", {})
    refresh_token = tokens.get("refresh_token")
    id_token = tokens.get("id_token")
    if not refresh_token or not id_token:
        return None

    # Decode client_id from the id_token JWT payload (no signature verification needed)
    try:
        id_parts = id_token.split(".")
        if len(id_parts) == 3:
            padded = id_parts[1] + "=" * (4 - len(id_parts[1]) % 4)
            id_payload = json.loads(base64.urlsafe_b64decode(padded))
            client_id = id_payload.get("aud", [])
            if isinstance(client_id, list):
                client_id = client_id[0] if client_id else ""
        else:
            return None
    except (ValueError, json.JSONDecodeError):
        return None

    refresh_payload = json.dumps({
        "grant_type": "refresh_token",
        "client_id": client_id,
        "refresh_token": refresh_token,
    }).encode()

    req = urllib.request.Request(
        f"{AUTH0_DOMAIN}/oauth/token",
        data=refresh_payload,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read().decode())
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, OSError):
        return None

    new_access_token = body.get("access_token")
    if not new_access_token:
        return None

    # Persist new tokens back to the auth file
    tokens["access_token"] = new_access_token
    if "id_token" in body:
        tokens["id_token"] = body["id_token"]
    if "refresh_token" in body:
        tokens["refresh_token"] = body["refresh_token"]
    tokens.setdefault("account_id", data.get("tokens", {}).get("account_id", ""))

    data["last_refresh"] = datetime.now(timezone.utc).isoformat()

    try:
        with open(AUTH_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except OSError:
        return None

    acct = tokens.get("account_id", "")
    return new_access_token, acct

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


def fetch_forecast() -> int | None:
    """GET the willcodexquotareset forecast API.

    Returns the forecast score (0-100) or None on failure.
    """
    req = urllib.request.Request(
        FORECAST_API_URL,
        headers={
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read().decode())
            score = body.get("forecast", {}).get("score")
            if isinstance(score, (int, float)):
                return int(score)
            return None
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


def color_forecast_score(score: int) -> str:
    """Color the willcodexquotareset forecast score by likelihood."""
    if score >= 50:
        return "#ff7800"  # orange — notable chance
    if score >= 25:
        return "#f9e2af"  # yellow — mild
    return "#666666"  # gray — quiet


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

    # Token may be expired — try refreshing and retry once
    if data is None:
        refreshed = refresh_auth()
        if refreshed:
            access_token, account_id = refreshed
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
    label = f"Codex ({reset_count})" if reset_count is not None else "Codex(?)"

    # Fetch willcodexquotareset forecast score
    forecast_score = fetch_forecast()
    if forecast_score is not None:
        forecast_color = color_forecast_score(forecast_score)
        forecast_text = f' <span color="{forecast_color}">{forecast_score}%</span>'
        forecast_tooltip = f"\nReset forecast: {forecast_score}% chance in 48h"
    else:
        forecast_text = ""
        forecast_tooltip = ""

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

        if reset_count is not None:
            tooltip += f"\nRate-limit resets: {reset_count} available"

        tooltip += forecast_tooltip

        print(json.dumps({
            "text": f"{label} <span color=\"{primary_color}\">{primary_bar}</span>"
                    f" <span color=\"{weekly_color}\">{weekly_bar}</span>"
                    f"{forecast_text}",
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

        tooltip += forecast_tooltip


        print(json.dumps({
            "text": f"{label} <span color=\"{weekly_color}\">{weekly_bar}</span>"
                    f"{forecast_text}",
            "tooltip": tooltip,
            "class": css_class,
        }))


if __name__ == "__main__":
    main()
