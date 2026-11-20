"""Discovery connectors -> normalized Lead records.

1. MockLinkedIn: synthetic, ToS-safe stand-in for a LinkedIn/Sales Navigator export.
2. company_signals(): live scraper of a company's /careers page (hiring + tech signals).
"""
from bs4 import BeautifulSoup
from .schema import Lead, ICPFilters
from .http import PoliteFetcher

# name: (domain, industry, stage, headcount, country, funding_days_ago, tech, email_pattern, careers_titles)
COMPANIES = {
    "Paylyt":     ("paylyt.example", "fintech", "series b", 180, "US", 70, ["python", "aws", "kafka"], "{first}.{last}", ["Senior Backend Engineer", "SRE", "Staff Engineer", "Data Engineer", "Engineering Manager", "Security Engineer"]),
    "LedgerLoop": ("ledgerloop.example", "fintech", "series b", 240, "CA", 400, ["golang", "kubernetes", "postgres"], "{f}{last}", ["Backend Engineer"]),
    "Finara":     ("finara.example", "fintech", "series a", 60, "US", 120, ["python", "react"], "{first}", []),
    "CoinCradle": ("coincradle.example", "fintech", "series b", 310, "GB", 90, ["python", "aws"], "{first}.{last}", ["Platform Engineer", "Backend Engineer", "QA Engineer"]),
    "Medisync":   ("medisync.example", "healthtech", "series b", 150, "US", 60, ["python", "aws"], "{first}.{last}", ["Full-Stack Engineer", "Data Scientist"]),
    "Shipwell2":  ("shipwell2.example", "logistics", "series c", 900, "US", 200, ["java", "aws"], "{first}.{last}", ["Engineer"] * 4),
    "Vaultic":    ("vaultic.example", "fintech", "series b", 200, "US", 45, ["golang", "terraform", "aws"], "{first}.{last}", ["DevOps Engineer", "Security Engineer", "Staff Engineer", "Backend Engineer", "Engineering Manager"]),
    "Brightwave": ("brightwave.example", "edtech", "seed", 25, "IN", 300, ["react"], "{first}", []),
}
# (name, title, company, activity_days_ago, recent_post)
PEOPLE = [
    ("Dana Whitfield", "Director of Software Engineering", "Paylyt", 6, "We're scaling our payments platform team - hiring across backend and SRE."),
    ("Marcus Oyelaran", "VP Engineering", "Paylyt", 40, "Proud of the team shipping our new ledger service."),
    ("Priya Nair", "Engineering Director", "LedgerLoop", 120, ""),
    ("Tom Alvarez", "Head of Engineering", "Finara", 15, "Just closed our seed extension, hiring soon!"),
    ("Helen Park", "Director, Software Engineering", "CoinCradle", 20, "Excited to open our new engineering hub."),
    ("Raj Mehta", "Director of Engineering", "Medisync", 10, "Our new HIPAA-compliant API just launched."),
    ("Sofia Reyes", "Director of Engineering", "Shipwell2", 5, "Great quarter for the platform org."),
    ("Ben Carter", "Senior Software Engineer", "Paylyt", 3, "Debugging Kafka consumers all day."),
    ("Lena Fischer", "Director of Software Engineering", "Vaultic", 2, "We just raised our Series B - and we're hiring engineers and security folks!"),
    ("Arjun Kapoor", "Director of Engineering", "Brightwave", 8, "Launching our new learner app."),
    ("Chloe Dubois", "Software Engineering Director", "LedgerLoop", 200, ""),
    ("Jamal Brooks", "CTO", "Vaultic", 30, "Launching a new fraud-detection product next month."),
]


def mock_linkedin(_: ICPFilters | None = None) -> list[Lead]:
    leads = []
    for name, title, co, act, post in PEOPLE:
        dom, ind, stage, hc, cc, fund, tech, _pat, _roles = COMPANIES[co]
        leads.append(Lead(
            full_name=name, title=title, company=co, company_domain=dom, country=cc,
            industry=ind, funding_stage=stage, headcount=hc, last_funding_days_ago=fund,
            tech_stack=list(tech), linkedin_url=f"https://linkedin.example/in/{name.lower().replace(' ', '-')}",
            source="mock_linkedin", last_activity_days_ago=act, recent_post=post))
    return leads


def role_match(role: str, title: str) -> bool:
    """Token match ignoring generic qualifiers, so 'software engineering' matches 'Engineering Director'."""
    stop = {"software", "of", "the", "and", ","}
    toks = [w.strip(",") for w in role.lower().split() if w not in stop]
    title_l = title.lower()
    return all(w[:6] in title_l for w in toks) if toks else True


def matches_icp(l: Lead, f: ICPFilters) -> bool:
    """Hard filters on company-level attributes + role/seniority."""
    t = l.title.lower()
    if f.industries and l.industry not in f.industries: return False
    if f.funding_stages and l.funding_stage not in f.funding_stages: return False
    if f.countries and l.country not in f.countries: return False
    if f.size_min and l.headcount < f.size_min: return False
    if f.size_max and l.headcount > f.size_max: return False
    sen_kw = {"director": ["director", "head of"], "vp": ["vp", "vice president"],
              "c-level": ["cto", "ceo", "cfo", "chief", "founder"], "manager": ["manager"],
              "ic": ["engineer", "analyst", "developer"]}
    sen_ok = not f.seniority or any(k in t for s in f.seniority for k in sen_kw.get(s, [s]))
    role_ok = not f.roles or any(role_match(r, l.title) for r in f.roles)
    return sen_ok and role_ok


# ---------- live careers-page scraper ----------
TECH = ["python", "golang", "java", "react", "kubernetes", "aws", "kafka", "postgres", "terraform", "snowflake"]


def parse_careers_html(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    titles = [h.get_text(" ", strip=True) for h in soup.select("h2, h3, li a, .job-title")]
    titles = [t for t in titles if any(k in t.lower() for k in ("engineer", "developer", "scientist", "sre", "devops"))]
    text = soup.get_text(" ").lower()
    return {"open_roles": len(titles), "titles": titles[:10], "tech": [t for t in TECH if t in text]}


def company_signals(domain: str, fetcher: PoliteFetcher) -> dict | None:
    for path in ("/careers", "/jobs"):
        html = fetcher.get(f"https://{domain}{path}")
        if html:
            return parse_careers_html(html)
    return None
