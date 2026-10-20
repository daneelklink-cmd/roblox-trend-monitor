"""Display-only conversion: analytics, persistence and CSV exports stay in UTC."""
import pandas as pd
import streamlit as st


def berlin(value):
    if value is None or pd.isna(value):return 'unknown'
    stamp=pd.Timestamp(value)
    if stamp.tzinfo is None:stamp=stamp.tz_localize('UTC')
    return stamp.tz_convert('Europe/Berlin').strftime('%d.%m.%Y %H:%M %Z')


def local_frame(frame):
    frame=frame.copy()
    for column in frame:
        if pd.api.types.is_datetime64_any_dtype(frame[column]):
            frame[column]=pd.to_datetime(frame[column],utc=True).dt.tz_convert('Europe/Berlin')
            if column.endswith('_utc'):frame=frame.rename(columns={column:column[:-4]+'_berlin'})
    return frame


def display_dataframe(frame,**kwargs):
    return st.dataframe(local_frame(frame),**kwargs)
