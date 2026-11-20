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

    def web_json(self, system: str, user: str, max_uses: int = 6, max_tokens: int = 4000) -> dict:
        """Claude with the server-side web_search tool; returns the JSON object in its final answer."""
        tools = [{"type": "web_search_20250305", "name": "web_search", "max_uses": max_uses}]
        messages = [{"role": "user", "content": user}]
        for _ in range(4):                                  # handle pause_turn on long searches
            r = self.client.messages.create(model=self.model, max_tokens=max_tokens, system=system,
                                            tools=tools, messages=messages)
            if getattr(r, "stop_reason", "") != "pause_turn":
                break
            messages = messages + [{"role": "assistant", "content": r.content}]
        text = "".join(b.text for b in r.content if getattr(b, "type", "") == "text")
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            raise ValueError("Claude returned no JSON")
        return json.loads(m.group(0))
