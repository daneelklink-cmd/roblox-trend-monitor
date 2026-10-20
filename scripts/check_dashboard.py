"""Runs the real Streamlit app without a browser, exercising filters and the explorer."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from streamlit.testing.v1 import AppTest
from app.config import ROOT

app = AppTest.from_file(str(ROOT / "app/dashboard/main.py"), default_timeout=60).run()
assert not app.exception, [x.message for x in app.exception]
assert len(app.tabs) == 11
app.text_input[0].set_value("Brookhaven").run()
assert not app.exception, [x.message for x in app.exception]
app.text_input[0].set_value("").run()
next(x for x in app.selectbox if x.label == "Market comparison").select(72).run()
assert not app.exception, [x.message for x in app.exception]
next(x for x in app.selectbox if x.label == "Numeric ranking sort").select("ccu").run()
assert not app.exception, [x.message for x in app.exception]
next(x for x in app.button if x.label == 'Generate exports').click().run()
assert not app.exception, [x.message for x in app.exception]
exported = app.session_state['research_export']
assert exported[2]['rows']['Games.csv'] > 0
assert exported[2]['rows']['Snapshots.csv'] > 0
assert 'Analytics.csv' in exported[0]
next(x for x in app.checkbox if x.label == 'Limit observation period').check()
next(x for x in app.number_input if x.label == 'Export maximum creation age / days (0 = any)').set_value(30)
next(x for x in app.button if x.label == 'Generate exports').click().run()
assert not app.exception, [x.message for x in app.exception]
assert app.session_state['research_export'][2]['filters']['maximum_creation_age_days'] == 30
print("Dashboard AppTest passed: eleven tabs, export generation, date/age filters, cohorts, opportunities and explorer.")
