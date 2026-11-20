from leadfinder.icp import parse_icp
from leadfinder.enrich import infer_email
from leadfinder.sources import parse_careers_html, mock_linkedin, matches_icp
from leadfinder.pipeline import run
from leadfinder.schema import ICPFilters

ICP = "software engineering directors at Series B fintech startups in North America"

def test_icp_fallback():
    f, issues = parse_icp(ICP)
    assert "director" in f.seniority and "fintech" in f.industries
    assert "series b" in f.funding_stages and {"US", "CA"} <= set(f.countries) and not issues

def test_validation():
    assert ICPFilters(funding_stages=["series zz"]).validate()

def test_email_patterns():
    assert infer_email("Dana Whitfield", "x.com", "{first}.{last}") == "dana.whitfield@x.com"
    assert infer_email("Priya Nair", "x.com", "{f}{last}") == "pnair@x.com"

def test_careers_parser():
    html = "<h3>Senior Backend Engineer</h3><h3>Office Manager</h3><p>We use Python and AWS</p>"
    r = parse_careers_html(html)
    assert r["open_roles"] == 1 and set(r["tech"]) == {"python", "aws"}

def test_end_to_end_ranks_and_filters():
    f, _ = parse_icp(ICP)
    leads = run(f)
    assert leads and all(l.industry == "fintech" and l.country in ("US", "CA") for l in leads)
    assert all(1 <= l.score <= 10 and l.rationale for l in leads)
    assert leads[0].score >= leads[-1].score
    assert not any(l.title == "Senior Software Engineer" for l in leads)
