# Waybar AI Modules

Custom waybar modules for monitoring AI API usage: **AI Throughput** (vllm/sglang/Flare inference rates),
**Codex** (quota windows), **Command Code** (credit windows) and **OpenRouter** (API key monthly spend).

## Modules

### codexbar

Displays your Codex 5-hour and weekly usage windows as block bars with independent, time-aware coloring.

**Dependency**: Python 3 stdlib only (no pip packages). Reads auth from `~/.codex/auth.json` and calls the ChatGPT API directly.

**How it colors each bar**:

| Bar | Logic |
|---|---|
| 5hr | Simple remaining%: green >= 60%, yellow >= 30%, red < 30% |
| Weekly | Compares budget `used%` vs `time left%` in the window: green while used <= time left, yellow when behind by up to 15 pts, red further behind (or <= 10% remaining regardless). 40% used halfway through the week is green (ahead); 70% used at the same point is red (will run out). |

The module CSS class (`critical`/`warning`/`""`) only controls the "Codex" label blink when truly critical (5hr <= 5%), leaving bar colors to inline `<span>` tags.

**Output**:
```
Codex(4) ████████ ████████
```
**Tooltip**:
```
5hr window: 98% remaining (94% of 5hr left) — resets in 4h
Weekly: 100% remaining (100% of week left) — resets in 6d 23h
Rate-limit resets: 4 available
```

> **Note**: If the 5-hour window is no longer reported by the API (Codex removed it
> temporarily or permanently), only the weekly bar is shown.
>
> **Weekly-only output:**
> ```
> Codex(4) ████████
> ```
> Tooltip: `Weekly: 100% remaining (100% of week left) — resets in 6d 23h`

### commandcodebar

Displays your Command Code 5-hour and weekly credit windows as block bars with independent, time-aware coloring.

**Dependency**: Python 3 stdlib only (no pip packages). Calls the Command Code API directly.

**How it colors each bar**:

| Bar | Logic |
|---|---|
| 5hr | Simple remaining% of the window cap: green >= 60%, yellow >= 30%, red < 30% |
| Weekly | Compares budget `used%` vs `time left%` in the window: green while used <= time left, yellow when behind by up to 15 pts, red further behind (or <= 10% remaining regardless). Same rule as codexbar, so the two modules read alike at a glance. |

The module CSS class (`critical`/`warning`/`""`) tracks the most urgent window — the 5hr window when the API reports one, otherwise the weekly window — leaving bar colors to inline `<span>` tags.

**Output**:
```
CmdCode ███████░ ████████
```
**Tooltip**:
```
Command Code usage
Plan: GOAT — renews in 29d
5hr window: 91% remaining (94% of 5hr left) — resets in 4h
Weekly: 96% remaining (100% of week left) — resets in 6d 23h
Monthly: 68.68 of 70.00 credits left (2% used)
```

Extra pay-as-you-go credits are never capped by the rolling windows, so when any are present two more tooltip lines appear:
```
Extra credits: 12.50 purchased, 3.25 free
Total available: 84.85
```

> **Note**: On plans with no rolling windows (pay-as-you-go / Provider), the module shows a single bar for the monthly credit balance instead, and the tooltip labels it `Monthly`.

> **Note**: The monthly allowance comes from the plan id reported by `/alpha/billing/subscriptions` (`individual-goat`, `individual-pro`, `individual-max`, …). An unrecognized plan id still renders, but the monthly line drops the allowance and shows the raw balance. If bonus credits push the balance above the plan allowance, the line reports them explicitly, e.g. `Monthly: 80.00 credits left (70.00 plan + 10.00 bonus)`.

### aithroughput

Displays real-time vllm, sglang or Flare inference throughput (prefill & decode tokens/s).

**Dependency**: Python 3 + `requests` package (`pip install requests` or `uv add requests`)

- Polls the backend's Prometheus `/metrics` endpoint.
- Flare derives rates from `flare_prefill_tokens_total` and `flare_generated_tokens_total` counter deltas.
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
cp codexbar.py commandcodebar.py openrouterbar.py aithroughput.py ~/.config/waybar/scripts/
chmod +x ~/.config/waybar/scripts/*.py
```

## Prerequisites

- **Waybar** built with `json` return-type support (default in most distro packages)
- **Codex** CLI authenticated and logged in (provides `~/.codex/auth.json`)
- **Command Code** API key in the `COMMAND_CODE_API_KEY` environment variable (commandcodebar only)
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
        "custom/commandcodebar",
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
    "custom/commandcodebar": {
        "exec": "/usr/bin/uv run $HOME/.config/waybar/scripts/commandcodebar.py",
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
- `interval` 1s for aithroughput (real-time throughput), 60s for codexbar and commandcodebar, 900s (15 min) for openrouterbar.

### Environment variables

**commandcodebar** and **openrouterbar** both read their key from the
environment (`COMMAND_CODE_API_KEY`, `OPENROUTER_API_KEY`).

Waybar does not read shell init files (`.bashrc`, `.profile`, `.zshrc`), so an
`export` in your shell is not enough — create a config in
[environment.d](https://wiki.archlinux.org/title/Environment_variables#Using_environment.d)
to make the variable available to every process in your session:

```ini
# ~/.config/environment.d/openrouter.conf
OPENROUTER_API_KEY=sk-or-v1-...
```

```ini
# ~/.config/environment.d/commandcode.conf
COMMAND_CODE_API_KEY=user_...
```

This works in KDE Plasma (systemd session mode), Sway/Hyprland launched via
`systemd --user`, or any display manager that enables the systemd user
session.  If your compositor launches waybar outside systemd (e.g. bare
`exec` in raw Sway/Hyprland), fall back to inline sourcing:

```ini
# ~/.config/waybar/.env
OPENROUTER_API_KEY=sk-or-v1-...
COMMAND_CODE_API_KEY=user_...
```

```json
"custom/openrouterbar": {
    "exec": "set -a; . $HOME/.config/waybar/.env; exec /usr/bin/python3 $HOME/.config/waybar/scripts/openrouterbar.py",
    ...
}
```

`environment.d` is read when the systemd user session starts, so a file added
mid-session needs the variable handed to the running manager and the bar
restarted before it takes effect:

```bash
systemctl --user import-environment COMMAND_CODE_API_KEY
killall waybar            # waybar can leave stale instances behind
systemctl --user reset-failed waybar
systemctl --user start waybar
pgrep -c -x waybar        # expect 1
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

/* ── Command Code ── */
#custom-commandcodebar {
    color: #ffffff;
}
#custom-commandcodebar.critical {
    color: #f23645;
    animation-name: blink;
    animation-duration: 1s;
    animation-timing-function: linear;
    animation-iteration-count: infinite;
    animation-direction: alternate;
}
#custom-commandcodebar.warning {
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
## How Weekly Coloring Works (codexbar and commandcodebar)

Both weekly bars share one rule, so the two modules read alike at a glance.

The weekly bar compares **budget used** against **time left** in the window,
instead of a flat remaining% threshold, and is fully independent of the 5hr bar.

At any point in the week, calculate:

```
time_left  = 100 - time_elapsed_pct
margin     = time_left - used_pct
```

If `margin >= 0`: **green** -- at or ahead of schedule (more time left than budget consumed).
If `margin >= -15`: **yellow** -- up to 15 pts behind schedule.
If `margin < -15`: **red** -- burning budget faster than time remains.
Always **red** when <= 10% of the weekly budget remains, regardless of schedule.

Examples: 40% used halfway through the week is green (50% time left vs 40% used);
60% used at the same point is yellow; 70% used is red. The same used% can sit in
different colors at different points of the week, but the weekly bar never reacts
to 5hr-window state -- only to its own budget and its own clock.
