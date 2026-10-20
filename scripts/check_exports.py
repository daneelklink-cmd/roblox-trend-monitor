"""Verify complete real-data CSV/ZIP round trips; write a shareable local bundle."""
import io
import json
import sys
import zipfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pandas as pd
from app.analytics.queries import load_data
from app.config import ROOT
from app.services.exports import build_exports

games,snapshots,appearances,_=load_data(include_archived=True)
files,bundle,manifest=build_exports(games,snapshots,appearances)
for filename,expected in [('Games.csv',games),('Snapshots.csv',snapshots),('Discovery.csv',appearances)]:
    actual=pd.read_csv(io.BytesIO(files[filename]),encoding='utf-8-sig')
    assert len(actual)==len(expected),(filename,len(actual),len(expected))
    assert set(actual.universe_id)==set(expected.universe_id)
analytics=pd.read_csv(io.BytesIO(files['Analytics.csv']),encoding='utf-8-sig')
assert len(analytics)==len(games)
assert not analytics.universe_id.duplicated().any()
with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
    assert archive.testzip() is None
    assert json.loads(archive.read('Manifest.json'))==manifest
path=ROOT/'data/RobloxResearch.zip'
path.write_bytes(bundle)
print(json.dumps({'rows':manifest['rows'],'bytes':len(bundle),'saved':str(path)},indent=2))
