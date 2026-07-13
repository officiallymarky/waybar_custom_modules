# Waybar AI Modules

Custom waybar modules for monitoring AI API usage: **AI Throughput** (vllm/sglang inference rates),
**Codex** (quota windows) and **OpenRouter** (API key monthly spend).

## Modules

### codexbar

Displays your Codex 5-hour and weekly usage windows as block bars with independent, time-aware coloring.

**Dependency**: Python 3 stdlib only (no pip packages). Reads auth from `~/.codex/auth.json` and calls the ChatGPT API directly.

**How it colors each bar**:

| Bar | Logic |
|---|---|
| 5hr | Simple remaining%: green >= 60%, yellow >= 30%, red < 30% |
| Weekly | **Scaled** -- compares `used%` vs `time-elapsed%` through the week. Green if comfortably ahead of schedule (+15 pts), yellow if on track, red if behind schedule or <= 10% remaining regardless. A 46% usage at 15% of the week is red (behind); the same 46% at 70% of the week is green (ahead, conserving). |

The module CSS class (`critical`/`warning`/`""`) only controls the "Codex" label blink when truly critical (5hr <= 5%), leaving bar colors to inline `<span>` tags.

**Output**:
```
Codex(4) ████████ ████████
```
**Tooltip**:
```
5hr window: 98% remaining (6% of 5hr elapsed) — resets in 4h
Weekly: 100% remaining (0% of week elapsed) — resets in 6d 23h
Rate-limit resets: 4 available
```

> **Note**: If the 5-hour window is no longer reported by the API (Codex removed it
> temporarily or permanently), only the weekly bar is shown.
>
> **Weekly-only output:**
> ```
> Codex(4) ████████
> ```
> Tooltip: `Weekly: 100% remaining (0% of week elapsed) — resets in 6d 23h`

### aithroughput

Displays real-time vllm or sglang inference throughput (prefill & decode tokens/s).

**Dependency**: Python 3 + `requests` package (`pip install requests` or `uv add requests`)

- Polls the backend's Prometheus `/metrics` endpoint.
- Shows prefill tokens/s and decode tokens/s as `AI P 12345 D 228`.
- CSS class: `good` (active inference), `idle` (no tokens flowing), `critical` (offline/unreachable).
- Configuration is passed as CLI flags in the waybar config — no `.env` file needed.

**Output**:
```
AI P 12345 D 228
```
**Tooltip**:
```
AI Throughput
Prefill: 12345.0 tokens/s
Decode:  228.0 tokens/s
Backend: vllm
Model:   chat
```

### openrouterbar

Displays your OpenRouter API key monthly spend.

**Dependency**: Python 3 stdlib only (no pip packages)

- Polls `https://openrouter.ai/api/v1/key` with your API key.
- Shows monthly spend as `OR $12.34`
- CSS class: `critical` (<= 10% remaining), `warning` (<= 25%), `idle` (no usage this month), `good` (default)

**Tooltip**:
```
OpenRouter API key usage
Monthly usage: $12.34
Weekly usage: $3.21
Daily usage: $0.50
All-time usage: $145.67
Limit: $200.00
Remaining: $54.33
Reset: 2026-07-31
BYOK monthly usage: $0.00
```

## Installation

```bash
./install.sh
```

Or copy manually:

```bash
mkdir -p ~/.config/waybar/scripts
cp codexbar.py openrouterbar.py aithroughput.py ~/.config/waybar/scripts/
chmod +x ~/.config/waybar/scripts/*.py
```

## Prerequisites

- **Waybar** built with `json` return-type support (default in most distro packages)
- **Codex** CLI authenticated and logged in (provides `~/.codex/auth.json`)
- **OpenRouter API key** in `OPENROUTER_API_KEY` environment variable (openrouterbar only)
- **Python `requests` package** (aithroughput only): `pip install requests` or `uv add requests`

## Waybar Configuration

### `~/.config/waybar/config`

Add the modules to your `modules-right` (or wherever you want them):

```json
{
    "modules-right": [
        "custom/aithroughput",
        "custom/codexbar",
        "custom/openrouterbar"
    ],
    "custom/aithroughput": {
        "exec": "/usr/bin/uv run $HOME/.config/waybar/scripts/aithroughput.py --url http://host:port/metrics --backend vllm --model chat",
        "return-type": "json",
        "interval": 1,
        "format": "{}",
        "parse": "pango",
        "tooltip": true
    },
    "custom/codexbar": {
        "exec": "/usr/bin/uv run $HOME/.config/waybar/scripts/codexbar.py",
        "return-type": "json",
        "interval": 60,
        "format": "{}",
        "parse": "pango",
        "tooltip": true
    },
    "custom/openrouterbar": {
        "exec": "/usr/bin/uv run $HOME/.config/waybar/scripts/openrouterbar.py",
        "return-type": "json",
        "interval": 900,
        "format": "{}",
        "parse": "pango",
        "tooltip": true
    }
}
```

Notes:

- Replace `--url`, `--backend`, and `--model` with your actual metrics endpoint and model.
- `"parse": "pango"` is required for `<span>` color tags.
- `interval` 1s for aithroughput (real-time throughput), 60s for codexbar, 900s (15 min) for openrouterbar.

### Environment variables

Waybar does not read shell init files (`.bashrc`, `.profile`, `.zshrc`).

Create a config in
[environment.d](https://wiki.archlinux.org/title/Environment_variables#Using_environment.d)
to make the variable available to every process in your session:

```ini
# ~/.config/environment.d/openrouter.conf
OPENROUTER_API_KEY=sk-or-v1-...
```

This works in KDE Plasma (systemd session mode), Sway/Hyprland launched via
`systemd --user`, or any display manager that enables the systemd user
session.  If your compositor launches waybar outside systemd (e.g. bare
`exec` in raw Sway/Hyprland), fall back to inline sourcing:

```ini
# ~/.config/waybar/.env
OPENROUTER_API_KEY=sk-or-v1-...
```

```json
"custom/openrouterbar": {
    "exec": "set -a; . $HOME/.config/waybar/.env; exec /usr/bin/python3 $HOME/.config/waybar/scripts/openrouterbar.py",
    ...
}
```
## Styling

Add to `~/.config/waybar/style.css`:

```css
/* ── AI Throughput ── */
#custom-aithroughput {
    color: #ffffff;
}
#custom-aithroughput.warning {
    color: #f9e2af;
}
#custom-aithroughput.good {
    color: #ffffff;
}
#custom-aithroughput.critical {
    color: #f38ba8;
}
#custom-aithroughput.idle {
    color: #6c7086;
}

/* ── Codexbar ── */
#custom-codexbar {
    color: #ffffff;
}
#custom-codexbar.critical {
    color: #f23645;
    animation-name: blink;
    animation-duration: 1s;
    animation-timing-function: linear;
    animation-iteration-count: infinite;
    animation-direction: alternate;
}
#custom-codexbar.warning {
    color: #f9e2af;
}

/* ── OpenRouter ── */
#custom-openrouterbar {
    color: #ffffff;
}
#custom-openrouterbar.warning {
    color: #f9e2af;
}
#custom-openrouterbar.critical {
    color: #f38ba8;
}
#custom-openrouterbar.idle {
    color: #6c7086;
}

/* ── Shared blink animation ── */
@keyframes blink {
    to {
        background-color: #ffffff;
        color: #000000;
    }
}
```
## How Weekly Scaling Works (codexbar)

The weekly bar uses **time-scaling** instead of a flat remaining% threshold.

At any point in the week, calculate:

```
elapsed_pct  = time_since_reset / window_duration * 100
adjusted     = elapsed_pct - used_pct
```

If `adjusted >= +15`: **ahead of schedule** (green) -- conserving budget well.
If `adjusted >= -15`: **on track** (yellow) -- consumption matches time elapsed.
If `adjusted < -15`: **behind schedule** (red) -- burning budget faster than time passes.

This prevents false alarms early in the week. Example: 46% used at 15% of the week is behind schedule (correct -- you'll run out), but 46% used at 70% of the week means you saved most of your budget for the final stretch (green).
