from __future__ import annotations

import argparse
import logging
import os
import random
import signal
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from .config import AppConfig, SearchConfig, load_config
from .fetcher import Fetcher
from .notifier import EmailNotifier
from .runner import SearchRunner
from .storage import Storage

log = logging.getLogger("scanner")
shutdown = threading.Event()


@dataclass
class ScheduledSearch:
    search: SearchConfig
    next_run: float


def setup_logging(level: str) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )
    for noisy in ("httpx", "httpcore", "hpack", "h2", "charset_normalizer"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def handle_signal(signum: int, _frame: object) -> None:
    log.info("received signal %s, shutting down after current search", signum)
    shutdown.set()


def heartbeat(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(int(time.time())), encoding="utf-8")


def run_loop(config: AppConfig, runner: SearchRunner) -> None:
    now = time.monotonic()
    schedule = [
        ScheduledSearch(search=search, next_run=now + index * 5)
        for index, search in enumerate(config.active_searches)
    ]
    log.info(
        "scanner started with %d active search(es): %s",
        len(schedule),
        ", ".join(item.search.name for item in schedule),
    )

    while not shutdown.is_set():
        heartbeat(config.heartbeat_path)
        now = time.monotonic()
        due = [item for item in schedule if item.next_run <= now]

        for item in due:
            if shutdown.is_set():
                break
            try:
                runner.run(item.search)
            except Exception as exc:
                log.exception("[%s] unexpected error: %s", item.search.name, exc)
            jitter = random.uniform(0, min(60, item.search.interval_minutes * 6))
            item.next_run = time.monotonic() + item.search.interval_minutes * 60 + jitter
            log.debug(
                "[%s] next run in %.1f min", item.search.name, (item.next_run - time.monotonic()) / 60
            )

        upcoming = min((item.next_run for item in schedule), default=time.monotonic() + 60)
        sleep_for = max(1.0, min(30.0, upcoming - time.monotonic()))
        shutdown.wait(sleep_for)

    log.info("scanner stopped")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kleinanzeigen-scanner")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(os.getenv("CONFIG_PATH", "config/searches.yaml")),
        help="path to the YAML config",
    )
    parser.add_argument("--once", action="store_true", help="run every search once and exit")
    parser.add_argument("--dry-run", action="store_true", help="log matches instead of sending mail")
    parser.add_argument("--test-mail", action="store_true", help="send a test mail and exit")
    parser.add_argument("--show-urls", action="store_true", help="print the built search URLs and exit")
    parser.add_argument("--reset", metavar="SEARCH", help="forget stored ads of one search ('all' for every search)")
    return parser


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = build_parser().parse_args(argv)

    try:
        config = load_config(args.config)
    except (FileNotFoundError, ValueError) as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2

    setup_logging(config.log_level)

    if args.show_urls:
        from .scraper import build_search_url

        for search in config.searches:
            state = "" if search.enabled else " (disabled)"
            print(f"{search.name}{state}:")
            for query, url in search.targets:
                print(f"  {build_search_url(search, 1, query, url)}")
        return 0

    if args.test_mail:
        EmailNotifier(config.smtp).send_test(config.recipients or config.searches[0].recipients)
        return 0

    storage = Storage(config.database_path)

    if args.reset:
        targets = [s.name for s in config.searches] if args.reset == "all" else [args.reset]
        for name in targets:
            removed = storage.reset(name)
            log.info("reset '%s': %d entries removed", name, removed)
        return 0

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    with Fetcher(
        user_agent=config.user_agent,
        delay_seconds=config.request_delay_seconds,
        timeout_seconds=config.request_timeout_seconds,
    ) as fetcher:
        runner = SearchRunner(config, storage, fetcher, EmailNotifier(config.smtp), dry_run=args.dry_run)
        try:
            if args.once:
                started = datetime.now()
                total = sum(runner.run(search) for search in config.active_searches)
                log.info("single run finished in %.1fs, %d matches", (datetime.now() - started).total_seconds(), total)
            else:
                run_loop(config, runner)
        finally:
            storage.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
