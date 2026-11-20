import csv
from .schema import Lead

COLS = ["score", "full_name", "title", "company", "company_domain", "email", "phone", "country", "industry",
        "funding_stage", "headcount", "last_funding_days_ago", "open_roles", "hiring_titles", "tech_stack",
        "linkedin_url", "last_activity_days_ago", "recent_post", "rationale", "score_breakdown", "confidence",
        "rubric_version", "scorer", "source"]


def to_csv(leads: list[Lead], path: str):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS, extrasaction="ignore")
        w.writeheader()
        for l in sorted(leads, key=lambda x: -x.score):
            w.writerow(l.to_row())


def to_hubspot_payload(l: Lead) -> dict:
    """Mock CRM mapping (HubSpot contacts API shape). POST to /crm/v3/objects/contacts with a sandbox token."""
    first, _, last = l.full_name.partition(" ")
    return {"properties": {"firstname": first, "lastname": last, "email": l.email, "jobtitle": l.title,
                           "company": l.company, "lead_score": l.score, "lead_score_rationale": l.rationale}}
