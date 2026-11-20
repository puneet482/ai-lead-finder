"""Step 3: enrichment with per-field confidence.

Email: pattern inference (company's known pattern) + syntax + optional MX check.
We deliberately do NOT do SMTP RCPT probing (unreliable, can get your IP blocklisted).
Plug in Hunter/ZeroBounce in `verify_email_api` for production-grade verification.
"""
import re
from .schema import Lead
from .sources import COMPANIES, company_signals
from .http import PoliteFetcher

EMAIL_RE = re.compile(r"^[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}$")
RESERVED_TLDS = (".example", ".test", ".invalid", ".localhost")


def _slug(s: str) -> str:
    return re.sub(r"[^a-z]", "", s.lower())


def infer_email(name: str, domain: str, pattern: str) -> str:
    parts = [p for p in re.split(r"\s+", name.strip()) if p]
    first, last = _slug(parts[0]), _slug(parts[-1])
    return pattern.format(first=first, last=last, f=first[:1], l=last[:1]) + "@" + domain


def has_mx(domain: str) -> bool:
    if domain.endswith(RESERVED_TLDS):
        return False
    try:
        import dns.resolver
        return bool(list(dns.resolver.resolve(domain, "MX", lifetime=4)))
    except Exception:
        return False


def verify_email_api(email: str) -> float | None:
    """Hook for Hunter.io / ZeroBounce etc. Return confidence 0..1 or None if unavailable."""
    return None


def enrich(lead: Lead, fetcher: PoliteFetcher | None = None, verify_mx=False, live=False) -> Lead:
    meta = COMPANIES.get(lead.company)
    conf = lead.confidence
    # --- email ---
    pattern = meta[7] if meta else "{first}.{last}"
    pattern_known = bool(meta)  # in prod: pattern learned from >=2 verified addresses at the domain
    lead.email = infer_email(lead.full_name, lead.company_domain, pattern)
    c = 0.55 if pattern_known else 0.30
    if not EMAIL_RE.match(lead.email):
        c, lead.email = 0.0, ""
    elif verify_mx and has_mx(lead.company_domain):
        c += 0.20
    api = verify_email_api(lead.email) if lead.email else None
    if api is not None:
        c = max(c, api)
    conf["email"] = round(min(c, 0.95), 2)
    # --- phone: not available from public sources in this MVP ---
    lead.phone, conf["phone"] = "", 0.0
    # --- company metadata (mock source is a curated snapshot) ---
    conf["company_meta"] = 0.8 if meta else 0.4
    # --- hiring signals ---
    if live and fetcher:
        sig = company_signals(lead.company_domain, fetcher)
        if sig:
            lead.open_roles, lead.hiring_titles = sig["open_roles"], sig["titles"]
            lead.tech_stack = sorted(set(lead.tech_stack) | set(sig["tech"]))
            conf["hiring"] = 0.9
            return lead
    if meta:  # offline: use snapshot of careers page
        lead.hiring_titles = list(meta[8])[:10]
        lead.open_roles = len(meta[8])
        conf["hiring"] = 0.6
    else:
        conf["hiring"] = 0.0
    return lead
