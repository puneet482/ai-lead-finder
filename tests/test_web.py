from leadfinder.search import parse_query, web_search_contacts, run_search
from leadfinder.diagnose import run_diagnostics


class FakeLLM:
    available = True
    model = "fake"
    def web_json(self, system, user, max_uses=6, max_tokens=4000):
        return {"results": [
            {"name": "Smile Dental Clinic", "role": "", "organization": "", "phone": "022 1111", "email": "", "website": "https://smile.in",
             "address": "Malad West, Mumbai", "source_url": "https://smile.in/contact"},
            {"name": "Dr. Anita Rao", "role": "Owner", "organization": "Smile Dental Clinic", "phone": "", "email": "anita@smile.in",
             "website": "", "address": "", "source_url": "https://smile.in/about"},
            {"name": "No Source Clinic", "organization": "", "source_url": ""},
            {"name": "Smile Dental Clinic", "organization": "", "source_url": "https://dup.example"}]}
    def json(self, *a, **k):
        raise RuntimeError("not used")


def test_web_contacts_filter_dedupe_score():
    res = web_search_contacts(parse_query("dentist in Mumbai"), FakeLLM(), 10)
    names = {(c.name, c.organization) for c in res}
    assert ("", "Smile Dental Clinic") in names and ("Dr. Anita Rao", "Smile Dental Clinic") in names
    assert len(res) == 2 and all(c.source_url and 1 <= c.score <= 10 for c in res)
    assert res[0].score >= res[1].score


def test_auto_routes_to_web_when_only_claude():
    res, stats = run_search("dentist in Mumbai", None, FakeLLM(), 10, source="auto")
    assert stats["source"] == "claude-web" and res


def test_diagnostics_never_crash(monkeypatch):
    import requests
    def boom(*a, **k): raise requests.ConnectionError("blocked")
    monkeypatch.setattr(requests, "get", boom); monkeypatch.setattr(requests, "post", boom)
    out = run_diagnostics(None, None)
    assert len(out) >= 5 and not any(ok for _, ok, _ in out[:3])


def test_overpass_falls_back_to_next_mirror(monkeypatch):
    import requests
    from leadfinder import search
    calls = []
    class R:
        def __init__(self, ok, data=None): self.ok, self.status_code, self._d = ok, 200 if ok else 504, data
        def json(self): return self._d
    def fake_post(url, **k):
        calls.append(url)
        if len(calls) == 1: raise requests.ReadTimeout("slow")
        return R(True, {"elements": [1]})
    monkeypatch.setattr(requests, "post", fake_post)
    assert search.overpass_query("q", {}) == {"elements": [1]} and len(calls) == 2
