from pathlib import Path

from app.config import SearchConfig
from app.models import PriceType
from app.scraper import build_search_url, parse_listings, parse_price, slugify

FIXTURE = (Path(__file__).parent / "fixtures" / "srp_sample.html").read_text(encoding="utf-8")

LEGACY_HTML = """
<ul id="srchrslt-adtable">
  <li class="ad-listitem">
    <article class="aditem" data-adid="2001" data-href="/s-anzeige/ps5-slim/2001-123-456">
      <div class="aditem-main">
        <div class="aditem-main--top">
          <div class="aditem-main--top--left"><span>70173 Stuttgart-Mitte</span></div>
          <div class="aditem-main--top--right"><span>Heute, 14:32</span></div>
        </div>
        <div class="aditem-main--middle">
          <h2 class="text-module-begin"><a class="ellipsis" href="/s-anzeige/ps5-slim/2001-123-456">PS5 Slim mit Laufwerk</a></h2>
          <p class="aditem-main--middle--description">Kaum benutzt, mit Rechnung.</p>
          <p class="aditem-main--middle--price-shipping--price">330 € VB</p>
        </div>
      </div>
    </article>
  </li>
</ul>
"""


def test_parse_current_frontend():
    listings = parse_listings(FIXTURE)
    assert len(listings) == 3

    first = listings[0]
    assert first.ad_id == "3501632059"
    assert first.title == "Playstation 5 mit Laufwerk und Spiele"
    assert first.url.startswith("https://www.kleinanzeigen.de/s-anzeige/")
    assert (first.price, first.price_type) == (350, PriceType.FIXED)
    assert first.location == "84130 Dingolfing"
    assert first.posted_text == "Heute, 14:22"
    assert first.posted_at is not None
    assert first.image_url.startswith("https://img.kleinanzeigen.de/")
    assert "Spielstunden" in first.description
    assert first.is_sponsored is False


def test_parse_negotiable_and_struck_through_price():
    negotiable = parse_listings(FIXTURE)[1]
    assert negotiable.price == 170
    assert negotiable.price_type is PriceType.NEGOTIABLE


def test_sponsored_listing_detected():
    assert parse_listings(FIXTURE)[2].is_sponsored is True


def test_legacy_markup_still_parses():
    listings = parse_listings(LEGACY_HTML)
    assert len(listings) == 1
    listing = listings[0]
    assert listing.title == "PS5 Slim mit Laufwerk"
    assert (listing.price, listing.price_type) == (330, PriceType.NEGOTIABLE)
    assert listing.location == "70173 Stuttgart-Mitte"


def test_parse_price_variants():
    assert parse_price("1.250 €")[:2] == (1250, PriceType.FIXED)
    assert parse_price("80 € VB")[:2] == (80, PriceType.NEGOTIABLE)
    assert parse_price("VB")[:2] == (None, PriceType.NEGOTIABLE)
    assert parse_price("Zu verschenken")[:2] == (0, PriceType.FREE)
    assert parse_price("")[:2] == (None, PriceType.NONE)


def test_slugify_handles_umlauts():
    assert slugify("Bücherregal Weiß") == "buecherregal-weiss"


def test_build_search_url_contains_all_modifiers():
    search = SearchConfig(
        name="test",
        query="Playstation 5",
        price_min=100,
        price_max=350,
        location_id="3331",
        radius_km=30,
        category_id="161",
        recipients=["a@b.de"],
    )
    url = build_search_url(search, page=2, query="Playstation 5")
    assert url.startswith("https://www.kleinanzeigen.de/s-seite:2/preis:100:350/anzeige:angebote/playstation-5/")
    assert url.endswith("k0c161l3331r30?sortingField=SORTING_DATE")


def test_build_search_url_open_price_range():
    search = SearchConfig(name="t", query="fahrrad", price_max=200, recipients=["a@b.de"])
    assert "/s-preis::200/" in build_search_url(search, query="fahrrad")


def test_multiple_queries_produce_multiple_targets():
    search = SearchConfig(
        name="ThinkCentre",
        queries=["thinkcentre m720q", "thinkcentre m920q"],
        recipients=["a@b.de"],
    )
    urls = [build_search_url(search, 1, query, url) for query, url in search.targets]
    assert len(urls) == 2
    assert "thinkcentre-m720q" in urls[0]
    assert "thinkcentre-m920q" in urls[1]


def test_custom_url_target_is_paginated():
    search = SearchConfig(
        name="custom",
        url="https://www.kleinanzeigen.de/s-stuttgart/laptop/k0l3331r20",
        recipients=["a@b.de"],
    )
    query, url = search.targets[0]
    assert build_search_url(search, 1, query, url) == search.url
    assert "/s-seite:3/stuttgart/" in build_search_url(search, 3, query, url)
