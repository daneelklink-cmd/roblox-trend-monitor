"""Authenticated-shell operations; the public dashboard has no write endpoints."""
import argparse
from pathlib import Path
from sqlalchemy import select
from app.database.session import database, utcnow, parse_time
from app.database.models import WatchEntry, Game
from app.services.classification import classify, import_csv, export_csv, FIELDS


def main():
    parser=argparse.ArgumentParser()
    sub=parser.add_subparsers(dest="command",required=True)
    watch=sub.add_parser("watch")
    watch.add_argument("action",choices=["add","remove","list"])
    watch.add_argument("universe_id",type=int,nargs="?")
    watch.add_argument("--note",default="")
    c=sub.add_parser("classify")
    c.add_argument("universe_id",type=int)
    for field in FIELDS:
        c.add_argument("--"+field.replace("_","-"))
    c.add_argument("--source",default="manual_hypothesis")
    c.add_argument("--confidence",type=float,default=0.5)
    c.add_argument("--evidence")
    for name in ("import-classifications","export-classifications"):
        sub.add_parser(name).add_argument("file")
    launch=sub.add_parser("verify-launch")
    launch.add_argument("universe_id",type=int)
    launch.add_argument("date",help="Verified UTC timestamp, not API creation time")
    launch.add_argument("--evidence-url",required=True)
    args=parser.parse_args()
    engine,Session=database()
    try:
        with Session.begin() as session:
            if args.command=="watch":
                if args.action=="list":
                    for row in session.scalars(select(WatchEntry)):
                        print(row.universe_id,row.active,row.note)
                else:
                    if not args.universe_id or args.universe_id<=0:
                        parser.error("Supply a positive universe ID")
                    entry=session.get(WatchEntry,args.universe_id)
                    if not entry:
                        entry=WatchEntry(universe_id=args.universe_id,added_at=utcnow());session.add(entry)
                    entry.active=args.action=="add";entry.note=args.note
            elif args.command=="classify":
                game=session.get(Game,args.universe_id)
                if not game: parser.error("Universe is not tracked")
                classify(session,game,{k:getattr(args,k) for k in FIELDS},args.source,args.confidence,args.evidence)
            elif args.command=="import-classifications":
                print("Rows imported:",import_csv(session,Path(args.file).read_text(encoding="utf-8-sig")))
            elif args.command=="export-classifications":
                Path(args.file).write_text(export_csv(session.scalars(select(Game))),encoding="utf-8")
            else:
                game=session.get(Game,args.universe_id)
                if not game: parser.error("Universe is not tracked")
                if not args.evidence_url.startswith("https://"): parser.error("Use an HTTPS evidence URL")
                stamp=parse_time(args.date)
                if not stamp or stamp>utcnow(): parser.error("Launch evidence cannot be in the future")
                game.public_launch_at=stamp;game.launch_evidence_url=args.evidence_url;game.launch_verification="human_verified"
    finally:
        engine.dispose()


if __name__=="__main__": main()
