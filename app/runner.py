from __future__ import annotations

import logging

from .config import AppConfig, SearchConfig
from .fetcher import BlockedError, FetchError, Fetcher
from .filters import check_listing, needs_detail_page, price_dropped
from .models import Listing
from .notifier import EmailNotifier
from .scraper import build_search_url, parse_detail_description, parse_listings
from .storage import Storage

log = logging.getLogger(__name__)


class SearchRunner:
    def __init__(
        self,
        config: AppConfig,
        storage: Storage,
        fetcher: Fetcher,
        notifier: EmailNotifier,
        dry_run: bool = False,
    ) -> None:
        self.config = config
        self.storage = storage
        self.fetcher = fetcher
        self.notifier = notifier
        self.dry_run = dry_run

    def collect(self, search: SearchConfig) -> tuple[list[Listing], str]:
        collected: list[Listing] = []
        seen_ids: set[str] = set()
        targets = search.targets
        first_url = build_search_url(search, 1, targets[0][0], targets[0][1])

        for query, url in targets:
            target_url = build_search_url(search, 1, query, url)
            for page in range(1, search.max_pages + 1):
                page_url = build_search_url(search, page, query, url)
                html = self.fetcher.get_html(page_url, referer=target_url if page > 1 else None)
                page_listings = parse_listings(html)
                log.debug(
                    "[%s] %s page %d -> %d listings",
                    search.name,
                    query or url or "category",
                    page,
                    len(page_listings),
                )
                if not page_listings:
                    break
                for listing in page_listings:
                    if listing.ad_id not in seen_ids:
                        seen_ids.add(listing.ad_id)
                        collected.append(listing)
                if len(page_listings) < 20:
                    break

        return collected, first_url

    def enrich(self, search: SearchConfig, listing: Listing, referer: str) -> None:
        if not needs_detail_page(listing, search):
            return
        try:
            listing.detail_description = parse_detail_description(
                self.fetcher.get_html(listing.url, referer=referer)
            )
        except FetchError as exc:
            log.warning("[%s] detail fetch failed for %s: %s", search.name, listing.ad_id, exc)

    def run(self, search: SearchConfig) -> int:
        log.info("[%s] scanning", search.name)
        try:
            listings, search_url = self.collect(search)
        except BlockedError as exc:
            log.error("[%s] %s - backing off", search.name, exc)
            self.storage.record_run(search.name, str(exc))
            return 0
        except FetchError as exc:
            log.error("[%s] fetch failed: %s", search.name, exc)
            self.storage.record_run(search.name, str(exc))
            return 0

        seeding = search.seed_on_first_run and not self.storage.is_seeded(search.name)
        matches: list[Listing] = []

        for listing in listings:
            known, previous_price = self.storage.known_price(search.name, listing.ad_id)

            if known and not (search.notify_on_price_drop and price_dropped(listing, previous_price)):
                self.storage.upsert(search.name, listing, notified=False)
                continue

            self.enrich(search, listing, search_url)
            result = check_listing(listing, search)
            if not result:
                log.debug("[%s] skip %s: %s", search.name, listing.title[:50], result.reason)
                self.storage.upsert(search.name, listing, notified=False)
                continue

            if seeding:
                self.storage.upsert(search.name, listing, notified=False)
                continue

            matches.append(listing)
            if len(matches) >= search.max_new_per_run:
                log.warning("[%s] hit max_new_per_run (%d)", search.name, search.max_new_per_run)
                break

        if seeding:
            self.storage.mark_seeded(search.name)
            log.info("[%s] first run: %d listings stored without notification", search.name, len(listings))
            self.storage.record_run(search.name)
            return 0

        if matches:
            if self.dry_run:
                for listing in matches:
                    log.info("[%s] MATCH %s | %s | %s", search.name, listing.title, listing.price_display, listing.url)
            else:
                try:
                    self.notifier.send_results(search, matches, search_url)
                except Exception as exc:
                    log.exception("[%s] sending mail failed: %s", search.name, exc)
                    self.storage.record_run(search.name, f"mail failed: {exc}")
                    return 0
                for listing in matches:
                    self.storage.upsert(search.name, listing, notified=True)

        log.info("[%s] %d listings scanned, %d new matches", search.name, len(listings), len(matches))
        self.storage.record_run(search.name)
        self.storage.prune(search.name)
        return len(matches)
