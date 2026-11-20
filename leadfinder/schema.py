"""Common schemas: ICP filters and the normalized Lead record."""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Optional

REGIONS = {
    "north america": ["US", "CA", "MX"],
    "united states": ["US"], "usa": ["US"], "us": ["US"],
    "canada": ["CA"], "europe": ["GB", "DE", "FR", "NL", "ES", "IE", "SE"],
    "uk": ["GB"], "india": ["IN"], "apac": ["IN", "SG", "AU", "JP"],
}
FUNDING_STAGES = ["pre-seed", "seed", "series a", "series b", "series c", "series d+", "public", "bootstrapped"]


@dataclass
class ICPFilters:
    roles: list[str] = field(default_factory=list)          # e.g. ["engineering director"]
    seniority: list[str] = field(default_factory=list)      # e.g. ["director", "vp"]
    industries: list[str] = field(default_factory=list)
    funding_stages: list[str] = field(default_factory=list)
    countries: list[str] = field(default_factory=list)      # ISO-2
    size_min: Optional[int] = None
    size_max: Optional[int] = None
    tech_stack: list[str] = field(default_factory=list)
    raw_icp: str = ""

    def validate(self) -> list[str]:
        issues = []
        if not self.roles and not self.seniority:
            issues.append("No role or seniority given - results will be unfocused.")
        bad = [s for s in self.funding_stages if s.lower() not in FUNDING_STAGES]
        if bad:
            issues.append(f"Unknown funding stages: {bad}. Allowed: {FUNDING_STAGES}")
        bad_c = [c for c in self.countries if len(c) != 2 or not c.isalpha()]
        if bad_c:
            issues.append(f"Countries must be ISO-2 codes, got: {bad_c}")
        if self.size_min and self.size_max and self.size_min > self.size_max:
            issues.append("size_min is greater than size_max.")
        return issues

    def to_dict(self):
        return asdict(self)


@dataclass
class Lead:
    full_name: str
    title: str
    company: str
    company_domain: str
    country: str
    industry: str
    funding_stage: str
    headcount: int
    last_funding_days_ago: Optional[int] = None
    tech_stack: list[str] = field(default_factory=list)
    linkedin_url: str = ""
    source: str = ""
    last_activity_days_ago: Optional[int] = None
    recent_post: str = ""
    # enrichment
    email: str = ""
    phone: str = ""
    open_roles: int = 0
    hiring_titles: list[str] = field(default_factory=list)
    confidence: dict[str, float] = field(default_factory=dict)  # per-field, 0..1
    # scoring
    score: int = 0
    score_breakdown: dict[str, float] = field(default_factory=dict)
    rationale: str = ""
    rubric_version: str = ""
    scorer: str = ""

    def to_row(self) -> dict:
        d = asdict(self)
        d["tech_stack"] = "; ".join(self.tech_stack)
        d["hiring_titles"] = "; ".join(self.hiring_titles)
        d["confidence"] = "; ".join(f"{k}={v:.2f}" for k, v in self.confidence.items())
        d["score_breakdown"] = "; ".join(f"{k}={v}" for k, v in self.score_breakdown.items())
        return d
