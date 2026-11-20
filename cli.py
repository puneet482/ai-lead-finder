import argparse, json
from leadfinder.icp import parse_icp
from leadfinder.llm import LLM
from leadfinder.pipeline import run
from leadfinder.export import to_csv
from leadfinder.storage import connect, save_run

ap = argparse.ArgumentParser()
ap.add_argument("icp"); ap.add_argument("--out", default="leads.csv")
ap.add_argument("--live", action="store_true", help="scrape live careers pages")
ap.add_argument("--yes", action="store_true", help="skip filter review prompt")
a = ap.parse_args()
llm = LLM()
f, issues = parse_icp(a.icp, llm)
print("Parsed filters:\n", json.dumps(f.to_dict(), indent=2)); [print("WARN:", i) for i in issues]
if not a.yes and input("Proceed? [y/N] ").lower() != "y":
    raise SystemExit("Aborted - edit your ICP and retry (or use the Streamlit UI to edit filters).")
leads = run(f, llm, live=a.live)
to_csv(leads, a.out); save_run(connect(), f, leads)
print(f"{len(leads)} leads -> {a.out} (scorer: {leads[0].scorer if leads else 'n/a'})")
for l in leads[:5]: print(f"  {l.score:>2}  {l.full_name} @ {l.company}: {l.rationale}")
