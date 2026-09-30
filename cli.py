from __future__ import annotations

import argparse
import os
import sys

from core.engine import execute_run, start_run
from core.llm import MockLLM, ResponsesLLM
from core.scheduler import tick
from core.storage import store_from_credentials


def main():
    parser = argparse.ArgumentParser(description="Viktor Mir Ангелис — text-only worker")
    parser.add_argument("command", choices=["init", "run", "tick"])
    parser.add_argument("--dry", action="store_true")
    parser.add_argument("--mock", action="store_true", help="Explicit synthetic offline test only")
    parser.add_argument("--deep", action="store_true")
    parser.add_argument("--task")
    parser.add_argument("--instruction", default="")
    args = parser.parse_args()
    credentials = dict(os.environ)
    credentials.setdefault("ANGELIS_STORAGE", "local")
    store = store_from_credentials(credentials)
    if args.command == "init":
        print("STATE/BACKLOG initialized; existing data preserved.")
        return 0
    llm = MockLLM() if args.mock else (None if args.dry else ResponsesLLM(credentials.get("OPENAI_API_KEY", "")))
    if args.command == "tick":
        if args.dry or args.mock:
            raise ValueError("tick использует только реальный адаптер и настройки расписания")
        tick(store, llm)
        print("Scheduler checked. Work runs only when both saved switches are ON.")
        return 0
    run_id = start_run(store, mode="dry" if args.dry else "deep" if args.deep else "normal", task_id=args.task,
                       instruction=args.instruction, mock=args.mock)
    execute_run(store, run_id, llm)
    run = store.load()["runs"][run_id]
    print(f"{run_id}: {run['status']}; {len(run['artifacts'])} artifacts")
    print(run.get("summary") or run.get("error", ""))
    return 0 if run["status"] == "completed" else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
