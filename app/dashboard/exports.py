"""Explicit export generation avoids recalculating bundles on every UI rerun."""
from datetime import datetime, time, timedelta
import pandas as pd
import streamlit as st
from app.analytics.queries import load_data
from app.database.session import utcnow
from app.database.session import database
from app.database.models import Game
from sqlalchemy import select
from app.services.exports import build_exports


def export_page():
    st.subheader('Research data exports')
    st.caption('Full stored data, independent of sidebar ranking filters. All timestamps and date boundaries use UTC.')
    with st.form('research_export_form'):
        include_archived = st.checkbox('Include archived games',value=True)
        use_period = st.checkbox('Limit observation period',value=False)
        today = utcnow().date()
        period = st.date_input('Observation date range (UTC; used only when enabled)',
            value=(today-timedelta(days=30),today),max_value=today)
        # Metadata lookup is cheap compared with generating all analytics/ZIPs.
        games = export_metadata()
        genres = st.multiselect('Export primary genres (empty = all)',sorted(games.primary_genre.fillna('(Unknown)').unique()))
        left,right = st.columns(2)
        minimum = left.number_input('Export minimum creation age / days',min_value=0,value=0)
        maximum = right.number_input('Export maximum creation age / days (0 = any)',min_value=0,value=0)
        followup = st.selectbox('Export cohort follow-up / hours',[24,72,168,720])
        horizon = st.selectbox('Export market analysis horizon',['24h','72h','7d','30d'])
        submitted = st.form_submit_button('Generate exports')
    st.caption('Age is measured at the selected end date, or now for all history. Analytics may use earlier baselines. Games metadata reflects the current stored state. Changing filters requires Generate exports again.')
    if submitted:
        if use_period and len(period)!=2:
            st.error('Choose both start and end dates.');return
        if maximum and maximum<minimum:
            st.error('Maximum age must be at least minimum age.');return
        with st.spinner('Preparing filtered research data…'):
            games,snapshots,appearances,_ = load_data(include_archived=include_archived)
            start = datetime.combine(period[0],time.min) if use_period else None
            end = datetime.combine(period[1]+timedelta(days=1),time.min)-timedelta(microseconds=1) if use_period else None
            files,bundle,manifest = build_exports(games,snapshots,appearances,start=start,end=end,
                genres=genres,min_age=minimum,max_age=maximum,followup_hours=followup,horizon=horizon,include_archived=include_archived)
            st.session_state['research_export'] = (files,bundle,manifest)
    saved = st.session_state.get('research_export')
    if saved:
        files,bundle,manifest = saved
        st.caption(f"Generated {manifest['generated_at_utc']} · cutoff {manifest['analysis_as_of_utc']}. These downloads retain the filters from that generation.")
        st.json(manifest,expanded=False)
        for name in ('Games.csv','Snapshots.csv','Analytics.csv'):
            st.download_button(f"Download {name} · {manifest['rows'][name]:,} rows",files[name],file_name=name,mime='text/csv',on_click='ignore')
        st.download_button('Download complete research ZIP',bundle,file_name='RobloxResearch.zip',mime='application/zip',on_click='ignore')
        st.caption('ZIP also includes discovery history, cohorts, milestone events, market analyses, filter manifest and data definitions. Empty cells mean unavailable. This is a discovery-biased observed sample.')


@st.cache_data(ttl=60)
def export_metadata():
    engine,_ = database()
    try:
        with engine.connect() as connection:
            return pd.read_sql(select(Game.universe_id,Game.primary_genre),connection)
    finally:
        engine.dispose()
