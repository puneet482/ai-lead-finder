# AI Lead Finder Agent (MVP)

Natural-language ICP -> structured filters (LLM) -> discovery -> enrichment -> LLM scoring with rationale -> CSV / CRM payload.

## Run
```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=...        # optional; without it a deterministic fallback is used
streamlit run app.py                # UI: parse -> edit filters -> run -> download CSV
python cli.py "software engineering directors at Series B fintech startups in North America" --yes
python -m pytest -q
```

## Architecture
```
ICP text --> icp.py (LLM JSON -> ICPFilters, validate, user edits in UI)
          --> sources.py  [mock_linkedin (ToS-safe) | company /careers scraper]  -> common Lead schema
          --> filter (matches_icp) + dedupe
          --> enrich.py   email pattern inference + syntax + optional MX (+ API hook), hiring signals,
                          per-field confidence
          --> scoring.py  rubric v1.0.0: fit(0-4) + intent(0-4) + recency(0-2); LLM scores components,
                          code sums/clamps; rationale mandatory; heuristic fallback
          --> storage.py (SQLite) / export.py (CSV, HubSpot payload mapping)
```
Key decisions
- **LLM never does arithmetic**: it returns component scores + evidence; code computes the total, so scores are auditable and the rubric is versioned (`RUBRIC["version"]`, stored per lead).
- **Compliance**: LinkedIn is mocked (scraping violates ToS). Live scraping uses honest UA, robots.txt, per-host delay, backoff, 429 handling. No CAPTCHA/anti-bot evasion.
- **Email**: no SMTP probing. Confidence = 0.55 (known company pattern) +0.20 (MX exists), overridden by a verification API when wired in (`verify_email_api`).
- **Graceful degradation**: every LLM call has a rule-based fallback, so the demo never breaks.

## Known limitations / next steps
- Mock LinkedIn data is synthetic (`.example` domains, so MX is skipped); swap `mock_linkedin` for a licensed provider (Apollo/PDL) or Google Places connector.
- Phone numbers not enriched (needs a paid provider).
- Email patterns are per-company snapshots, not learned from verified addresses.
- No eval set yet: next step is ~50 hand-labelled leads to measure score vs. human ranking (Spearman) and compare LLM vs. heuristic.
- Bonus not done: live HubSpot sync (payload mapper exists), cold-message queue with send limits.

## running instructions :- 
navigate to file
C:\Users\Puneet Hindlekar\Documents\Internship_assignments\leadfinder\leadfinder
activate vm 
.venv\Scripts\activate
install packages 
python -m pip install -r requirements.txt
set up claude key(optional)
Run on steamlit 
python -m streamlit run app.py