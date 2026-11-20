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

## Local businesses (e.g. Malad, Mumbai)
1. Google Cloud Console -> create project -> enable **Places API (New)** -> Credentials -> **Create API key** (billing must be enabled; Google gives a monthly free credit - check current pricing). Restrict the key to Places API.
2. PowerShell: `$env:GOOGLE_PLACES_API_KEY="your-key"`
3. UI: `python -m streamlit run app.py` -> "Local businesses" tab. CLI: `python local_cli.py "restaurants" --area "Malad, Mumbai"`
Rubric `local-1.0.0`: fit(0-4) + quality(0-3) + reachability(0-3). Owner names come from the business's own site (JSON-LD / "Founder:", "Owned by" patterns) and are heuristic (confidence 0.6).
Use business contact details only; respect TRAI DND rules for calls/SMS.

## Free-form search (new)
`python search_cli.py "dentist in Mumbai"` / `python search_cli.py "IT professors in Bangalore" --source osm`
- **Business queries** -> Google Places (if `GOOGLE_PLACES_API_KEY` set) or free OpenStreetMap -> website read for owner/email -> rubric `local-1.0.0`.
- **People queries (professors etc.)** -> find institutions -> locate faculty/department pages -> extract name/title/email
  (Claude when a key is set, regex fallback; LLM output is validated against the page text) -> rubric `people-1.0.0`.
- Limits: static HTML only (JS-rendered faculty pages need Playwright), OSM coverage is patchy in India, emails are often hidden.

## Data sources (pick what works on your network)
| Source | Needs | Notes |
|---|---|---|
| Google Places | `GOOGLE_PLACES_API_KEY` | Most complete & dependable for India; business listings + phone + website |
| Claude web search | `ANTHROPIC_API_KEY` | Works for businesses AND people (professors); every result carries a source URL; no map services needed |
| OpenStreetMap | nothing | Free but patchy, may be blocked on some networks |
`Auto` picks Google if a key is set, else Claude web search if a Claude key is set, else OpenStreetMap.
Run `python diagnose.py` (or the "Check connections" box in the app) to see which sources work from your machine.
