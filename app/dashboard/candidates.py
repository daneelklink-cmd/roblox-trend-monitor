from pathlib import Path
import json
import pandas as pd
import plotly.express as px
import streamlit as st
from app.config import ROOT
from app.database.session import utcnow
from app.analytics.research import CANDIDATES,candidate_metrics,compare_controls
from app.services.research import load_research,latest_groups,playtest_template
from app.services.research_exports import research_bundle
from app.reports.research import collection_health
from app.dashboard.timezone import berlin,local_frame,display_dataframe


def research_page(games,snapshots,appearances):
    st.subheader('Research Candidates')
    st.caption('Five pinned candidates · frozen observational controls · human playtests. Display: Europe/Berlin; storage and CSV: UTC. Independent of sidebar ranking filters.')
    groups,notes,watch,reports=load_research()
    active=latest_groups(groups)
    asof=snapshots.timestamp.max().floor('h') if len(snapshots) else pd.Timestamp(utcnow()).floor('h')
    metrics=candidate_metrics(games,snapshots,asof)
    st.caption(f'Latest observed hour: {berlin(asof)}. Missing readings remain blank. Creation is not verified launch.')
    if utcnow()-asof.to_pydatetime()>pd.Timedelta(hours=2):st.warning('Data is stale: latest observed hour is more than two hours old.')
    tracked=set(watch[watch.active].universe_id) if len(watch) else set()
    if not set(CANDIDATES).issubset(tracked):st.warning('One or more research candidates are not pinned in the watchlist; run the authenticated init-research command.')
    display_dataframe(metrics[['name','universe_id','ccu','delta_1h','pct_1h','delta_6h','pct_6h','delta_24h','pct_24h','delta_72h','pct_72h','avg_24h','peak_24h','historical_observed_peak_ccu','drawdown_pct','signal']],hide_index=True,width='stretch')
    st.caption('24h/72h changes compare the same Berlin wall hour on earlier local dates. 1h/6h use elapsed hours. New observed high and recovery below an earlier peak are distinct; neither proves a breakout. Daily means/peaks require ≥75% hourly coverage and a valid 24h boundary.')
    uid=st.selectbox('Inspect research candidate',list(CANDIDATES),format_func=lambda value:CANDIDATES[value])
    with st.expander('Visits, favorites, creation dates and full candidate measurements'):
        display_dataframe(metrics[metrics.universe_id==uid],hide_index=True,width='stretch')
    history=snapshots[snapshots.universe_id==uid].sort_values('timestamp')
    if len(history):
        st.plotly_chart(px.line(local_frame(history),x='timestamp',y='playing',markers=True,title='Observed hourly CCU · Europe/Berlin'),width='stretch',key='research_ccu')
    with st.expander('Discovery ranking history'):
        ranks=appearances[appearances.universe_id==uid].sort_values('timestamp')
        if len(ranks):
            figure=px.line(local_frame(ranks),x='timestamp',y='rank',color='source',markers=True)
            figure.update_yaxes(autorange='reversed')
            st.plotly_chart(figure,width='stretch',key='research_ranks')
            display_dataframe(ranks,hide_index=True,width='stretch')
        st.caption('Each source is separate. Missing appearances can mean off-list or incomplete discovery; they are not rank zero. Lines connect observed appearances only.')
    st.markdown('**Fixed control comparison**')
    if not active:
        st.info('Control manifests have not been initialized. They are selected explicitly once, never during a dashboard refresh.')
    else:
        comparison,details=compare_controls(snapshots,active,asof)
        display_dataframe(comparison[comparison.candidate_id==uid],hide_index=True,width='stretch')
        st.caption('Relative performance = candidate % change minus control median % change, in percentage points. It is shown only with ≥75% paired controls and at least 10 controls. Zero baselines have undefined percentages. No causal inference.')
        with st.expander('Frozen members, selection criteria and missing endpoint details'):
            group=next((g for g in active if g['candidate_id']==uid),None)
            if group:
                st.caption(f"Group {group['id']} · version {group['version']} · selected {berlin(group['selected_at'])}. Historical comparisons before selection are retrospective.")
                st.json(group['methodology'])
                display_dataframe(pd.DataFrame(group['members']),hide_index=True,width='stretch')
                display_dataframe(details[details.candidate_id==uid],hide_index=True,width='stretch')
    with st.expander('Manual playtest research — notes and CSV template'):
        display_dataframe(notes[notes.universe_id==uid],hide_index=True,width='stretch')
        st.caption('Human playtest notes are separate from classification labels and quantitative facts. Blank fields remain unknown. Complexity and marketing scores are subjective 1–5 assessments. Evidence and researcher/date are required; only enter mechanics you actually observed.')
        st.download_button('Download playtest CSV template',playtest_template().encode('utf-8-sig'),file_name='PlaytestTemplate.csv',mime='text/csv')
        st.code('cd /opt/roblox-trend-monitor\nset -a; . /etc/roblox-trend-monitor.env; set +a\n.venv/bin/python -m app.manage import-playtests /path/to/PlaytestTemplate.csv',language='bash')
        st.caption('Fill the template after playing, using an observation timestamp with Z or an explicit offset (e.g. 2026-10-20T12:00:00+02:00). Import through authenticated SSH. Public viewers cannot edit notes. Identical reimports are skipped; changed observations append a new evidence record.')
    with st.expander('72-hour research briefing · updated every 24 hours'):
        if reports:
            report=reports[0];path=Path(report['path'])
            st.caption(f"Generated {berlin(report['generated_at'])}. Hourly pipeline checks the 24h due time after each collection; update latency can be up to one collection interval.")
            if path.is_relative_to(ROOT/'reports') and path.exists():
                content=path.read_text(encoding='utf-8')
                st.download_button('Download latest research briefing',content,file_name=path.name,mime='text/markdown')
                st.markdown(content)
        else:st.info('No research briefing generated yet.')
    with st.expander('Monitoring integrity'):
        attempts,missing=collection_health()
        display_dataframe(attempts,hide_index=True,width='stretch')
        display_dataframe(missing[missing.universe_id.isin(CANDIDATES)] if len(missing) else missing,hide_index=True,width='stretch')
        expected=[]
        end=asof
        for candidate in CANDIDATES:
            h=snapshots[snapshots.universe_id==candidate]
            first=h.timestamp.min().floor('h') if len(h) else pd.NaT
            expected_bins=len(pd.date_range(first,end,freq='h')) if pd.notna(first) else 0
            actual=h[h.timestamp.dt.floor('h')<=end].timestamp.dt.floor('h').nunique()
            expected.append({'universe_id':candidate,'expected_hours_since_first_measurement':expected_bins,'observed_hours':actual,'missing_hours':expected_bins-actual})
        display_dataframe(pd.DataFrame(expected),hide_index=True,width='stretch')
        st.caption('Attempt summaries include failed requests, failed discovery sources, missing games and duration. Full source coverage remains in Discovery & Classification. Unavailable CCU never becomes zero.')
    if st.button('Generate research ZIP'):
        with st.spinner('Preparing candidates, frozen controls, measurements and playtests…'):
            _,bundle=research_bundle()
            st.session_state['candidate_research_zip']=bundle
    if 'candidate_research_zip' in st.session_state:
        st.download_button('Download research candidates ZIP',st.session_state['candidate_research_zip'],file_name='ResearchCandidates.zip',mime='application/zip',on_click='ignore')
        st.caption('Includes candidate/control metadata, all collected hourly history, analytics, comparison endpoints, frozen membership, playtests, missing observations and data definitions. Generate again to refresh the snapshot.')
