"""Local-business lead finder: Google Places (New) -> website scrape for owner/email -> score.

Only uses business-level public info (listing + the business's own website). Respects robots.txt via PoliteFetcher.
"""
import csv, json, re
from dataclasses import dataclass, asdict, field
import requests
from bs4 import BeautifulSoup
from .http import PoliteFetcher

PLACES_URL = "https://places.googleapis.com/v1/places:searchText"
FIELDS = ("places.id,places.displayName,places.formattedAddress,places.nationalPhoneNumber,places.websiteUri,"
          "places.rating,places.userRatingCount,places.businessStatus,places.primaryTypeDisplayName,nextPageToken")

RUBRIC = {
    "version": "local-1.0.0",
    "components": {
        "fit": {"max": 4, "desc": "Operational (1), address in target locality (1), type matches search (1), has website (1)."},
        "quality": {"max": 3, "desc": "Established business: rating >=4.2 (1.5), reviews >=100 (1.5) / >=30 (0.75)."},
        "reachability": {"max": 3, "desc": "Owner name found (1), direct email (1; generic info@ 0.5), phone (1)."},
    },
    "total": "round(fit + quality + reachability), clamped 1..10",
}


@dataclass
class LocalLead:
    name: str
    business_type: str = ""
    address: str = ""
    phone: str = ""
    website: str = ""
    rating: float = 0.0
    review_count: int = 0
    status: str = ""
    owner_name: str = ""
    owner_role: str = ""
    email: str = ""
    maps_id: str = ""
    confidence: dict = field(default_factory=dict)
    score: int = 0
    breakdown: dict = field(default_factory=dict)
    rationale: str = ""
    rubric_version: str = RUBRIC["version"]

    def to_row(self):
        d = asdict(self)
        d["confidence"] = "; ".join(f"{k}={v:.2f}" for k, v in self.confidence.items())
        d["breakdown"] = "; ".join(f"{k}={v}" for k, v in self.breakdown.items())
        return d


# ---------------- discovery ----------------
def search_places(business_type: str, area: str, api_key: str, max_results=40) -> list[dict]:
    out, token = [], None
    while len(out) < max_results:
        body = {"textQuery": f"{business_type} in {area}", "pageSize": 20, "regionCode": "IN"}
        if token:
            body["pageToken"] = token
        r = requests.post(PLACES_URL, json=body, timeout=20,
                          headers={"X-Goog-Api-Key": api_key, "X-Goog-FieldMask": FIELDS})
        if not r.ok:
            raise RuntimeError(f"Places API error {r.status_code}: {r.text[:300]}")
        data = r.json()
        out += data.get("places", [])
        token = data.get("nextPageToken")
        if not token:
            break
    return out[:max_results]


def parse_place(p: dict) -> LocalLead:
    return LocalLead(
        name=(p.get("displayName") or {}).get("text", ""),
        business_type=(p.get("primaryTypeDisplayName") or {}).get("text", ""),
        address=p.get("formattedAddress", ""), phone=p.get("nationalPhoneNumber", ""),
        website=p.get("websiteUri", ""), rating=float(p.get("rating") or 0),
        review_count=int(p.get("userRatingCount") or 0), status=p.get("businessStatus", ""),
        maps_id=p.get("id", ""), confidence={"phone": 0.95 if p.get("nationalPhoneNumber") else 0.0})


# ---------------- website enrichment ----------------
ROLE = r"(Co-?[Ff]ounder|Founder|Owner|Proprietor|Managing Director|Director|CEO|Chef Owner|Partner)"
NAME = r"((?:Dr\.?\s)?[A-Z][a-z]{1,15}(?:\s[A-Z]\.?)?(?:\s[A-Z][a-z]{1,15}){1,2})"
STOP = {"Our", "The", "Meet", "About", "Team", "Contact", "Welcome", "Read", "More", "Home", "Menu", "Book", "Call"}
GENERIC = ("info@", "contact@", "hello@", "support@", "sales@", "admin@", "enquiry@", "care@", "reservations@", "bookings@")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
BAD_EMAIL_END = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".css", ".js")


def _clean_name(n: str) -> str | None:
    words = n.split()
    return None if any(w in STOP for w in words) else n.strip()


def extract_owner(html: str) -> tuple[str, str] | None:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all("script", type="application/ld+json"):   # structured data first
        try:
            data = json.loads(tag.string or "")
        except Exception:
            continue
        for item in data if isinstance(data, list) else [data]:
            f = item.get("founder") if isinstance(item, dict) else None
            f = f[0] if isinstance(f, list) and f else f
            nm = f.get("name") if isinstance(f, dict) else f if isinstance(f, str) else None
            if nm and _clean_name(nm):
                return nm, "Founder"
    text = soup.get_text(" ", strip=True)
    pats = [rf"{NAME}\s*[,\-–|:(]+\s*(?:the\s)?{ROLE}", rf"{ROLE}\s*[:\-–|,]+\s*{NAME}",
            rf"(?:[Ff]ounded|[Oo]wned|[Rr]un|[Ll]ed)\s+by\s+{NAME}"]
    for i, pat in enumerate(pats):
        m = re.search(pat, text)
        if m:
            g = m.groups()
            name, role = (g[0], g[1]) if i == 0 else (g[1], g[0]) if i == 1 else (g[0], "Owner")
            if _clean_name(name):
                return name.strip(), role
    return None


def extract_emails(html: str, domain_hint: str = "") -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    found = [a["href"][7:].split("?")[0] for a in soup.select('a[href^="mailto:"]')]
    found += EMAIL_RE.findall(soup.get_text(" "))
    seen, out = set(), []
    for e in found:
        e = e.lower().strip()
        if e not in seen and EMAIL_RE.fullmatch(e) and not e.endswith(BAD_EMAIL_END):
            seen.add(e); out.append(e)
    out.sort(key=lambda e: (domain_hint not in e, e.startswith(GENERIC)))  # same-domain + personal first
    return out


def enrich_from_website(lead: LocalLead, fetcher: PoliteFetcher) -> LocalLead:
    if not lead.website:
        return lead
    base = lead.website.rstrip("/")
    host = re.sub(r"^https?://(www\.)?", "", base).split("/")[0]
    for path in ("", "/about", "/about-us", "/contact"):
        html = fetcher.get(base + path)
        if not html:
            continue
        if not lead.owner_name and (o := extract_owner(html)):
            lead.owner_name, lead.owner_role = o
            lead.confidence["owner"] = 0.6          # regex heuristic: verify before using
        if not lead.email and (emails := extract_emails(html, host.split(".")[0])):
            lead.email = emails[0]
            lead.confidence["email"] = 0.85 if host.split(".")[0] in emails[0] else 0.5
        if lead.owner_name and lead.email:
            break
    return lead


# ---------------- scoring ----------------
def score_local(l: LocalLead, business_type: str, area: str) -> LocalLead:
    why = []
    locality = area.split(",")[0].strip().lower()
    fit = 0.0
    if l.status in ("OPERATIONAL", ""): fit += 1
    if locality and locality in l.address.lower(): fit += 1; why.append(f"located in {area.split(',')[0]}")
    if any(w[:4] in (l.business_type + " " + l.name).lower() for w in business_type.lower().split()): fit += 1
    if l.website: fit += 1
    q = 0.0
    if l.rating >= 4.2: q += 1.5; why.append(f"{l.rating}★ rating")
    if l.review_count >= 100: q += 1.5; why.append(f"{l.review_count} reviews (established)")
    elif l.review_count >= 30: q += 0.75; why.append(f"{l.review_count} reviews")
    r = 0.0
    if l.owner_name: r += 1; why.append(f"owner found: {l.owner_name} ({l.owner_role})")
    if l.email: r += 0.5 if l.email.startswith(GENERIC) else 1; why.append(f"email {l.email}")
    if l.phone: r += 1; why.append("phone listed")
    l.breakdown = {"fit": min(fit, 4), "quality": min(q, 3), "reachability": min(r, 3)}
    l.score = max(1, min(10, round(sum(l.breakdown.values()))))
    txt = ", ".join(why) or "limited data"
    l.rationale = txt[0].upper() + txt[1:] + "."
    return l


# ---------------- pipeline + export ----------------
def run_local(business_type, area, api_key, max_results=40, scrape_sites=True, progress=None) -> list[LocalLead]:
    places = search_places(business_type, area, api_key, max_results)
    leads, seen = [], set()
    for p in places:
        l = parse_place(p)
        if l.maps_id in seen or l.status == "CLOSED_PERMANENTLY" or not l.name:
            continue
        seen.add(l.maps_id); leads.append(l)
    fetcher = PoliteFetcher(min_delay=1.5, retries=2) if scrape_sites else None
    for i, l in enumerate(leads):
        if fetcher:
            enrich_from_website(l, fetcher)
        score_local(l, business_type, area)
        if progress: progress((i + 1) / len(leads))
    return sorted(leads, key=lambda x: -x.score)


COLS = ["score", "name", "owner_name", "owner_role", "phone", "email", "website", "address", "business_type",
        "rating", "review_count", "rationale", "breakdown", "confidence", "rubric_version", "maps_id"]


def to_csv(leads: list[LocalLead], path: str):
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:   # utf-8-sig so Excel opens it cleanly
        w = csv.DictWriter(fh, fieldnames=COLS, extrasaction="ignore")
        w.writeheader()
        for l in leads:
            w.writerow(l.to_row())
