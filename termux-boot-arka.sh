#!/data/data/com.termux/files/usr/bin/bash
# Copy to Termux:  cp termux-boot-arka.sh ~/.termux/boot/arka.sh && chmod +x ~/.termux/boot/arka.sh
# Runs once after phone reboot (needs Termux:Boot app from F-Droid).

sleep 25  # wait for Wi‑Fi

ARKA_DIR="$HOME/arka"
ENV_FILE="$HOME/.arka/env"
SCRIPT="$ARKA_DIR/arka_phone.py"

[[ -f "$ENV_FILE" ]] && source "$ENV_FILE"
[[ -f "$SCRIPT" ]] || exit 0

# Quick ping — no interactive listen on boot; use browser UI or run: arka listen
python "$SCRIPT" health >/dev/null 2>&1 && termux-toast "Arka PC is online" 2>/dev/null || \
    termux-toast "Arka PC offline — run arka serve on PC" 2>/dev/null
