import json, pandas as pd, streamlit as st
from leadfinder.icp import parse_icp
from leadfinder.llm import LLM
from leadfinder.pipeline import run
from leadfinder.export import to_csv, COLS
from leadfinder.schema import ICPFilters
from leadfinder.storage import connect, save_run
from leadfinder.scoring import RUBRIC

st.set_page_config(page_title="AI Lead Finder", layout="wide")
st.title("AI Lead Finder (MVP)")
llm = LLM()
st.caption(f"LLM: {'connected - ' + llm.model if llm.available else 'no API key - rule-based fallback'} | rubric v{RUBRIC['version']}")

icp = st.text_area("Describe your ideal customer", "software engineering directors at Series B fintech startups in North America", height=80)
if st.button("1. Parse ICP"):
    f, issues = parse_icp(icp, llm)
    st.session_state["filters"], st.session_state["issues"] = f, issues

if "filters" in st.session_state:
    f: ICPFilters = st.session_state["filters"]
    st.subheader("2. Review & edit filters")
    for i in st.session_state["issues"]: st.warning(i)
    c = st.columns(3)
    lst = lambda s: [x.strip().lower() for x in s.split(",") if x.strip()]
    f.roles = lst(c[0].text_input("Roles", ", ".join(f.roles)))
    f.seniority = lst(c[0].text_input("Seniority", ", ".join(f.seniority)))
    f.industries = lst(c[1].text_input("Industries", ", ".join(f.industries)))
    f.funding_stages = lst(c[1].text_input("Funding stages", ", ".join(f.funding_stages)))
    f.countries = [x.upper() for x in lst(c[2].text_input("Countries (ISO-2)", ", ".join(f.countries)))]
    f.tech_stack = lst(c[2].text_input("Tech stack", ", ".join(f.tech_stack)))
    live = st.checkbox("Live-scrape company careers pages (respects robots.txt, rate-limited)")
    if st.button("3. Run agent", type="primary"):
        if f.validate(): st.error(f.validate())
        else:
            with st.spinner("Discovering, enriching, scoring..."):
                leads = run(f, llm, live=live)
            save_run(connect(), f, leads); to_csv(leads, "leads.csv")
            st.session_state["leads"] = leads

if "leads" in st.session_state:
    leads = st.session_state["leads"]
    st.subheader(f"Results: {len(leads)} leads")
    df = pd.DataFrame([l.to_row() for l in leads])[COLS]
    st.dataframe(df, use_container_width=True, hide_index=True)
    st.download_button("Download CSV", df.to_csv(index=False), "leads.csv", "text/csv")
    with st.expander("Scoring rubric"): st.json(RUBRIC)
