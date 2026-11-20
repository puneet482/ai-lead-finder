import os, pandas as pd, streamlit as st
from leadfinder.icp import parse_icp
from leadfinder.llm import LLM
from leadfinder.pipeline import run
from leadfinder.export import to_csv, COLS
from leadfinder.schema import ICPFilters
from leadfinder.storage import connect, save_run
from leadfinder.scoring import RUBRIC
from leadfinder import search
from leadfinder.diagnose import run_diagnostics

st.set_page_config(page_title="AI Lead Finder", layout="wide")
st.title("AI Lead Finder (MVP)")
llm = LLM()
st.caption(f"LLM: {'connected - ' + llm.model if llm.available else 'no API key - rule-based fallback'}")

tab_search, tab_b2b = st.tabs(["Search (any business or professional)", "B2B lead finder (sample data)"])

with tab_search:
    st.write("Type what you are looking for, e.g. **dentist in Mumbai**, **IT professors in Bangalore**, **gyms in Malad, Mumbai**.")
    q = st.text_input("Search", "dentist in Mumbai")
    c = st.columns(3)
    source = c[0].radio("Data source", ["auto", "google", "web", "osm"], horizontal=True,
                        format_func=lambda x: {"auto": "Auto", "google": "Google Places", "web": "Claude web search", "osm": "OpenStreetMap (free)"}[x])
    n = c[1].slider("Max results", 10, 60, 30, 10)
    scrape = c[2].checkbox("Read websites for owner / faculty details (slower)", True)
    key = st.text_input("Google Places API key (optional - leave empty to use free OpenStreetMap)",
                        value=os.getenv("GOOGLE_PLACES_API_KEY", ""), type="password")
    with st.expander("Check connections (shows which sources work from this computer)"):
        if st.button("Run checks"):
            for name, ok, detail in run_diagnostics(key or None, llm):
                (st.success if ok else st.warning)(f"{name}: {detail}")
    if st.button("Search", type="primary"):
        bar = st.progress(0.0, text="Starting...")
        try:
            res, stats = search.run_search(q, key or None, llm, n, scrape, source,
                                           progress=lambda p, m="": bar.progress(min(float(p), 1.0), text=m))
            st.session_state["search"] = (res, stats)
        except Exception as e:
            st.error(str(e))
        bar.empty()
    if "search" in st.session_state:
        res, stats = st.session_state["search"]
        st.subheader(f"{len(res)} results")
        st.caption(f"Source: {stats.get('source')} | " + " | ".join(f"{k}: {v}" for k, v in stats.items() if k not in ("intent", "source")))
        if not res:
            st.info("No results. Try the other data source, a broader query, or turn on website reading. "
                    "OpenStreetMap has sparse coverage in some areas; Google Places is more complete.")
        else:
            df = pd.DataFrame([r.to_row() for r in res])[search.COLS]
            st.dataframe(df, use_container_width=True, hide_index=True)
            st.download_button("Download CSV", df.to_csv(index=False, encoding="utf-8-sig"), "results.csv", "text/csv")
            st.caption("Names/emails are extracted from public pages and are heuristic - verify before outreach. "
                       "Use business/institutional contacts only and respect DND rules.")
        with st.expander("How this query was understood"):
            st.json(stats.get("intent", {}))

with tab_b2b:
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

