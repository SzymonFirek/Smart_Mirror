#!/bin/bash
set -u

BASE_DIR="/home/smart/Desktop/Smart_Mirror"
URL="http://127.0.0.1:5000"
WAIT_SECONDS=60

cd "$BASE_DIR" || exit 1

# Środowisko GUI dla uruchomienia z systemd / PIR
export DISPLAY="${DISPLAY:-:0}"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
export PATH="/usr/bin:/bin:$PATH"

echo "[START_CHROMIUM] Start skryptu"
echo "[START_CHROMIUM] URL: $URL"
echo "[START_CHROMIUM] DISPLAY=${DISPLAY}"
echo "[START_CHROMIUM] XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR}"

# Jeśli Chromium już działa, nie uruchamiaj drugiej instancji
if pgrep -x chromium-browser >/dev/null 2>&1 || pgrep -x chromium >/dev/null 2>&1; then
    echo "[START_CHROMIUM] Chromium już działa - kończę."
    exit 0
fi

# Czekaj aż backend Flask zacznie odpowiadać
READY=0
for ((i=1; i<=WAIT_SECONDS; i++)); do
    if command -v curl >/dev/null 2>&1; then
        if curl -fsS "$URL" >/dev/null 2>&1; then
            READY=1
            break
        fi
    elif command -v wget >/dev/null 2>&1; then
        if wget -q -O /dev/null "$URL"; then
            READY=1
            break
        fi
    else
        echo "[START_CHROMIUM] Brak curl i wget - nie mogę sprawdzić backendu."
        exit 1
    fi

    sleep 1
done

if [ "$READY" -ne 1 ]; then
    echo "[START_CHROMIUM] Backend nie odpowiedział w ciągu ${WAIT_SECONDS}s."
    exit 1
fi

echo "[START_CHROMIUM] Backend gotowy - uruchamiam Chromium"

if command -v chromium-browser >/dev/null 2>&1; then
    exec chromium-browser \
        --kiosk \
        --noerrdialogs \
        --disable-infobars \
        --disable-session-crashed-bubble \
        --check-for-update-interval=31536000 \
        --overscroll-history-navigation=0 \
        "$URL"
elif command -v chromium >/dev/null 2>&1; then
    exec chromium \
        --kiosk \
        --noerrdialogs \
        --disable-infobars \
        --disable-session-crashed-bubble \
        --check-for-update-interval=31536000 \
        --overscroll-history-navigation=0 \
        "$URL"
else
    echo "[START_CHROMIUM] Nie znaleziono chromium-browser ani chromium."
    exit 1
fi