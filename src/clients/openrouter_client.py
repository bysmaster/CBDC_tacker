import os
import requests
import time
from typing import Optional

class OpenRouterClient:
    def __init__(self):
        self.api_key = os.environ.get("OPENROUTER_API_KEY")
        # Switch back to real OpenRouter endpoint
        self.base_url = "https://openrouter.ai/api/v1"
        self.model = "openrouter/free" # Fallback to generic free router

    def chat_completion(self, prompt: str) -> Optional[str]:
        if not self.api_key:
            print("⚠️ OPENROUTER_API_KEY not found.")
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
                    # print(f"DEBUG: Connecting to OpenRouter at {url}...")
                    response = requests.post(
                        url,
                        headers=headers,
                        json=payload,
                        proxies=proxies, # Explicitly pass proxies
                        timeout=60
                    )
                    response.raise_for_status()
                    data = response.json()
                    if 'choices' in data and len(data['choices']) > 0:
                        return data['choices'][0]['message']['content']
                    else:
                        print(f"⚠️ [OpenRouter] Invalid response format: {data}")
                        return None
                except requests.exceptions.RequestException as e:
                    print(f"⚠️ [OpenRouter] Attempt {attempt+1} failed: {e}")
                    if attempt < 2:
                        time.sleep(2)
                    else:
                        print(f"❌ [OpenRouter] All retries failed.")
                        return None
        except Exception as e:
            print(f"❌ [OpenRouter] Unexpected error: {e}")
            return None
