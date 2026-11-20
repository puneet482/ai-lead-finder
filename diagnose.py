import os
from leadfinder.diagnose import run_diagnostics
from leadfinder.llm import LLM

for name, ok, detail in run_diagnostics(os.getenv("GOOGLE_PLACES_API_KEY"), LLM()):
    print(("PASS " if ok else "FAIL ") + name + " - " + detail)
