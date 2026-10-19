import json
import logging
from logging.handlers import RotatingFileHandler
from app.config import ROOT
from app.services.collection import collect


def setup_logging():
    (ROOT / "data").mkdir(exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", handlers=[
        logging.StreamHandler(), RotatingFileHandler(ROOT / "data/collector.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    ])
    logging.getLogger("httpx").setLevel(logging.WARNING)


def main():
    setup_logging()
    try:
        result = collect()
    except OSError:
        logging.exception("Collector is already running or the data directory is unavailable")
        raise SystemExit(1)
    print("Collection complete\n" + json.dumps(result, indent=2))
    if result["status"] == "empty":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
