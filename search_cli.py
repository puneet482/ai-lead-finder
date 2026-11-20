import argparse, os
from leadfinder.search import run_search, to_csv
from leadfinder.llm import LLM

ap = argparse.ArgumentParser()
ap.add_argument("query", help='e.g. "dentist in Mumbai" or "IT professors in Bangalore"')
ap.add_argument("--source", choices=["auto", "google", "osm"], default="auto")
ap.add_argument("--max", type=int, default=30)
ap.add_argument("--no-scrape", action="store_true")
ap.add_argument("--out", default="search_results.csv")
a = ap.parse_args()
contacts, stats = run_search(a.query, os.getenv("GOOGLE_PLACES_API_KEY"), LLM(), a.max, not a.no_scrape, a.source)
to_csv(contacts, a.out)
print(stats)
print(f"{len(contacts)} results -> {a.out}")
for c in contacts[:10]:
    print(f"{c.score:>2}  {c.name or '-'} | {c.role or '-'} | {c.organization} | {c.phone or '-'} | {c.email or '-'}")
