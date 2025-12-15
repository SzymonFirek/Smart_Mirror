#!/bin/bash
# Wejście do katalogu
cd ~/Desktop/Smart_Mirror

# Aktywacja venv
source .venv2/bin/activate

# Uruchomienie app.py w tle i zapis logów
python app.py > mirror.log 2>&1 &

# Czekamy aż Flask się podniesie
while ! grep -q "Running on http://127.0.0.1:5000" mirror.log; do
    sleep 1
done

# Otwórz Chromium w trybie kiosk (pełny ekran, bez pasków)
chromium-browser --kiosk http://127.0.0.1:5000
