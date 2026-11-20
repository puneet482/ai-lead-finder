"""Thin LLM wrapper. Falls back gracefully when no API key is configured."""
import json, os, re


class LLM:
    def __init__(self, model: str | None = None):
        self.model = model or os.getenv("LEADFINDER_MODEL", "claude-sonnet-5-5")
        self.client = None
        if os.getenv("ANTHROPIC_API_KEY"):
            try:
                import anthropic
                self.client = anthropic.Anthropic()
            except ImportError:
                pass

    @property
    def available(self) -> bool:
        return self.client is not None

    def json(self, system: str, user: str, max_tokens: int = 800) -> dict:
        r = self.client.messages.create(
            model=self.model, max_tokens=max_tokens, system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(b.text for b in r.content if b.type == "text")
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            raise ValueError("LLM returned no JSON")
        return json.loads(m.group(0))
