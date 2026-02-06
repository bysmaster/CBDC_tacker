import os
import requests
import time
from typing import Optional

class ZaiClient:
    def __init__(self):
        # Using specific Z.AI key or falling back to general env var if we rename it later
        self.api_key = os.environ.get("ZAI_API_KEY")
        self.base_url = "https://api.z.ai/api/paas/v4"
        self.model = "GLM-4.7-Flash" 

    def chat_completion(self, prompt: str) -> Optional[str]:
        if not self.api_key:
            print("⚠️ ZAI_API_KEY not found.")
            return None

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept-Language": "en-US,en"
        }
        
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.5,
            "stream": False
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
                        proxies=proxies, # Explicitly pass proxies
                        timeout=60
                    )
                    response.raise_for_status()
                    data = response.json()
                    return data['choices'][0]['message']['content']
                except requests.exceptions.RequestException as e:
                    print(f"⚠️ [Z.AI] Attempt {attempt+1} failed: {e}")
                    if attempt < 2:
                        time.sleep(2) # Short wait
                    else:
                        print(f"❌ [Z.AI] All retries failed.")
                        return None
        except Exception as e:
            print(f"❌ [Z.AI] Unexpected error: {e}")
            return None
