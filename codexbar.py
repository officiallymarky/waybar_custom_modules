#!/usr/bin/env python3
"""Waybar module for Codex usage with independent per-bar coloring.

5hr bar: colored by remaining %.
Weekly bar: colored by scaled consumption — compares used% vs time-elapsed%
through the week so "ahead of schedule" and "behind schedule" differ even
at the same remaining %.
"""
import json
import subprocess
from datetime import datetime, timezone


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
      positive → more time elapsed than budget used (ahead of schedule)
      negative → more budget used than time elapsed (behind schedule)
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


def compute_elapsed_pct(resets_at_str: str, window_minutes: int) -> float:
    """How much of the current window has elapsed, as a percentage (0-100)."""
    if not resets_at_str or window_minutes <= 0:
        return 0.0

    now = datetime.now(timezone.utc)
    resets_at = datetime.fromisoformat(resets_at_str.replace("Z", "+00:00"))
    window_start = resets_at.timestamp() - (window_minutes * 60)
    elapsed = now.timestamp() - window_start
    total = resets_at.timestamp() - window_start

    if total <= 0:
        return 0.0

    return max(0.0, min(100.0, (elapsed / total) * 100))


result = subprocess.run(
    ["/home/linuxbrew/.linuxbrew/bin/codexbar", "usage", "--json-only", "--source", "cli"],
    capture_output=True, text=True,
)

data = json.loads(result.stdout)[0]
usage = data["usage"]
primary = usage["primary"]
secondary = usage["secondary"]

primary_remaining = 100 - primary["usedPercent"]
secondary_remaining = 100 - secondary["usedPercent"]
primary_elapsed_pct = compute_elapsed_pct(primary["resetsAt"], primary["windowMinutes"])
# Weekly time scaling
elapsed_pct = compute_elapsed_pct(secondary["resetsAt"], secondary["windowMinutes"])

primary_color = color_remaining(primary_remaining)
secondary_color = color_weekly_scaled(secondary["usedPercent"], elapsed_pct)

primary_bar = make_bar(primary_remaining)
secondary_bar = make_bar(secondary_remaining)

# Module class — used for blink animation only when truly critical
# (spans handle per-bar colors independently)
if primary_remaining <= 5:
    css_class = "critical"
elif primary_remaining <= 20:
    css_class = "warning"
else:
    css_class = ""

primary_tooltip = f"5hr window: {primary_remaining}% remaining ({primary_elapsed_pct:.0f}% of 5hr elapsed) — resets {primary['resetDescription']}"

if secondary_remaining < 0:
    secondary_tooltip = f"Weekly: exceeded by {-secondary_remaining}% — resets {secondary['resetDescription']}"
else:
    secondary_tooltip = f"Weekly: {secondary_remaining}% remaining ({elapsed_pct:.0f}% of week elapsed) — resets {secondary['resetDescription']}"

tooltip = f"{primary_tooltip}\n{secondary_tooltip}"

# Tertiary (code review), when available
tertiary = usage.get("tertiary")
if tertiary and tertiary.get("usedPercent") is not None:
    tertiary_remaining = 100 - tertiary["usedPercent"]
    tooltip += f"\nCode Review: {tertiary_remaining}% remaining"

print(json.dumps({
    "text": (
        f"Codex <span color=\"{primary_color}\">{primary_bar}</span>"
        f" <span color=\"{secondary_color}\">{secondary_bar}</span>"
    ),
    "tooltip": tooltip,
    "class": css_class,
}))