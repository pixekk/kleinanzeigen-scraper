import pytest

from app.config import KeywordFilter, SearchConfig
from app.filters import check_listing, check_price, price_dropped
from app.models import Listing, PriceType


def make_search(**kwargs) -> SearchConfig:
    kwargs.setdefault("name", "test")
    kwargs.setdefault("query", "ps5")
    kwargs.setdefault("recipients", ["a@b.de"])
    return SearchConfig(**kwargs)


def make_listing(**kwargs) -> Listing:
    base = dict(
        ad_id="1",
        title="PS5 Slim mit Laufwerk",
        url="https://www.kleinanzeigen.de/s-anzeige/x/1",
        price=300,
        price_type=PriceType.NEGOTIABLE,
        price_text="300 € VB",
        description="Guter Zustand, mit OVP",
    )
    base.update(kwargs)
    return Listing(**base)


def test_price_range_bounds():
    search = make_search(price_min=100, price_max=350)
    assert check_price(make_listing(price=300), search)
    assert not check_price(make_listing(price=90), search)
    assert not check_price(make_listing(price=400), search)


def test_negotiable_modes():
    fixed = make_listing(price_type=PriceType.FIXED, price_text="300 €")
    assert check_price(fixed, make_search(negotiable="exclude"))
    assert not check_price(fixed, make_search(negotiable="only"))
    assert check_price(make_listing(), make_search(negotiable="only"))
    assert not check_price(make_listing(), make_search(negotiable="exclude"))


def test_listing_without_price():
    listing = make_listing(price=None, price_type=PriceType.NONE, price_text="")
    assert not check_price(listing, make_search(price_max=350))
    assert check_price(listing, make_search(price_max=350, include_without_price=True))
    assert check_price(listing, make_search())


def test_free_listings_toggle():
    listing = make_listing(price=0, price_type=PriceType.FREE, price_text="Zu verschenken")
    assert check_price(listing, make_search(price_min=100))
    assert not check_price(listing, make_search(include_free=False))


def test_keyword_rules():
    listing = make_listing()
    assert check_listing(listing, make_search(keywords=KeywordFilter(any_of=["laufwerk", "disc"])))
    assert not check_listing(listing, make_search(keywords=KeywordFilter(any_of=["digital"])))
    assert check_listing(listing, make_search(keywords=KeywordFilter(all_of=["ps5", "ovp"])))
    assert not check_listing(listing, make_search(keywords=KeywordFilter(all_of=["ps5", "garantie"])))
    assert not check_listing(listing, make_search(keywords=KeywordFilter(none_of=["ovp"])))


def test_keywords_ignore_case_and_umlauts():
    listing = make_listing(description="Sehr guter Zustand, für Bastler ungeeignet")
    assert check_listing(listing, make_search(keywords=KeywordFilter(all_of=["FÜR bastler"])))


def test_sponsored_excluded():
    assert not check_listing(make_listing(is_sponsored=True), make_search())
    assert check_listing(make_listing(is_sponsored=True), make_search(exclude_sponsored=False))


def test_price_drop_detection():
    assert price_dropped(make_listing(price=250), 300)
    assert not price_dropped(make_listing(price=300), 300)
    assert not price_dropped(make_listing(price=None), 300)


def test_invalid_interval_rejected():
    with pytest.raises(ValueError):
        make_search(interval_minutes=1)


def test_multiple_queries_and_config_from_yaml(tmp_path, monkeypatch):
    from app.config import load_config

    monkeypatch.setenv(
        "CONFIG_YAML",
        """
recipients: [me@example.com]
smtp: {host: smtp.example.com, user: bot@example.com, password: secret}
defaults: {interval_minutes: 20, price_max: 200}
searches:
  - name: ThinkCentre
    queries: [thinkcentre m720q, thinkcentre m920q]
  - name: Fahrrad
    query: herrenrad
    interval_minutes: 30
""",
    )
    config = load_config(tmp_path / "does-not-exist.yaml")

    assert [s.name for s in config.searches] == ["ThinkCentre", "Fahrrad"]
    assert config.searches[0].recipients == ["me@example.com"]
    assert config.searches[0].interval_minutes == 20
    assert config.searches[0].price_max == 200
    assert config.searches[1].interval_minutes == 30
    assert len(config.searches[0].targets) == 2
    assert config.smtp.from_address == "bot@example.com"
