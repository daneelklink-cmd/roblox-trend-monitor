"""Runs the real Streamlit app without a browser, exercising filters and the explorer."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from streamlit.testing.v1 import AppTest
from app.config import ROOT

app = AppTest.from_file(str(ROOT / "app/dashboard/main.py"), default_timeout=60).run()
assert not app.exception, [x.message for x in app.exception]
assert len(app.tabs) == 10
app.text_input[0].set_value("Brookhaven").run()
assert not app.exception, [x.message for x in app.exception]
app.text_input[0].set_value("").run()
next(x for x in app.selectbox if x.label == "Market comparison").select(72).run()
assert not app.exception, [x.message for x in app.exception]
next(x for x in app.selectbox if x.label == "Numeric ranking sort").select("ccu").run()
assert not app.exception, [x.message for x in app.exception]
print("Dashboard AppTest passed: ten tabs, cohorts, opportunities, coverage, filters and explorer.")
