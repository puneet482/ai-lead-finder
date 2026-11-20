from .schema import ICPFilters, Lead
from .sources import mock_linkedin, matches_icp
from .enrich import enrich
from .scoring import score_lead
from .http import PoliteFetcher
from .llm import LLM


def run(filters: ICPFilters, llm: LLM | None = None, live=False, verify_mx=False, limit=50) -> list[Lead]:
    fetcher = PoliteFetcher() if live else None
    seen, leads = set(), []
    for l in mock_linkedin(filters):                       # source 1 (add more connectors here)
        if matches_icp(l, filters) and (l.full_name, l.company) not in seen:   # dedupe
            seen.add((l.full_name, l.company)); leads.append(l)
    leads = leads[:limit]
    for l in leads:
        enrich(l, fetcher, verify_mx=verify_mx, live=live)  # source 2: live careers-page scrape
        score_lead(l, filters, llm)
    return sorted(leads, key=lambda x: -x.score)
