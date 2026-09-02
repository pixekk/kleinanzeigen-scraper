from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .config import SearchConfig
from .models import Listing, PriceType
from .scraper import normalize


@dataclass
class FilterResult:
    matched: bool
    reason: str = ""

    def __bool__(self) -> bool:
        return self.matched


MATCH = FilterResult(True)


def check_price(listing: Listing, search: SearchConfig) -> FilterResult:
    if listing.price_type is PriceType.FREE:
        return MATCH if search.include_free else FilterResult(False, "free listings excluded")

    if search.negotiable == "only" and listing.price_type is not PriceType.NEGOTIABLE:
        return FilterResult(False, "not a VB price")
    if search.negotiable == "exclude" and listing.price_type is PriceType.NEGOTIABLE:
        return FilterResult(False, "VB price excluded")

    if listing.price is None:
        if search.price_min is None and search.price_max is None:
            return MATCH
        return (
            MATCH
            if search.include_without_price
            else FilterResult(False, "no price given")
        )

    if search.price_min is not None and listing.price < search.price_min:
        return FilterResult(False, f"price {listing.price} below minimum {search.price_min}")
    if search.price_max is not None and listing.price > search.price_max:
        return FilterResult(False, f"price {listing.price} above maximum {search.price_max}")
    return MATCH


def check_keywords(listing: Listing, search: SearchConfig) -> FilterResult:
    keywords = search.keywords
    if not keywords.is_active:
        return MATCH

    haystack = normalize(listing.searchable_text)

    missing = [term for term in keywords.all_of if normalize(term) not in haystack]
    if missing:
        return FilterResult(False, f"missing required term(s): {', '.join(missing)}")

    if keywords.any_of and not any(normalize(term) in haystack for term in keywords.any_of):
        return FilterResult(False, "none of the optional terms found")

    blocked = [term for term in keywords.none_of if normalize(term) in haystack]
    if blocked:
        return FilterResult(False, f"blocked term(s): {', '.join(blocked)}")

    return MATCH


def needs_detail_page(listing: Listing, search: SearchConfig) -> bool:
    if not search.fetch_details or listing.detail_description:
        return False
    return search.keywords.is_active


def check_listing(listing: Listing, search: SearchConfig) -> FilterResult:
    if search.exclude_sponsored and listing.is_sponsored:
        return FilterResult(False, "sponsored listing")
    price_result = check_price(listing, search)
    if not price_result:
        return price_result
    return check_keywords(listing, search)


def price_dropped(listing: Listing, previous_price: Optional[int]) -> bool:
    return (
        previous_price is not None
        and listing.price is not None
        and listing.price < previous_price
    )
