from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class PriceType(str, Enum):
    FIXED = "fixed"
    NEGOTIABLE = "vb"
    FREE = "free"
    NONE = "none"


@dataclass
class Listing:
    ad_id: str
    title: str
    url: str
    price_text: str = ""
    price: Optional[int] = None
    price_type: PriceType = PriceType.NONE
    location: str = ""
    posted_text: str = ""
    posted_at: Optional[datetime] = None
    description: str = ""
    detail_description: str = ""
    image_url: str = ""
    tags: list[str] = field(default_factory=list)
    is_sponsored: bool = False

    @property
    def searchable_text(self) -> str:
        return " ".join([self.title, self.description, self.detail_description, " ".join(self.tags)])

    @property
    def price_display(self) -> str:
        return self.price_text or "Preis auf Anfrage"
