import os, json
from abc import ABC, abstractmethod
from typing import Iterator
import httpx
from dotenv import load_dotenv

load_dotenv()


class LLMProvider(ABC):
    @abstractmethod
    def stream(self, system: str, user: str, max_tokens: int = 400) -> Iterator[str]:
        """Yield text chunks as they are generated."""


class GroqProvider(LLMProvider):
    def __init__(self):
        from groq import Groq
        self.client = Groq(api_key=os.environ["GROQ_API_KEY"])
        self.model = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")

    def stream(self, system, user, max_tokens=400):
        extra = {"reasoning_effort": "low"} if "gpt-oss" in self.model else {}
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=max_tokens,
            temperature=0.7,
            stream=True,
            **extra,
        )
        for chunk in resp:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta


class OllamaProvider(LLMProvider):
    def __init__(self):
        self.url = os.getenv("OLLAMA_URL", "http://localhost:11434")
        self.model = os.getenv("OLLAMA_MODEL", "llama3.1:8b")

    def stream(self, system, user, max_tokens=400):
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": True,
            "options": {"num_predict": max_tokens},
        }
        with httpx.stream("POST", f"{self.url}/api/chat", json=payload, timeout=60) as r:
            for line in r.iter_lines():
                if line:
                    text = json.loads(line).get("message", {}).get("content", "")
                    if text:
                        yield text


def get_provider() -> LLMProvider:
    if os.getenv("LLM_PROVIDER", "groq").lower() == "ollama":
        return OllamaProvider()
    return GroqProvider()
