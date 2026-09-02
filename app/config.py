from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Literal, Optional

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator


class SmtpConfig(BaseModel):
    host: str
    port: int = 587
    user: str = ""
    password: str = ""
    security: Literal["starttls", "ssl", "none"] = "starttls"
    from_address: str = ""
    from_name: str = "Kleinanzeigen Scanner"

    @model_validator(mode="after")
    def default_sender(self) -> "SmtpConfig":
        if not self.from_address:
            self.from_address = self.user
        return self


class KeywordFilter(BaseModel):
    all_of: list[str] = Field(default_factory=list)
    any_of: list[str] = Field(default_factory=list)
    none_of: list[str] = Field(default_factory=list)

    @property
    def is_active(self) -> bool:
        return bool(self.all_of or self.any_of or self.none_of)


class SearchConfig(BaseModel):
    name: str
    query: str = ""
    queries: list[str] = Field(default_factory=list)
    url: Optional[str] = None
    urls: list[str] = Field(default_factory=list)
    enabled: bool = True
    interval_minutes: int = 15
    recipients: list[str] = Field(default_factory=list)

    price_min: Optional[int] = None
    price_max: Optional[int] = None
    price_filter_in_url: bool = True
    negotiable: Literal["any", "only", "exclude"] = "any"
    include_without_price: bool = False
    include_free: bool = True

    zipcode: Optional[str] = None
    radius_km: Optional[int] = None
    location_id: Optional[str] = None
    category_id: Optional[str] = None
    only_offers: bool = True
    exclude_sponsored: bool = True

    keywords: KeywordFilter = Field(default_factory=KeywordFilter)
    fetch_details: bool = False

    max_pages: int = 1
    max_new_per_run: int = 25
    seed_on_first_run: bool = True
    notify_on_price_drop: bool = False

    @field_validator("interval_minutes")
    @classmethod
    def sane_interval(cls, value: int) -> int:
        if value < 5:
            raise ValueError("interval_minutes must be >= 5 to stay polite to the site")
        return value

    @model_validator(mode="after")
    def needs_target(self) -> "SearchConfig":
        self.queries = [q.strip() for q in self.queries if q and q.strip()]
        self.urls = [u.strip() for u in self.urls if u and u.strip()]
        if not self.targets:
            raise ValueError(f"search '{self.name}': needs query/queries, url/urls or category_id")
        if self.price_min is not None and self.price_max is not None and self.price_min > self.price_max:
            raise ValueError(f"search '{self.name}': price_min > price_max")
        return self

    @property
    def targets(self) -> list[tuple[str, Optional[str]]]:
        if self.urls or self.url:
            return [("", url) for url in ([*self.urls, self.url] if self.url else self.urls)]
        terms = self.queries or ([self.query] if self.query else [])
        if terms:
            return [(term, None) for term in terms]
        return [("", None)] if self.category_id else []

    @property
    def slug(self) -> str:
        return "".join(c if c.isalnum() else "-" for c in self.name.lower()).strip("-")


class AppConfig(BaseModel):
    recipients: list[str] = Field(default_factory=list)
    smtp: SmtpConfig
    searches: list[SearchConfig]
    database_path: Path = Path("data/scanner.db")
    heartbeat_path: Path = Path("data/heartbeat")
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    )
    request_delay_seconds: float = 3.0
    request_timeout_seconds: float = 30.0
    log_level: str = "INFO"

    @model_validator(mode="after")
    def spread_recipients(self) -> "AppConfig":
        self.recipients = [r.strip() for r in self.recipients if r and r.strip()]
        for search in self.searches:
            search.recipients = [r.strip() for r in search.recipients if r and r.strip()]
            if not search.recipients:
                search.recipients = list(self.recipients)
            if not search.recipients:
                raise ValueError(f"search '{search.name}': no recipients configured")
        names = [s.name for s in self.searches]
        duplicates = {n for n in names if names.count(n) > 1}
        if duplicates:
            raise ValueError(f"duplicate search names: {', '.join(sorted(duplicates))}")
        return self

    @property
    def active_searches(self) -> list[SearchConfig]:
        return [s for s in self.searches if s.enabled]


_ENV_PATTERN = re.compile(r"\$\{(\w+)\}")


def _expand_env(value: Any) -> Any:
    if isinstance(value, str):
        return _ENV_PATTERN.sub(lambda m: os.getenv(m.group(1), ""), value)
    if isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env(v) for v in value]
    return value


def _merge_defaults(defaults: dict[str, Any], search: dict[str, Any]) -> dict[str, Any]:
    merged = dict(defaults)
    for key, value in search.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = {**merged[key], **value}
        else:
            merged[key] = value
    return merged


def config_source(path: Optional[Path]) -> tuple[str, str]:
    inline = os.getenv("CONFIG_YAML", "").strip()
    if inline:
        return inline, "CONFIG_YAML"
    if path and path.exists():
        return path.read_text(encoding="utf-8"), str(path)
    raise FileNotFoundError(
        f"no configuration found: set CONFIG_YAML or create {path or 'config/searches.yaml'}"
    )


def load_config(path: Optional[Path] = None) -> AppConfig:
    text, _ = config_source(path)
    raw = yaml.safe_load(text) or {}
    raw = _expand_env(raw)

    smtp = raw.get("smtp") or {}
    for key, env_name in (
        ("host", "SMTP_HOST"),
        ("port", "SMTP_PORT"),
        ("user", "SMTP_USER"),
        ("password", "SMTP_PASSWORD"),
        ("from_address", "SMTP_FROM"),
    ):
        if not smtp.get(key):
            smtp[key] = os.getenv(env_name, "")
    smtp["port"] = int(smtp["port"] or 587)

    defaults = raw.get("defaults", {}) or {}
    searches = [_merge_defaults(defaults, s) for s in (raw.get("searches") or [])]

    recipients = raw.get("recipients") or [
        r.strip() for r in os.getenv("MAIL_TO", "").split(",") if r.strip()
    ]

    return AppConfig(
        recipients=recipients,
        smtp=SmtpConfig(**smtp),
        searches=[SearchConfig(**s) for s in searches],
        database_path=Path(os.getenv("DATABASE_PATH", raw.get("database_path", "data/scanner.db"))),
        heartbeat_path=Path(os.getenv("HEARTBEAT_PATH", raw.get("heartbeat_path", "data/heartbeat"))),
        user_agent=raw.get("user_agent") or AppConfig.model_fields["user_agent"].default,
        request_delay_seconds=float(raw.get("request_delay_seconds", 3.0)),
        request_timeout_seconds=float(raw.get("request_timeout_seconds", 30.0)),
        log_level=os.getenv("LOG_LEVEL", raw.get("log_level", "INFO")),
    )
