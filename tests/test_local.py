from leadfinder.local import parse_place, extract_owner, extract_emails, score_local

PLACE = {"id": "abc", "displayName": {"text": "Spice Villa"}, "formattedAddress": "Link Rd, Malad West, Mumbai 400064",
         "nationalPhoneNumber": "022 1234 5678", "websiteUri": "https://spicevilla.in", "rating": 4.4,
         "userRatingCount": 250, "businessStatus": "OPERATIONAL", "primaryTypeDisplayName": {"text": "Restaurant"}}

def test_parse_and_score():
    l = parse_place(PLACE)
    assert l.name == "Spice Villa" and l.review_count == 250
    score_local(l, "restaurants", "Malad, Mumbai")
    assert 1 <= l.score <= 10 and "Malad" in l.rationale

def test_owner_patterns():
    assert extract_owner("<p>Rakesh Sharma, Founder of Spice Villa</p>") == ("Rakesh Sharma", "Founder")
    assert extract_owner("<p>Owner: Anita Desai welcomes you</p>")[0] == "Anita Desai"
    assert extract_owner("<p>Our Team, Director of nothing</p>") is None
    ld = '<script type="application/ld+json">{"@type":"Restaurant","founder":{"name":"Vikram Joshi"}}</script>'
    assert extract_owner(ld) == ("Vikram Joshi", "Founder")

def test_emails_prefer_same_domain_personal():
    html = '<a href="mailto:info@spicevilla.in">x</a> rakesh@spicevilla.in logo@2x.png other@gmail.com'
    es = extract_emails(html, "spicevilla")
    assert es[0] == "rakesh@spicevilla.in" and "logo@2x.png" not in es
