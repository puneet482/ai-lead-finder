import argparse, os
from leadfinder.local import run_local, to_csv

ap = argparse.ArgumentParser()
ap.add_argument("business_type", help='e.g. "restaurants", "gyms", "chartered accountants"')
ap.add_argument("--area", default="Malad, Mumbai")
ap.add_argument("--max", type=int, default=40)
ap.add_argument("--no-scrape", action="store_true", help="skip website visits (faster, no owner/email)")
ap.add_argument("--out", default="local_leads.csv")
a = ap.parse_args()
key = os.getenv("GOOGLE_PLACES_API_KEY")
if not key:
    raise SystemExit("Set GOOGLE_PLACES_API_KEY first (see README).")
leads = run_local(a.business_type, a.area, key, a.max, not a.no_scrape)
to_csv(leads, a.out)
print(f"{len(leads)} businesses -> {a.out}")
for l in leads[:8]:
    print(f"{l.score:>2}  {l.name} | {l.owner_name or '-'} | {l.phone or '-'} | {l.email or '-'}")
