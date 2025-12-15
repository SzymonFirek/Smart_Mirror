import requests
import os

API_KEY = os.getenv("OPENROUTER_API_KEY")
API_URL = "https://openrouter.ai/api/v1/chat/completions"

headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
}

# Lista darmowych modeli do rotacji
DARMOWE_MODELE = [
    "openai/gpt-oss-20b:free",
    "deepseek/deepseek-chat-v3-0324:free",
    "nousresearch/nous-capybara-7b:free",
    "openchat/openchat-7b:free",
    "mistralai/mistral-7b-instruct:free"

]


def zapytaj_openrouter(prompt: str, modele: list[str] = DARMOWE_MODELE) -> str:
    for model in modele:
        print(f"🧠 Próbuję model: {model}")
        data = {
            "model": model,
            "messages": [
                {"role": "system", "content": "Jesteś pomocnym asystentem mówiącym po polsku. Odpowiadaj krótko i zwięźle. Nie używaj pogrubionej czcionki"},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.7,
            "max_tokens": 200,
        }

        try:
            response = requests.post(API_URL, headers=headers, json=data, timeout=15)
            if response.status_code == 200:
                result = response.json()
                odpowiedz = result["choices"][0]["message"]["content"].strip()

                if not odpowiedz or "no text to speech" in odpowiedz.lower():
                    print(f"⚠️ Model {model} nie zwrócił użytecznej odpowiedzi.")
                    continue  # Próbuj kolejnego modelu

                return odpowiedz

            else:
                print(f"⚠️ Błąd modelu {model}: {response.status_code} - {response.text}")
                continue

        except Exception as e:
            print(f"❌ Wyjątek przy modelu {model}: {e}")
            continue

    return "Niestety, żaden z modeli nie odpowiedział poprawnie."


if __name__ == "__main__":
    pytanie = "Jak się masz?"
    odpowiedz = zapytaj_openrouter(pytanie)
    print("🤖 OpenRouter:", odpowiedz)
