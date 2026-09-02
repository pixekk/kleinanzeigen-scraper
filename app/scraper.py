from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup, Tag

from .config import SearchConfig
from .models import Listing, PriceType

BASE_URL = "https://www.kleinanzeigen.de"

_UMLAUTS = {"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"}
_ZIP_PATTERN = re.compile(r"^\d{5}\s+\S")
_DATE_PATTERN = re.compile(r"(heute|gestern|\d{2}\.\d{2}\.\d{4})", re.IGNORECASE)
_PRICE_MARKER = re.compile(r"(€|\bvb\b|zu verschenken)", re.IGNORECASE)
_PRICE_NUMBER = re.compile(r"(\d[\d.\s]*)")
_TIME_ONLY = re.compile(r"(\d{1,2}):(\d{2})")
_FULL_DATE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})")


def slugify(text: str) -> str:
    lowered = text.lower().strip()
    for source, target in _UMLAUTS.items():
        lowered = lowered.replace(source, target)
    lowered = unicodedata.normalize("NFKD", lowered).encode("ascii", "ignore").decode()
    lowered = re.sub(r"[^a-z0-9]+", "-", lowered)
    return lowered.strip("-")


def normalize(text: str) -> str:
    lowered = text.lower()
    for source, target in _UMLAUTS.items():
        lowered = lowered.replace(source, target)
    lowered = unicodedata.normalize("NFKD", lowered).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", lowered)


def build_search_url(
    search: SearchConfig,
    page: int = 1,
    query: Optional[str] = None,
    url: Optional[str] = None,
) -> str:
    if url:
        return _paginate_custom_url(url, page)

    modifiers: list[str] = []
    if page > 1:
        modifiers.append(f"seite:{page}")
    if search.price_filter_in_url and (search.price_min is not None or search.price_max is not None):
        low = "" if search.price_min is None else str(search.price_min)
        high = "" if search.price_max is None else str(search.price_max)
        modifiers.append(f"preis:{low}:{high}")
    if search.only_offers:
        modifiers.append("anzeige:angebote")
    if query:
        modifiers.append(slugify(query))

    suffix = "k0"
    if search.category_id:
        suffix += f"c{str(search.category_id).lstrip('c')}"
    if search.location_id:
        suffix += f"l{str(search.location_id).lstrip('l')}"
    if search.radius_km:
        suffix += f"r{search.radius_km}"

    path = "/s-" + "/".join([*modifiers, suffix])
    return f"{BASE_URL}{path}?sortingField=SORTING_DATE"


def _paginate_custom_url(url: str, page: int) -> str:
    if page <= 1:
        return url
    parts = urlparse(url)
    path = re.sub(r"/seite:\d+", "", parts.path)
    path = path.replace("/s-", f"/s-seite:{page}/", 1)
    return urlunparse(parts._replace(path=path))


def parse_price(text: str) -> tuple[Optional[int], PriceType, str]:
    cleaned = re.sub(r"\s+", " ", text or "").strip()
    if not cleaned:
        return None, PriceType.NONE, ""

    lowered = cleaned.lower()
    if "verschenk" in lowered:
        return 0, PriceType.FREE, cleaned

    match = _PRICE_NUMBER.search(cleaned)
    value: Optional[int] = None
    if match:
        digits = re.sub(r"[^\d]", "", match.group(1))
        if digits:
            value = int(digits)

    is_negotiable = re.search(r"\bvb\b", lowered) is not None
    if value is None:
        return None, PriceType.NEGOTIABLE if is_negotiable else PriceType.NONE, cleaned
    return value, PriceType.NEGOTIABLE if is_negotiable else PriceType.FIXED, cleaned


def parse_posted(text: str, now: Optional[datetime] = None) -> Optional[datetime]:
    now = now or datetime.now()
    cleaned = (text or "").strip()
    if not cleaned:
        return None

    full = _FULL_DATE.search(cleaned)
    if full:
        day, month, year = (int(group) for group in full.groups())
        try:
            return datetime(year, month, day)
        except ValueError:
            return None

    time_match = _TIME_ONLY.search(cleaned)
    hour, minute = (int(time_match.group(1)), int(time_match.group(2))) if time_match else (0, 0)
    lowered = cleaned.lower()
    if "heute" in lowered:
        base = now
    elif "gestern" in lowered:
        base = now - timedelta(days=1)
    else:
        return None
    return base.replace(hour=hour, minute=minute, second=0, microsecond=0)


def _text_of(node: Optional[Tag]) -> str:
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True)) if node else ""


def _first(node: Tag, *selectors: str) -> Optional[Tag]:
    for selector in selectors:
        found = node.select_one(selector)
        if found:
            return found
    return None


def _classes(node: Tag) -> str:
    return " ".join(node.get("class") or [])


def _leaf_nodes(article: Tag, selector: str) -> list[Tag]:
    return [node for node in article.select(selector) if not node.find(["p", "span", "div", "h3", "h2"])]


def _extract_title(article: Tag) -> str:
    for selector in ("h3 a", "h2 a", "h3", "h2", "a.ellipsis"):
        text = _text_of(article.select_one(selector))
        if text:
            return text
    return ""


def _extract_price(article: Tag) -> str:
    candidates = [
        node
        for node in _leaf_nodes(article, "p, span, div")
        if _PRICE_MARKER.search(_text_of(node))
        and len(_text_of(node)) <= 40
        and "line-through" not in _classes(node)
    ]
    for node in candidates:
        if "font-strong" in _classes(node):
            return _text_of(node)
    return _text_of(candidates[0]) if candidates else ""


def _extract_structured(article: Tag) -> dict[str, str]:
    for script in article.select('script[type="application/ld+json"]'):
        try:
            payload = json.loads(script.string or "{}")
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(payload, dict) and payload.get("@type") == "ImageObject":
            return {
                "title": str(payload.get("title") or ""),
                "description": str(payload.get("description") or ""),
                "image": str(payload.get("contentUrl") or ""),
            }
    return {}


def _extract_meta(article: Tag) -> tuple[str, str]:
    location = ""
    posted = ""
    for node in _leaf_nodes(article, "span, div"):
        text = _text_of(node)
        if not text or len(text) > 60:
            continue
        if not location and _ZIP_PATTERN.match(text):
            location = text
        elif not posted and len(text) < 30 and _DATE_PATTERN.search(text):
            posted = text
        if location and posted:
            break
    return location, posted


def _extract_image(article: Tag) -> str:
    image = _first(article, "img[src]", "img")
    if not image:
        return ""
    source = image.get("src") or image.get("data-imgsrc") or (image.get("srcset") or "").split(" ")[0]
    return source if isinstance(source, str) else ""


def _extract_tags(article: Tag, exclude: set[str]) -> list[str]:
    tags: list[str] = []
    for node in _leaf_nodes(article, "span, p"):
        text = _text_of(node)
        if not text or len(text) > 40 or text in exclude or text in tags or text.isdigit():
            continue
        if _PRICE_MARKER.search(text) or _ZIP_PATTERN.match(text) or _DATE_PATTERN.search(text):
            continue
        tags.append(text)
    return tags[:5]


def _is_sponsored(article: Tag) -> bool:
    if "is-topad" in _classes(article):
        return True
    for node in article.select("[data-gaevent]"):
        event = node.get("data-gaevent") or ""
        if "partner=pro" in event or "AdStoreClick" in event:
            return True
    return False


def parse_listings(html: str) -> list[Listing]:
    soup = BeautifulSoup(html, "lxml")
    listings: list[Listing] = []

    for article in soup.select("article[data-adid], article.aditem"):
        href = (article.get("data-href") or "").strip()
        if not href:
            link = _first(article, "h3 a[href]", "h2 a[href]", "a[href*='/s-anzeige/']")
            href = (link.get("href") or "").strip() if link else ""
        if not href:
            continue

        ad_id = (article.get("data-adid") or "").strip()
        if not ad_id:
            digits = re.findall(r"(\d{6,})", href)
            ad_id = digits[-1] if digits else href

        structured = _extract_structured(article)
        title = _extract_title(article) or structured.get("title", "")
        if not title:
            continue

        price, price_type, price_text = parse_price(_extract_price(article))
        location, posted_text = _extract_meta(article)
        short_description = _text_of(
            _first(article, "p.text-onSurfaceSubdued", ".aditem-main--middle--description", "p")
        )

        listings.append(
            Listing(
                ad_id=ad_id,
                title=title,
                url=urljoin(BASE_URL, href),
                price_text=price_text,
                price=price,
                price_type=price_type,
                location=location,
                posted_text=posted_text,
                posted_at=parse_posted(posted_text),
                description=structured.get("description") or short_description,
                image_url=structured.get("image") or _extract_image(article),
                tags=_extract_tags(article, exclude={title, location, posted_text, short_description}),
                is_sponsored=_is_sponsored(article),
            )
        )

    return listings


def parse_detail_description(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    node = _first(
        soup,
        "#viewad-description-text",
        "[id*='description-text']",
        "[data-testid*='description']",
    )
    return _text_of(node)
