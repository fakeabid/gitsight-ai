"""List all Gemini models available to the current API key."""

import httpx

from app.core.config import get_settings


def main() -> None:
    settings = get_settings()
    api_key = settings.gemini_api_key.get_secret_value()
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"

    print(f"Fetching available models for key prefix {api_key[:8]}...")
    try:
        response = httpx.get(url, timeout=10.0)
        data = response.json()
        if "error" in data:
            print("API Error:", data["error"])
            return

        models = data.get("models", [])
        print(f"\nFound {len(models)} models available:")
        for m in models:
            methods = m.get("supportedGenerationMethods", [])
            if "generateContent" in methods:
                name = m.get("name", "").removeprefix("models/")
                display = m.get("displayName", "")
                print(f"  - {name:<30} ({display})")
    except Exception as e:
        print("Failed to fetch models:", e)


if __name__ == "__main__":
    main()
