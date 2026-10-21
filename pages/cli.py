import argparse
import getpass
import json
from datetime import UTC, datetime

from pages import config, db as dbm


def main(argv=None):
    ap = argparse.ArgumentParser(prog="pages")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init")
    sub.add_parser("connect").add_argument("handle")
    sub.add_parser("verify-ig").add_argument("handle")
    for name in ("check-aws", "web", "tick", "work", "fetch"):
        sub.add_parser(name)
    args = ap.parse_args(argv)

    # Modules below are imported lazily: each subcommand only needs its own.
    if args.cmd == "web":
        import uvicorn
        uvicorn.run("pages.web:app", host="127.0.0.1", port=8000)
        return
    if args.cmd == "check-aws":
        from pages.voice import check_aws
        check_aws()
        return
    if args.cmd == "fetch":
        from pages.fetcher import run_jobs
        print(json.dumps(run_jobs()))
        return

    cfg = config.load()
    db = dbm.connect()
    if args.cmd == "init":
        dbm.add_pages(db, cfg)
    elif args.cmd == "connect":
        from pages.accounts import connect
        token = getpass.getpass(f"Token for @{args.handle}: ")
        connect(db, args.handle, token, now=datetime.now(UTC))
    elif args.cmd == "verify-ig":
        from pages.verify import run
        print(json.dumps(run(db, args.handle), indent=2, default=str))
    elif args.cmd == "tick":
        from pages.tick import tick
        tick(db, cfg, datetime.now(UTC))
    elif args.cmd == "work":
        from pages import clips_pipeline, script_pipeline
        clips_pipeline.step(db, cfg)
        script_pipeline.step(db, cfg)
