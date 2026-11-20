"""Step 4: versioned rubric + LLM scoring with explainability.

The LLM scores the three components; code sums & clamps them so the total is auditable.
If the LLM is unavailable (or returns junk) a deterministic heuristic applies the same rubric.
"""
import json
from .schema import Lead, ICPFilters
from .llm import LLM
from .sources import role_match

RUBRIC = {
    "version": "1.0.0",
    "components": {
        "fit":     {"max": 4, "desc": "Role/seniority match, industry, funding stage, geography, size, tech overlap with the ICP."},
        "intent":  {"max": 4, "desc": "Buying signals: funding <=180d (strong), hiring volume/relevance, product launches, relevant posts."},
        "recency": {"max": 2, "desc": "Lead's own activity: <=30d=2, <=90d=1, <=180d=0.5, older=0."},
    },
    "total": "round(fit + intent + recency), clamped to 1..10",
}

SYSTEM = f"""You are a B2B lead-scoring analyst. Score ONE lead against the ICP using rubric v{RUBRIC['version']}:
{json.dumps(RUBRIC['components'], indent=1)}
Rules: only use facts in the lead JSON; do not invent signals; missing data scores 0 for that signal.
Return ONLY JSON: {{"fit": float, "intent": float, "recency": float, "rationale": "2-3 sentences citing specific evidence"}}"""


def _heuristic(l: Lead, f: ICPFilters) -> tuple[dict, str]:
    why, t = [], l.title.lower()
    fit = 0.0
    if any(role_match(r, l.title) for r in f.roles) or not f.roles: fit += 1.5; why.append(f"title '{l.title}' matches target role")
    if f.seniority and any(s in t for s in f.seniority): fit += 1.0; why.append("seniority matches")
    elif "vp" in t or "director" in t or "head" in t: fit += 0.5
    fit += 0.5 + (0.5 if l.funding_stage in f.funding_stages else 0) + (0.5 if set(f.tech_stack) & set(l.tech_stack) else 0)
    intent = 0.0
    d = l.last_funding_days_ago
    if d is not None and d <= 180: intent += 1.5; why.append(f"funded {d}d ago")
    elif d is not None and d <= 365: intent += 0.75
    if l.open_roles >= 5: intent += 1.5; why.append(f"{l.open_roles} open roles")
    elif l.open_roles >= 1: intent += 0.75; why.append(f"{l.open_roles} open role(s)")
    p = l.recent_post.lower()
    if any(k in p for k in ("hiring", "launch", "raised", "scaling", "new")): intent += 1.0; why.append("recent post signals growth/launch")
    a = l.last_activity_days_ago
    rec = 2.0 if a is not None and a <= 30 else 1.0 if a is not None and a <= 90 else 0.5 if a is not None and a <= 180 else 0.0
    if a is not None: why.append(f"last active {a}d ago")
    comp = {"fit": min(fit, 4), "intent": min(intent, 4), "recency": rec}
    return comp, "; ".join(why).capitalize() + "."


def score_lead(l: Lead, f: ICPFilters, llm: LLM | None = None) -> Lead:
    comp, why, scorer = None, "", "heuristic"
    if llm and llm.available:
        try:
            payload = {k: v for k, v in l.to_row().items() if k not in ("score", "rationale", "score_breakdown")}
            r = llm.json(SYSTEM, f"ICP: {json.dumps(f.to_dict())}\nLEAD: {json.dumps(payload)}")
            comp = {k: max(0.0, min(float(r[k]), RUBRIC["components"][k]["max"])) for k in RUBRIC["components"]}
            why, scorer = str(r["rationale"]), f"llm:{llm.model}"
        except Exception as e:
            print(f"[score] LLM failed for {l.full_name} ({e}); using heuristic")
    if comp is None:
        comp, why = _heuristic(l, f)
    l.score_breakdown = {k: round(v, 2) for k, v in comp.items()}
    l.score = max(1, min(10, round(sum(comp.values()))))
    l.rationale, l.rubric_version, l.scorer = why, RUBRIC["version"], scorer
    return l
