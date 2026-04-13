import os
import requests
import time
from typing import Optional

def safe_print(msg: str):
    """Print message safely handling encoding issues on Windows."""
    try:
        print(msg)
    except UnicodeEncodeError:
        # Fallback to ASCII-only output
        print(msg.encode('ascii', 'ignore').decode('ascii'))

class OpenRouterClient:
    def __init__(self):
        self.api_key = os.environ.get("OPENROUTER_API_KEY")
        self.base_url = "https://openrouter.ai/api/v1"
        self.model = "arcee-ai/trinity-large-preview:free"

    def chat_completion(self, prompt: str) -> Optional[str]:
        if not self.api_key:
            safe_print("[OpenRouter] OPENROUTER_API_KEY not found.")
            return None

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/cbdc-tracker",
            "X-Title": "CBDC Tracker"
        }

        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2,
            "max_tokens": 1024
        }

        # Ensure proxy is picked up
        proxies = {}
        if os.environ.get("HTTPS_PROXY"):
            proxies["https"] = os.environ.get("HTTPS_PROXY")
        if os.environ.get("HTTP_PROXY"):
            proxies["http"] = os.environ.get("HTTP_PROXY")

        try:
            # Retry logic
            for attempt in range(3):
                try:
                    url = f"{self.base_url.rstrip('/')}/chat/completions"
                    response = requests.post(
                        url,
                        headers=headers,
                        json=payload,
                        proxies=proxies,
                        timeout=60
                    )
                    response.raise_for_status()
                    data = response.json()
                    if 'choices' in data and len(data['choices']) > 0:
                        return data['choices'][0]['message']['content']
                    else:
                        safe_print(f"[OpenRouter] Invalid response format: {data}")
                        return None
                except requests.exceptions.RequestException as e:
                    safe_print(f"[OpenRouter] Attempt {attempt+1} failed: {e}")
                    if attempt < 2:
                        time.sleep(2)
                    else:
                        safe_print("[OpenRouter] All retries failed.")
                        return None
        except Exception as e:
            safe_print(f"[OpenRouter] Unexpected error: {e}")
            return None
