"""Evidence-labeled classifications, editable through authenticated shell access."""
import csv
import io
import json
from sqlalchemy import select
from app.database.models import Game, ClassificationHistory
from app.database.session import utcnow

FIELDS = ("primary_genre", "secondary_genre", "core_loop", "theme", "trend_family", "social_mechanic", "progression_system", "monetization_style")
SOURCES = {"official_metadata", "manual_observation", "manual_hypothesis", "imported_unverified"}


def classify(session, game, values, source, confidence, evidence=None):
    if source not in SOURCES or not 0<=confidence<=1:
        raise ValueError("Use a supported source and confidence between 0 and 1")
    if source=="manual_observation" and not evidence:
        raise ValueError("Manual observations require supporting evidence/notes")
    changes={k:str(v).strip() for k,v in values.items() if k in FIELDS and v is not None}
    if not changes:
        return
    meta=dict(game.classification_meta or {})
    for key,value in changes.items():
        setattr(game,key,value or None)
        meta[key]={"source":source,"confidence":confidence,"evidence":evidence}
    game.classification_meta=meta
    game.classification_source=source
    game.classification_confidence=confidence
    game.classification_updated_at=utcnow()
    session.add(ClassificationHistory(universe_id=game.universe_id,timestamp=utcnow(),values_json=changes,source=source,confidence=confidence,evidence=evidence))


def sync_official_genres(session, game, row, now):
    changes={}
    meta=game.classification_meta or {}
    for key,raw in (("primary_genre","genre_l1"),("secondary_genre","genre_l2")):
        value=row.get(raw)
        if value and meta.get(key,{}).get("source","official_metadata")=="official_metadata" and getattr(game,key)!=value:
            changes[key]=value
    if changes:
        classify(session,game,changes,"official_metadata",1.0,"Roblox games API genre fields; not independent gameplay validation")


def export_csv(games):
    stream=io.StringIO()
    writer=csv.DictWriter(stream,fieldnames=["universe_id",*FIELDS,"source","confidence","evidence","provenance_json"])
    writer.writeheader()
    for game in games:
        item={k:getattr(game,k) for k in FIELDS}
        writer.writerow({"universe_id":game.universe_id,**item,"source":game.classification_source or "imported_unverified","confidence":game.classification_confidence or 0,"evidence":"","provenance_json":json.dumps(game.classification_meta or {})})
    return stream.getvalue()


def import_csv(session, content):
    reader=csv.DictReader(io.StringIO(content))
    if not reader.fieldnames or "universe_id" not in reader.fieldnames:
        raise ValueError("CSV requires universe_id")
    count=0
    for number,row in enumerate(reader,2):
        uid=int(row["universe_id"])
        game=session.get(Game,uid)
        if not game:
            raise ValueError(f"Row {number}: universe {uid} is not tracked")
        values={k:row[k] for k in FIELDS if row.get(k)}
        provenance=json.loads(row.get("provenance_json") or "{}")
        for key,value in values.items():
            meta=provenance.get(key,{})
            source=row.get("source") or "imported_unverified"
            if meta:
                source=meta.get("source",source)
            classify(session,game,{key:value},source,float(meta.get("confidence",row.get("confidence") or 0)),meta.get("evidence") or row.get("evidence"))
        count+=1
    return count
