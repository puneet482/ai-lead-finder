import pytest
from leadfinder.search import (parse_query, extract_people, find_people_pages, build_overpass, osm_tags_for,
                               parse_osm_element, run_search, role_matches, bbox_from_photon)
from leadfinder.local import LocalLead

FACULTY = """<html><body><h2>Faculty - Department of Information Technology</h2>
<div><h4>Dr. Anita Rao</h4><p>Associate Professor</p><p>anita.rao@bmsce.example.edu</p></div>
<div><h4>Prof. Suresh Kumar</h4><p>Assistant Professor</p><p>Email: suresh@bmsce.example.edu</p></div>
<div><h4>Dr. Meera Iyer</h4><p>Head of Department</p></div>
<p>Our campus has great facilities and many students enrolled every year in our programmes.</p></body></html>"""
HOME = '<a href="/academics/it-department/faculty">IT Faculty</a><a href="https://other.com/faculty">x</a><a href="/about">About</a>'


def test_intent_rules():
    i = parse_query("dentist in mumbai")
    assert (i.kind, i.target, i.location) == ("business", "dentist", "mumbai")
    j = parse_query("IT professors in banglore")
    assert (j.kind, j.target, j.field, j.location) == ("people", "professor", "it", "banglore")
    assert "engineering" in j.org_query
    with pytest.raises(ValueError):
        parse_query("dentist")


def test_extract_people_regex():
    p = {x["name"]: x for x in extract_people(FACULTY)}
    assert p["Anita Rao"]["title"] == "Associate Professor" and p["Anita Rao"]["email"] == "anita.rao@bmsce.example.edu"
    assert p["Suresh Kumar"]["email"] == "suresh@bmsce.example.edu"
    assert "Meera Iyer" in p and role_matches("Associate Professor", "professor") and not role_matches("Head of Department", "professor")


def test_find_pages_same_domain_and_field():
    pages = find_people_pages(HOME, "https://www.bmsce.example.edu", "it")
    assert pages[0].endswith("/academics/it-department/faculty") and all("other.com" not in u for u in pages)


def test_osm():
    assert ("amenity", "dentist") in osm_tags_for("dentist")
    assert ("amenity", "college") in osm_tags_for("engineering colleges")
    assert "nwr" in build_overpass(osm_tags_for("gym"), (1, 2, 3, 4))
    l = parse_osm_element({"type": "node", "id": 5, "tags": {"name": "Smile Dental", "amenity": "dentist", "phone": "+91 22 1111", "website": "smile.in"}}, "Mumbai")
    assert l.website == "https://smile.in" and l.phone.startswith("+91") and "Mumbai" in l.address
    assert parse_osm_element({"type": "node", "id": 6, "tags": {}}, "Mumbai") is None


class FakeFetcher:
    def get(self, url):
        return {"https://bmsce.example.edu": HOME, "https://bmsce.example.edu/academics/it-department/faculty": FACULTY}.get(url)


def test_end_to_end_people_and_business():
    org = LocalLead(name="BMS College", website="https://bmsce.example.edu", address="Bull Temple Rd, Bangalore", rating=4.3,
                    review_count=900, phone="080 1234", maps_id="x1")
    res, stats = run_search("IT professors in Bangalore", org_finder=lambda *a: ([org], "osm"), fetcher=FakeFetcher())
    names = [c.name for c in res]
    assert "Anita Rao" in names and "Meera Iyer" not in names and stats["people_found"] == 2
    assert res[0].score >= res[-1].score and all(1 <= c.score <= 10 for c in res)
    d = LocalLead(name="Smile Dental", website="", address="Malad, Mumbai", phone="022 5", maps_id="d1", business_type="Dentist")
    res, st = run_search("dentist in Mumbai", org_finder=lambda *a: ([d], "osm"), scrape=False)
    assert res[0].organization == "Smile Dental" and res[0].kind == "business"


def test_photon_bbox():
    d = {"features": [{"properties": {"extent": [72.7, 19.3, 73.0, 18.9]}, "geometry": {"coordinates": [72.8, 19.0]}}]}
    assert bbox_from_photon(d) == (18.9, 19.3, 72.7, 73.0)
    d2 = {"features": [{"properties": {}, "geometry": {"coordinates": [77.5, 12.9]}}]}
    s_, n_, w_, e_ = bbox_from_photon(d2)
    assert s_ < 12.9 < n_ and w_ < 77.5 < e_ and bbox_from_photon({"features": []}) is None
