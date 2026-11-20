"""Connection checks: tells you exactly which data sources work from THIS machine/network."""
import requests
from .http import UA
from .llm import LLM
from .search import OVERPASS_MIRRORS


def _try(name, fn):
    try:
        return name, True, str(fn())[:140]
    except Exception as e:
        return name, False, f"{type(e).__name__}: {str(e)[:200]}"


def run_diagnostics(google_key: str | None = None, llm: LLM | None = None):
    h = {"User-Agent": UA}
    checks = []

    def nominatim():
        r = requests.get("https://nominatim.openstreetmap.org/search", params={"q": "Mumbai", "format": "json", "limit": 1}, headers=h, timeout=15)
        r.raise_for_status(); return f"OK, found {r.json()[0]['display_name'][:40]}"

    def photon():
        r = requests.get("https://photon.komoot.io/api/", params={"q": "Mumbai", "limit": 1}, headers=h, timeout=15)
        r.raise_for_status(); return "OK"

    q = '[out:json][timeout:20];nwr["amenity"="dentist"](19.0,19.2,72.8,72.9);out center 1;'

    def overpass_one(url):
        def f():
            r = requests.post(url, data={"data": q}, headers=h, timeout=30)
            r.raise_for_status(); return f"OK, {len(r.json().get('elements', []))} element(s)"
        return f

    checks += [_try("OpenStreetMap geocoder (Nominatim)", nominatim), _try("Backup geocoder (Photon)", photon)]
    checks += [_try(f"OSM data server {u.split('/')[2]}", overpass_one(u)) for u in OVERPASS_MIRRORS] + [_try(f"OSM data server {u.split('/')[2]}", overpass_one(u)) for u in OVERPASS_MIRRORS]
    if google_key:
        def google():
            from .local import search_places
            return f"OK, {len(search_places('dentist', 'Malad, Mumbai', google_key, 3))} place(s)"
        checks.append(_try("Google Places key", google))
    else:
        checks.append(("Google Places key", False, "no key provided (optional)"))
    if llm and llm.available:
        checks.append(_try("Claude API key", lambda: llm.json("Return only JSON.", 'Return {"ok": true}', 50)))
        checks.append(_try("Claude web search", lambda: llm.web_json("Return ONLY JSON {\"ok\": true, \"city\": str}.",
                                                                    "Use web search: what country is Mumbai in? Reply JSON.", max_uses=1, max_tokens=300)))
    else:
        checks.append(("Claude API key", False, "no ANTHROPIC_API_KEY set (optional)"))
    return checks
