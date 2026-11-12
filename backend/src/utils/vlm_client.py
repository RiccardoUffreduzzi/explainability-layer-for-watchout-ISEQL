import os

ENV_KEYS = {
    "openai": "OPENAI_API_KEY",
    "gemini": "GOOGLE_API_KEY",
    "claude": "ANTHROPIC_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "zhipu": "ZHIPUAI_API_KEY",
    "ollama": None,
}

# Sampling settings of every VLM call: no caller passes temperature or seed.
_DEFAULT_TEMPERATURE = 0.0
_DEFAULT_SEED = 42


class VLMClient:
    @staticmethod
    def generation_defaults() -> dict:
        """Temperature and seed a client uses when the caller passes none."""
        return {"temperature": _DEFAULT_TEMPERATURE, "seed": _DEFAULT_SEED}

    def __init__(self,
                 provider: str,
                 api_key: str = None,
                 model: str = None,
                 base_url: str = None,
                 max_tokens: int = 2048,
                 temperature: float = _DEFAULT_TEMPERATURE,
                 seed: int | None = _DEFAULT_SEED,
                 timeout: float = 60.0):
        provider = provider.lower().strip()
        if provider not in ENV_KEYS:
            raise ValueError(f"Unknown provider '{provider}'. "
                             f"Choose from: {list(ENV_KEYS.keys())}")
        
        self.provider = provider
        if not model:
            raise ValueError(f"No model provided for '{provider}'. Pass model= explicitly.")
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.seed = seed
        self.base_url = base_url
        self.timeout = timeout

        if provider == "ollama":
            self.api_key = "ollama"
            self.base_url = base_url or "http://localhost:11434"
        else:
            self.api_key = api_key or os.environ.get(ENV_KEYS[provider])
            if not self.api_key:
                raise ValueError(f"No API key provided for '{provider}'. "
                                 f"Pass api_key= or set env var {ENV_KEYS[provider]}.")
        
        self._client = self._init_client()

    def _init_client(self):
        if self.provider == "openai":
            from openai import OpenAI
            return OpenAI(api_key=self.api_key, timeout=self.timeout)
        
        elif self.provider == "gemini":
            from google import genai
            from google.genai import types
            return genai.Client(api_key=self.api_key,
                                http_options=types.HttpOptions(timeout=int(self.timeout * 1000)))
        
        elif self.provider == "claude":
            import anthropic
            return anthropic.Anthropic(api_key=self.api_key, timeout=self.timeout)

        elif self.provider == "mistral":
            from mistralai.client.sdk import Mistral
            return Mistral(api_key=self.api_key, timeout_ms=int(self.timeout * 1000))

        elif self.provider == "zhipu":
            from zhipuai import ZhipuAI
            return ZhipuAI(api_key=self.api_key, timeout=self.timeout)

        elif self.provider == "ollama":
            return self.base_url

    def chat(self, prompt: str, images: list = None) -> str:
        if self.provider == "openai":
            return self._chat_openai(prompt, images)
        elif self.provider == "gemini":
            return self._chat_gemini(prompt, images)
        elif self.provider == "claude":
            return self._chat_claude(prompt, images)
        elif self.provider == "mistral":
            return self._chat_mistral(prompt, images)
        elif self.provider == "zhipu":
            return self._chat_zhipu(prompt, images)
        elif self.provider == "ollama":
            return self._chat_ollama(prompt, images)

    def _chat_openai(self, prompt: str, images: list = None) -> str:
        content = [{"type": "text", "text": prompt}]
        if images:
            for img in images:
                content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{img}"}
                })
        
        response = self._client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": content}],
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            seed=self.seed,
            timeout=self.timeout,
        )
        return response.choices[0].message.content

    def _chat_gemini(self, prompt: str, images: list = None) -> str:
        from google.genai import types
        import base64
        
        parts = [types.Part.from_text(text=prompt)]
        if images:
            for img in images:
                img_data = base64.b64decode(img)
                parts.append(types.Part.from_bytes(data=img_data, mime_type="image/jpeg"))
        
        contents = [types.Content(role="user", parts=parts)]
        gen_config = types.GenerateContentConfig(
            max_output_tokens=self.max_tokens,
            temperature=self.temperature,
        )
        if self.seed is not None:
            gen_config.seed = self.seed
        response = self._client.models.generate_content(
            model=self.model,
            contents=contents,
            config=gen_config,
        )
        # Filter out thought/reasoning parts (Gemma models return thinking by default)
        text_parts = []
        for candidate in response.candidates:
            if candidate.content:
                for part in candidate.content.parts:
                    if getattr(part, 'thought', None):
                        continue
                    if hasattr(part, 'text') and part.text:
                        text_parts.append(part.text)
        return '\n'.join(text_parts) if text_parts else (response.text or "")

    def _chat_claude(self, prompt: str, images: list = None) -> str:
        content = [{"type": "text", "text": prompt}]
        if images:
            for img in images:
                content.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/jpeg",
                        "data": img
                    }
                })
        
        response = self._client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            messages=[{"role": "user", "content": content}],
            timeout=self.timeout,
        )
        return response.content[0].text

    def _chat_mistral(self, prompt: str, images: list = None) -> str:
        content = [{"type": "text", "text": prompt}]
        if images:
            for img in images:
                content.append({
                    "type": "image_url",
                    "image_url": f"data:image/jpeg;base64,{img}"
                })
        
        response = self._client.chat.complete(
            model=self.model,
            messages=[{"role": "user", "content": content}],
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            random_seed=self.seed,
            timeout_ms=int(self.timeout * 1000),
        )
        return response.choices[0].message.content

    def _chat_zhipu(self, prompt: str, images: list = None) -> str:
        content = [{"type": "text", "text": prompt}]
        if images:
            for img in images:
                content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{img}"}
                })
        
        response = self._client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": content}],
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            seed=self.seed,
            timeout=self.timeout,
        )
        return response.choices[0].message.content

    def _chat_ollama(self, prompt: str, images: list = None) -> str:
        import requests
        import json
        
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "options": {
                "temperature": self.temperature,
                "num_predict": self.max_tokens
            }
        }

        if self.provider == "ollama":
            payload["keep_alive"] = 0

        if self.seed is not None:
            payload["options"]["seed"] = self.seed

        if images:
            payload["messages"][0]["images"] = images
        
        response = requests.post(
            f"{self._client}/api/chat",
            json=payload,
            timeout=(self.timeout, None)
        )
        response.raise_for_status()
        return json.loads(response.content.decode('utf-8'))["message"]["content"]

    def list_models(self) -> list:
        if self.provider == "ollama":
            import requests
            try:
                response = requests.get(f"{self._client}/api/tags", timeout=5)
                response.raise_for_status()
                data = response.json()
                return [{"name": m["name"], "label": m["name"]} 
                        for m in data.get("models", [])]
            except:
                return []
        else:
            return [{"name": self.model, "label": self.model}]

    def __repr__(self) -> str:
        return (f"VLMClient(provider='{self.provider}', model='{self.model}', "
                f"max_tokens={self.max_tokens}, temperature={self.temperature})")
