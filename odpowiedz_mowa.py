from gtts import gTTS
from playsound import playsound
import tempfile
import os
import time
import re

def oczysc_tekst(text: str) -> str:
    # Usuń emoji, znaki specjalne, tagi itp.
    # Zostaw litery, cyfry, spacje i podstawowe znaki interpunkcyjne
    return re.sub(r"[^a-zA-Z0-9ąćęłńóśźżĄĆĘŁŃÓŚŹŻ.,!? \n]", "", text)

def podziel_na_fragmenty(text, max_dlugosc=250):
    """Dzieli tekst na krótsze fragmenty do TTS (np. max 250 znaków)."""
    zdania = re.split(r'(?<=[.!?]) +', text)
    fragmenty = []
    buf = ""
    for zdanie in zdania:
        if len(buf) + len(zdanie) <= max_dlugosc:
            buf += zdanie + " "
        else:
            fragmenty.append(buf.strip())
            buf = zdanie + " "
    if buf:
        fragmenty.append(buf.strip())
    return fragmenty

def mow_tekstem(text: str, lang: str = 'pl'):
    """Zamienia tekst na mowę i odtwarza go."""
    try:
        # Stwórz plik tymczasowy, ale nie usuwaj automatycznie
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp_file:
            sciezka = "output.mp3"

        # Wygeneruj mowę i zapisz do pliku
        text= oczysc_tekst(text)
        tts = gTTS(text=text, lang=lang)
        tts.save(sciezka)

        time.sleep(0.2)  # 200 ms daje systemowi czas na zamknięcie pliku

        # Odtwórz plik
        playsound(sciezka)

        # Usuń plik ręcznie po odtworzeniu
        os.remove(sciezka)

    except Exception as e:
        print(f"❌ Błąd syntezy mowy: {e}")

if __name__ == "__main__":
    #mow_tekstem("#*😊 Cześć! Jak się masz?")
    mow_tekstem("#*😊 Opisz ssaki w 300 słowach")
