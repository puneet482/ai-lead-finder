"""Step 1: natural-language ICP -> validated structured filters."""
import re
from .llm import LLM
from .schema import ICPFilters, REGIONS, FUNDING_STAGES

SYSTEM = f"""You convert an Ideal Customer Profile into JSON filters. Return ONLY JSON with keys:
roles (list of lowercase job-title phrases), seniority (subset of: c-level, vp, director, manager, ic),
industries (list lowercase), funding_stages (subset of {FUNDING_STAGES}), countries (ISO-2 codes),
size_min (int|null), size_max (int|null), tech_stack (list lowercase). Use [] / null when unspecified. Never invent values."""

SENIORITY_WORDS = {"director": "director", "directors": "director", "vp": "vp", "vice president": "vp",
                   "head of": "director", "cto": "c-level", "ceo": "c-level", "cfo": "c-level",
                   "founder": "c-level", "manager": "manager", "managers": "manager"}
INDUSTRY_WORDS = ["fintech", "healthtech", "saas", "ecommerce", "edtech", "cybersecurity", "logistics", "ai"]
TECH_WORDS = ["python", "aws", "kubernetes", "react", "snowflake", "kafka", "postgres", "golang", "terraform"]
ROLE_WORDS = ["software engineering", "engineering", "data", "product", "sales", "marketing", "security", "devops", "infrastructure"]


def _fallback(icp: str) -> dict:
    t = icp.lower()
    out = {"roles": [], "seniority": [], "industries": [], "funding_stages": [], "countries": [],
           "size_min": None, "size_max": None, "tech_stack": []}
    for k, v in SENIORITY_WORDS.items():
        if re.search(rf"\b{re.escape(k)}\b", t) and v not in out["seniority"]:
            out["seniority"].append(v)
    out["roles"] = [r for r in ROLE_WORDS if r in t and not any(r in x and r != x for x in ROLE_WORDS if x in t)]
    out["industries"] = [i for i in INDUSTRY_WORDS if i in t]
    out["tech_stack"] = [x for x in TECH_WORDS if x in t]
    for s in FUNDING_STAGES:
        if s in t:
            out["funding_stages"].append(s)
    for k, codes in REGIONS.items():
        if re.search(rf"\b{re.escape(k)}\b", t):
            out["countries"] += [c for c in codes if c not in out["countries"]]
    m = re.search(r"(\d+)\s*[-–to]+\s*(\d+)\s*(employees|people|headcount)", t)
    if m:
        out["size_min"], out["size_max"] = int(m.group(1)), int(m.group(2))
    return out


def parse_icp(icp: str, llm: LLM | None = None) -> tuple[ICPFilters, list[str]]:
    """Returns (filters, validation_issues). UI lets the user edit before running."""
    data = None
    if llm and llm.available:
        try:
            data = llm.json(SYSTEM, icp)
        except Exception as e:  # network/JSON errors -> fallback
            print(f"[icp] LLM parse failed ({e}); using rule-based fallback")
    if data is None:
        data = _fallback(icp)
    f = ICPFilters(
        roles=[x.lower() for x in data.get("roles") or []],
        seniority=[x.lower() for x in data.get("seniority") or []],
        industries=[x.lower() for x in data.get("industries") or []],
        funding_stages=[x.lower() for x in data.get("funding_stages") or []],
        countries=[x.upper() for x in data.get("countries") or []],
        size_min=data.get("size_min"), size_max=data.get("size_max"),
        tech_stack=[x.lower() for x in data.get("tech_stack") or []],
        raw_icp=icp,
    )
    return f, f.validate()
