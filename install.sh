#!/usr/bin/env bash
set -euo pipefail

DEST="${XDG_CONFIG_HOME:-$HOME/.config}/waybar/scripts"

mkdir -p "$DEST"

cp codexbar.py openrouterbar.py aithroughput.py "$DEST/"