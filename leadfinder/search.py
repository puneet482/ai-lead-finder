"""Free-form search: "dentist in Mumbai" / "IT professors in Bangalore" -> ranked contacts.

query --parse--> Intent(kind=business|people)
business: find businesses (Google Places or free OpenStreetMap) -> read websites for owner/email -> score
people:   find institutions -> locate faculty/department pages -> extract name/title/email -> score
"""
import os, re, json
from dataclasses import dataclass, asdict, field
from urllib.parse import urljoin, urlparse
import requests
from bs4 import BeautifulSoup
from .llm import LLM
from .http import PoliteFetcher, UA
from . import local
from .local import LocalLead, EMAIL_RE, BAD_EMAIL_END

# ------------------------------------------------------------------ intent
PEOPLE_ROLES = {"professor": "professor", "professors": "professor", "lecturer": "lecturer", "lecturers": "lecturer",
                "faculty": "faculty", "teacher": "teacher", "teachers": "teacher", "hod": "hod",
                "principal": "principal", "principals": "principal", "dean": "dean", "deans": "dean"}
TECHY = {"it", "information technology", "computer", "computer science", "cse", "ai", "data science",
         "engineering", "electronics", "software", "mechanical", "civil"}
FIELD_ALIASES = {"it": ["information technology", "computer", "cse", "it "], "computer science": ["computer", "cse"],
                 "cse": ["computer", "cse"], "ai": ["artificial intelligence", "ai ", "machine learning", "data science"]}


@dataclass
class Intent:
    kind: str            # "business" | "people"
    target: str          # "dentist" / "professor"
    location: str
    field: str = ""      # "IT"
    org_query: str = ""  # people mode: kind of institution to look in, e.g. "engineering colleges"


SYSTEM = """Convert a lead-search query to JSON. Return ONLY JSON:
{"kind": "business" | "people", "target": str, "field": str, "location": str, "org_query": str}
- business: shops/clinics/firms (dentist, gym, restaurant, chartered accountant). target = the business type.
- people: individuals at institutions (professor, lecturer, principal, HOD). target = role (singular),
  field = subject (e.g. "IT"), org_query = institution type to search (e.g. "engineering colleges").
location = city/area as written. Never invent a location; use "" if none."""


def _fallback_intent(q: str) -> Intent:
    parts = re.split(r"\s+(?:in|at|near|around)\s+", q.strip(), maxsplit=1, flags=re.I)
    target, loc = (parts[0], parts[1]) if len(parts) == 2 else (q.strip(), "")
    words = target.lower().split()
    role = next((w for w in words if w in PEOPLE_ROLES), None)
    if role:
        fld = " ".join(w for w in words if w != role).strip()
        org = "engineering colleges" if (fld in TECHY) else "colleges and universities"
        return Intent("people", PEOPLE_ROLES[role], loc.strip(), fld, org)
    return Intent("business", target.strip(), loc.strip())


def parse_query(q: str, llm: LLM | None = None) -> Intent:
    intent = None
    if llm and llm.available:
        try:
            d = llm.json(SYSTEM, q, max_tokens=300)
            if d.get("kind") in ("business", "people") and d.get("target"):
                intent = Intent(d["kind"], d["target"].strip(), (d.get("location") or "").strip(),
                                (d.get("field") or "").strip(), (d.get("org_query") or "").strip())
        except Exception as e:
            print(f"[search] LLM intent failed ({e}); using rules")
    intent = intent or _fallback_intent(q)
    if intent.kind == "people" and not intent.org_query:
        intent.org_query = "engineering colleges" if intent.field.lower() in TECHY else "colleges and universities"
    if not intent.location:
        raise ValueError("Add a location, e.g. 'dentist in Mumbai'.")
    return intent


# ------------------------------------------------------------------ output record
@dataclass
class Contact:
    kind: str
    name: str                 # person / owner (may be blank for businesses)
    role: str
    organization: str
    phone: str = ""
    email: str = ""
    website: str = ""
    address: str = ""
    source_url: str = ""
    rating: float = 0.0
    review_count: int = 0
    confidence: dict = field(default_factory=dict)
    score: int = 0
    breakdown: dict = field(default_factory=dict)
    rationale: str = ""
    rubric_version: str = ""

    def to_row(self):
        d = asdict(self)
        d["confidence"] = "; ".join(f"{k}={v:.2f}" for k, v in self.confidence.items())
        d["breakdown"] = "; ".join(f"{k}={v}" for k, v in self.breakdown.items())
        return d


COLS = ["score", "name", "role", "organization", "phone", "email", "website", "address", "rating",
        "review_count", "source_url", "rationale", "breakdown", "confidence", "rubric_version", "kind"]

PEOPLE_RUBRIC = {"version": "people-1.0.0", "components": {
    "fit": "0-4: name found (1), title matches role (1.5), department matches field (1), institution in target city (0.5)",
    "reachability": "0-4: email on page (2.5), institution phone (1), source page URL (0.5)",
    "quality": "0-2: institution rating >=4.0 (1), >=100 reviews (1)"}}


# ------------------------------------------------------------------ organisations: Google / OSM
OSM_TAGS = {
    "dentist": [("amenity", "dentist"), ("healthcare", "dentist")], "dental": [("amenity", "dentist"), ("healthcare", "dentist")],
    "doctor": [("amenity", "doctors"), ("healthcare", "doctor")], "clinic": [("amenity", "clinic"), ("healthcare", "clinic")],
    "hospital": [("amenity", "hospital")], "pharmacy": [("amenity", "pharmacy")],
    "restaurant": [("amenity", "restaurant")], "cafe": [("amenity", "cafe")], "bank": [("amenity", "bank")],
    "gym": [("leisure", "fitness_centre")], "salon": [("shop", "hairdresser"), ("shop", "beauty")],
    "college": [("amenity", "college"), ("amenity", "university")], "universit": [("amenity", "university")],
    "school": [("amenity", "school")], "lawyer": [("office", "lawyer")], "advocate": [("office", "lawyer")],
    "accountant": [("office", "accountant")], "hotel": [("tourism", "hotel")],
    "bakery": [("shop", "bakery")], "jewel": [("shop", "jewelry")], "veterinar": [("amenity", "veterinary")],
}


def osm_tags_for(text: str):
    t = text.lower()
    for key in sorted(OSM_TAGS, key=len, reverse=True):
        if key in t:
            return OSM_TAGS[key]
    return None


def build_overpass(tags, bbox, term="", limit=80) -> str:
    s, n, w, e = bbox
    if tags:
        body = "".join(f'nwr["{k}"="{v}"]({s},{w},{n},{e});' for k, v in tags)
    else:
        body = f'nwr["name"~"{re.sub(r"[^A-Za-z0-9 ]", "", term)}",i]({s},{w},{n},{e});'
    return f"[out:json][timeout:30];({body});out center {limit};"


def parse_osm_element(el: dict, location: str) -> LocalLead | None:
    t = el.get("tags", {})
    if not t.get("name"):
        return None
    addr = ", ".join(x for x in [t.get("addr:housenumber"), t.get("addr:street"), t.get("addr:suburb"), t.get("addr:city")] if x)
    if location.split(",")[0].lower() not in addr.lower():
        addr = f"{addr}, {location}".strip(", ")
    site = t.get("website") or t.get("contact:website") or ""
    if site and not site.startswith("http"):
        site = "https://" + site
    phone = t.get("phone") or t.get("contact:phone") or t.get("contact:mobile") or ""
    email = t.get("email") or t.get("contact:email") or ""
    ll = LocalLead(name=t["name"], business_type=next((t[k] for k in ("amenity", "healthcare", "shop", "office", "leisure") if k in t), ""),
                   address=addr, phone=phone.split(";")[0].strip(), website=site, status="OPERATIONAL",
                   email=email.split(";")[0].strip(), maps_id=f"osm:{el.get('type')}/{el.get('id')}")
    ll.confidence = {"phone": 0.9 if ll.phone else 0.0, "email": 0.9 if ll.email else 0.0}
    return ll


def bbox_from_photon(data: dict):
    f = (data.get("features") or [None])[0]
    if not f:
        return None
    ext = f["properties"].get("extent")          # [minLon, maxLat, maxLon, minLat]
    if ext:
        w, n, e, s = ext
        return s, n, w, e
    lon, lat = f["geometry"]["coordinates"]
    d = 0.08
    return lat - d, lat + d, lon - d, lon + d


def geocode_bbox(location: str, headers: dict):
    """(south, north, west, east). Nominatim first, Photon as backup."""
    errs = []
    try:
        g = requests.get("https://nominatim.openstreetmap.org/search",
                         params={"q": location, "format": "json", "limit": 1}, headers=headers, timeout=20)
        g.raise_for_status()
        if g.json():
            return tuple(float(x) for x in g.json()[0]["boundingbox"])
        raise RuntimeError(f"Could not find location '{location}' on OpenStreetMap.")
    except requests.RequestException as e:
        errs.append(f"Nominatim: {e}")
    try:
        r = requests.get("https://photon.komoot.io/api/", params={"q": location, "limit": 1}, headers=headers, timeout=20)
        r.raise_for_status()
        b = bbox_from_photon(r.json())
        if b:
            return b
        errs.append(f"Photon: no match for '{location}'")
    except requests.RequestException as e:
        errs.append(f"Photon: {e}")
    raise RuntimeError("Location lookup failed (" + "; ".join(errs) + "). Set LEADFINDER_CONTACT to your email, or use Google Places.")


OVERPASS_MIRRORS = [m for m in [os.getenv("LEADFINDER_OVERPASS"),
                    "https://overpass-api.de/api/interpreter",
                    "https://overpass.kumi.systems/api/interpreter",
                    "https://overpass.private.coffee/api/interpreter"] if m]


def overpass_query(q: str, headers: dict, timeout=45) -> dict:
    """Try each public Overpass mirror until one answers."""
    errs = []
    for url in OVERPASS_MIRRORS:
        try:
            r = requests.post(url, data={"data": q}, headers=headers, timeout=timeout)
            if r.ok:
                return r.json()
            errs.append(f"{url.split('/')[2]}: HTTP {r.status_code}")
        except (requests.RequestException, ValueError) as e:
            errs.append(f"{url.split('/')[2]}: {type(e).__name__}")
    raise RuntimeError("All free OpenStreetMap data servers are busy or blocked (" + "; ".join(errs) +
                       "). Retry in a minute, or use Claude web search / Google Places.")


def osm_search(target: str, location: str, limit=60) -> list[LocalLead]:
    h = {"User-Agent": UA}
    s, n, w, e = geocode_bbox(location, h)
    q = build_overpass(osm_tags_for(target), (s, n, w, e), target, limit)
    data = overpass_query(q, h)
    out = [x for x in (parse_osm_element(el, location) for el in data.get("elements", [])) if x]
    return out[:limit]


def find_orgs(org_type: str, location: str, google_key: str | None, source: str, limit: int) -> tuple[list[LocalLead], str]:
    """source: auto | google | osm. Returns (orgs, source_used)."""
    use_google = source == "google" or (source == "auto" and google_key)
    if use_google:
        if not google_key:
            raise RuntimeError("Google Places selected but no API key given.")
        places = local.search_places(org_type, location, google_key, limit)
        return [p for p in (local.parse_place(x) for x in places) if p.name and p.status != "CLOSED_PERMANENTLY"], "google"
    return osm_search(org_type, location, limit), "osm"


# ------------------------------------------------------------------ people extraction
HON = r"\b(?:Dr|Prof)\b\.?"
_BAD = r"Professor|Assistant|Associate|Senior|Lecturer|Head|Department|Dept|Dean|Principal|Director|HOD|Computer|Information|Science|Engineering|Technology|Email|Phone|Faculty|Contact|Read|More"
TOK = rf"(?:[A-Z]\.|(?!(?:{_BAD})\b)[A-Z][a-z]{{1,14}})"
NAME = rf"{TOK}(?:\s{TOK}){{1,3}}"
TITLE = (r"(?:Assistant\s+Professor|Associate\s+Professor|Senior\s+Professor|Professor(?:\s+and\s+Head)?|Senior\s+Lecturer|Lecturer|"
         r"Head\s+of\s+(?:the\s+)?Department|HOD|Principal|Dean|Director)")
PERSON_RE = re.compile(rf"{HON}\s*(?P<n>{NAME})(?P<gap>(?:(?!{HON}).){{0,90}}?)(?P<t>{TITLE})", re.S)
LINK_KW = ["faculty", "staff", "people", "professor", "department", "dept", "teaching", "team", "academics"]

LLM_PEOPLE_SYSTEM = """Extract faculty/staff listed on this web page. Return ONLY JSON:
{"people": [{"name": str, "title": str, "department": str, "email": str}]}
Only include people explicitly named in the text; use "" for missing fields; never guess emails."""


def extract_people(html: str, llm: LLM | None = None) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    for t in soup(["script", "style", "noscript"]):
        t.decompose()
    text = soup.get_text(" | ", strip=True)
    people = []
    if llm and llm.available and len(text) > 200:
        try:
            d = llm.json(LLM_PEOPLE_SYSTEM, text[:15000], max_tokens=1500)
            low = text.lower()
            for p in d.get("people", []):
                nm = (p.get("name") or "").strip()
                if nm and all(tok.lower().strip(".,") in low for tok in nm.split()):     # anti-hallucination
                    em = (p.get("email") or "").lower()
                    people.append({"name": nm, "title": p.get("title", ""), "dept": p.get("department", ""),
                                   "email": em if em and em in low else "", "how": "llm"})
            if people:
                return people
        except Exception as e:
            print(f"[people] LLM extraction failed ({e}); using regex")
    for m in PERSON_RE.finditer(text):
        window = text[m.end(): m.end() + 200]
        nxt = re.search(HON, window)
        window = window[: nxt.start()] if nxt else window
        em = [e for e in EMAIL_RE.findall(window) if not e.lower().endswith(BAD_EMAIL_END)]
        context = text[max(0, m.start() - 60): m.end() + 120]
        people.append({"name": m["n"].strip(), "title": re.sub(r"\s+", " ", m["t"]), "dept": context,
                       "email": em[0].lower() if em else "", "how": "regex"})
    return people


def find_people_pages(html: str, base_url: str, field: str, limit=3) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    root = ".".join(urlparse(base_url).netloc.split(".")[-3:])
    aliases = [field.lower()] + FIELD_ALIASES.get(field.lower(), []) if field else []
    scored = {}
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith(("mailto:", "javascript:", "#", "tel:")):
            continue
        url = urljoin(base_url, href).split("#")[0]
        if root not in urlparse(url).netloc:
            continue
        blob = (a.get_text(" ") + " " + href).lower()
        s = 2 * sum(k in blob for k in LINK_KW) + (3 if any(al.strip() in blob for al in aliases) else 0)
        if s:
            scored[url] = max(scored.get(url, 0), s)
    return sorted(scored, key=scored.get, reverse=True)[:limit]


def role_matches(title: str, target: str) -> bool:
    t, tg = title.lower(), target.lower()
    if tg in ("faculty", "teacher", ""):
        return True
    if tg == "hod":
        return "head" in t or "hod" in t
    return tg in t


def field_matches(text: str, field_: str) -> bool:
    if not field_:
        return False
    low = text.lower() + " "
    return any(a in low for a in [field_.lower()] + FIELD_ALIASES.get(field_.lower(), []))


# ------------------------------------------------------------------ scoring
def score_person(c: Contact, intent: Intent, field_hit: bool, org_in_city: bool) -> Contact:
    why = []
    fit = 1.0 if c.name else 0.0
    if role_matches(c.role, intent.target):
        fit += 1.5; why.append(f"{c.role}")
    if field_hit:
        fit += 1; why.append(f"department matches '{intent.field}'")
    if org_in_city:
        fit += 0.5
    reach = 0.0
    if c.email: reach += 2.5; why.append(f"email {c.email}")
    if c.phone: reach += 1; why.append("institution phone listed")
    if c.source_url: reach += 0.5
    q = (1 if c.rating >= 4.0 else 0) + (1 if c.review_count >= 100 else 0)
    c.breakdown = {"fit": min(fit, 4), "reachability": min(reach, 4), "quality": q}
    c.score = max(1, min(10, round(sum(c.breakdown.values()))))
    c.rationale = f"{c.name} - {', '.join(why) or 'limited data'} at {c.organization}."
    c.rubric_version = PEOPLE_RUBRIC["version"]
    return c


def business_contact(l: LocalLead) -> Contact:
    return Contact("business", l.owner_name, l.owner_role, l.name, l.phone, l.email, l.website, l.address, l.website,
                   l.rating, l.review_count, dict(l.confidence), l.score, dict(l.breakdown), l.rationale, l.rubric_version)


# ------------------------------------------------------------------ Claude web-search source
WEB_SYSTEM = """You are a lead researcher. Use web search to find REAL entries and return ONLY JSON:
{"results": [{"name": str, "role": str, "organization": str, "phone": str, "email": str,
              "website": str, "address": str, "source_url": str}]}
Rules: only include details that appear on pages you actually found; never guess or construct emails or phone numbers;
use "" when not found; every result MUST have a source_url (the page where you found it); no duplicates."""

WEB_RUBRIC = {"version": "web-1.0.0", "components": "completeness 0-10: name 2, email 3, phone 2, website 1, address 1, source 1"}


def score_web(c: Contact) -> Contact:
    parts = {"name": 2 if c.name else 0, "email": 3 if c.email else 0, "phone": 2 if c.phone else 0,
             "website": 1 if c.website else 0, "address": 1 if c.address else 0, "source": 1 if c.source_url else 0}
    c.breakdown = parts
    c.score = max(1, min(10, sum(parts.values())))
    found = [k for k, v in parts.items() if v]
    c.rationale = f"Found on the web ({', '.join(found)}); verify via source link."
    c.rubric_version = WEB_RUBRIC["version"]
    return c


def web_search_contacts(intent: Intent, llm: LLM, n: int) -> list[Contact]:
    if not (llm and llm.available):
        raise RuntimeError("Claude web search needs ANTHROPIC_API_KEY (see README).")
    n = min(n, 20)
    if intent.kind == "people":
        ask = (f"Find up to {n} {intent.field} {intent.target}s working at colleges/universities in {intent.location}. "
               f"For each: full name, title, institution, official email if published on the institution's site, phone, website.")
    else:
        ask = (f"Find up to {n} {intent.target} businesses in {intent.location}. For each: business name, owner/founder name "
               f"if published (role = Owner/Founder), phone, email if published, website, address.")
    data = llm.web_json(WEB_SYSTEM, ask, max_uses=6)
    out, seen = [], set()
    for r in data.get("results", []):
        name, org, src = (r.get("name") or "").strip(), (r.get("organization") or "").strip(), (r.get("source_url") or "").strip()
        if not src or not (name or org):
            continue                                        # unsourced -> drop
        if intent.kind == "business" and not org:
            org, name = name, ""                            # a business listing: 'name' is the business
        key = (name.lower(), org.lower())
        if key in seen:
            continue
        seen.add(key)
        em = (r.get("email") or "").lower().strip()
        c = Contact("person" if intent.kind == "people" else "business",
                    name, r.get("role", ""), org, r.get("phone", ""), em if EMAIL_RE.fullmatch(em) else "",
                    r.get("website", ""), r.get("address", ""), src,
                    confidence={"web": 0.6, "email": 0.7 if em else 0.0})
        out.append(score_web(c))
    return sorted(out, key=lambda c: -c.score)[:n]


# ------------------------------------------------------------------ pipeline
def run_search(query: str, google_key: str | None = None, llm: LLM | None = None, max_results=30, scrape=True,
               source="auto", fetcher=None, org_finder=None, progress=None) -> tuple[list[Contact], dict]:
    intent = parse_query(query, llm)
    finder = org_finder or find_orgs
    stats = {"intent": asdict(intent)}
    prog = progress or (lambda p, m="": None)
    if source == "web" or (source == "auto" and not google_key and llm and llm.available):
        prog(0.2, "Searching the web with Claude...")
        res = web_search_contacts(intent, llm, max_results)
        stats.update(source="claude-web", results=len(res))
        return res, stats
    if intent.kind == "business":
        prog(0.1, f"Finding {intent.target} in {intent.location}...")
        orgs, used = finder(intent.target, intent.location, google_key, source, max_results)
        stats.update(source=used, found=len(orgs))
        seen, leads = set(), []
        for o in orgs:
            if o.maps_id not in seen:
                seen.add(o.maps_id); leads.append(o)
        fetcher = fetcher or (PoliteFetcher(min_delay=1.5, retries=2) if scrape else None)
        for i, l in enumerate(leads):
            if scrape and fetcher:
                local.enrich_from_website(l, fetcher)
            local.score_local(l, intent.target, intent.location)
            prog(0.1 + 0.9 * (i + 1) / max(len(leads), 1), f"Reading websites {i + 1}/{len(leads)}")
        stats["with_owner"] = sum(bool(l.owner_name) for l in leads)
        return sorted((business_contact(l) for l in leads), key=lambda c: -c.score), stats

    # people mode
    prog(0.05, f"Finding {intent.org_query} in {intent.location}...")
    orgs, used = finder(intent.org_query, intent.location, google_key, source, 40)
    orgs = sorted([o for o in orgs if o.website], key=lambda o: (-o.review_count, -o.rating))[:12]
    stats.update(source=used, institutions_with_website=len(orgs), pages_scanned=0)
    fetcher = fetcher or PoliteFetcher(min_delay=1.5, retries=2)
    out, seen = [], set()
    for i, org in enumerate(orgs):
        prog(0.1 + 0.9 * i / max(len(orgs), 1), f"Scanning {org.name} ({i + 1}/{len(orgs)})")
        home = fetcher.get(org.website)
        if not home:
            continue
        pages = [(org.website, home)] + [(u, fetcher.get(u)) for u in find_people_pages(home, org.website, intent.field)]
        for url, html in pages:
            if not html:
                continue
            stats["pages_scanned"] += 1
            for p in extract_people(html, llm):
                key = (p["name"].lower(), org.name)
                if key in seen or not role_matches(p["title"], intent.target):
                    continue
                seen.add(key)
                c = Contact("person", p["name"], p["title"], org.name, org.phone, p["email"], org.website, org.address,
                            url, org.rating, org.review_count,
                            {"name": 0.8 if p["how"] == "llm" else 0.6, "email": 0.85 if p["email"] else 0.0})
                score_person(c, intent, field_matches(p["dept"] + " " + url, intent.field),
                             intent.location.split(",")[0].lower() in org.address.lower())
                out.append(c)
        if len(out) >= max_results:
            break
    stats["people_found"] = len(out)
    return sorted(out, key=lambda c: -c.score)[:max_results], stats


def to_csv(contacts: list[Contact], path: str):
    import csv
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS, extrasaction="ignore")
        w.writeheader()
        for c in contacts:
            w.writerow(c.to_row())
