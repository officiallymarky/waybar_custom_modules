#!/usr/bin/env bash
set -euo pipefail

DEST="${XDG_CONFIG_HOME:-$HOME/.config}/waybar/scripts"

mkdir -p "$DEST"

cp codexbar.py openrouterbar.py "$DEST/"
chmod +x "$DEST"/codexbar.py "$DEST"/openrouterbar.py

echo "Installed to $DEST"
echo "Add the modules to your waybar config and style.css — see README.md"