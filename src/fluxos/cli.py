from __future__ import annotations
import argparse
import json
from pathlib import Path
from . import demo
from .benchmark import benchmark


def main():
    parser=argparse.ArgumentParser(prog="fluxos")
    parser.add_argument("command",choices=["serve","demo","unified-demo","benchmark"])
    parser.add_argument("--home",default=".fluxos",help="Local demo state directory")
    parser.add_argument("--port",type=int,default=8765)
    args=parser.parse_args()
    if args.command=="serve":
        import uvicorn
        from .api import create_app
        # loopback only; local demo endpoints are deliberately not internet safe.
        uvicorn.run(create_app(args.home),host="127.0.0.1",port=args.port)
    elif args.command=="demo":
        home=Path(args.home)/"causal_demo"
        demo.bootstrap(home)
        print("BEFORE CHANGE",demo.snapshot(home)["statuses"])
        print("AFTER CHANGE",demo.mutate(home)["statuses"])
        print("AFTER REPAIR",demo.repair(home)["statuses"])
    elif args.command=="unified-demo":
        from .unified_demo import run
        print(json.dumps(run(),indent=2))
    else:
        print(json.dumps(benchmark(),indent=2))

if __name__=="__main__":main()
