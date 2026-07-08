# Waybar AI Modules

Custom waybar modules for monitoring AI API usage: **Codex** (5hr/weekly quota) and **OpenRouter** (API key monthly spend).

## Modules

### codexbar

Displays your Codex 5-hour and weekly usage windows as block bars with independent, time-aware coloring.

**Dependency**: [codexbar](https://github.com/B00merang/CodexBar) CLI (`codexbar usage --json-only --source cli`)

**How it colors each bar**:

| Bar | Logic |
|---|---|
| 5hr | Simple remaining%: green >= 60%, yellow >= 30%, red < 30% |
| Weekly | **Scaled** -- compares `used%` vs `time-elapsed%` through the week. Green if comfortably ahead of schedule (+15 pts), yellow if on track, red if behind schedule or <= 10% remaining regardless. A 46% usage at 15% of the week is red (behind); the same 46% at 70% of the week is green (ahead, conserving). |

The module CSS class (`critical`/`warning`/`""`) only controls the "Codex" label blink when truly critical (5hr <= 5%), leaving bar colors to inline `<span>` tags.

**Output**:

```
Codex ████░░░░ ████████
```

**Tooltip**:
```
5hr window: 0% remaining -- resets 3:38 AM
Weekly: 54% remaining (15% of week elapsed) -- resets Jul 14 at 2:21 AM
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
cp codexbar.py openrouterbar.py ~/.config/waybar/scripts/
chmod +x ~/.config/waybar/scripts/*.py
```

## Prerequisites

- **Waybar** built with `json` return-type support (default in most distro packages)
- **codexbar** CLI installed and authenticated (codexbar only)
- **OpenRouter API key** in `OPENROUTER_API_KEY` environment variable (openrouterbar only)

## Waybar Configuration

### `~/.config/waybar/config`

Add both to your `modules-right` (or wherever you want them):

```json
{
    "modules-right": [
        "custom/codexbar",
        "custom/openrouterbar"
    ],
    "custom/codexbar": {
        "exec": "/usr/bin/python3 $HOME/.config/waybar/scripts/codexbar.py",
        "return-type": "json",
        "interval": 30,
        "format": "{}",
        "parse": "pango",
        "tooltip": true
    },
    "custom/openrouterbar": {
        "exec": "/usr/bin/python3 $HOME/.config/waybar/scripts/openrouterbar.py",
        "return-type": "json",
        "interval": 900,
        "format": "{}",
        "parse": "pango",
        "tooltip": true
    }
}
```

Notes:

- `"parse": "pango"` is required for `<span>` color tags in codexbar.
- `interval` 30s for codexbar (live feedback), 900s (15 min) for openrouterbar (usage changes slowly).
- If you use `uv`, replace `exec` with `"/usr/bin/uv run $HOME/.config/waybar/scripts/codexbar.py"`.

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
