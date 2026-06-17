"""Carrier registry: news outlet definitions keyed by ISO-2 country code."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CarrierDef:
    name: str
    country: str  # ISO 3166-1 alpha-2
    role: str
    feeds: list[str]
    lean: str  # left | right | centre | state


CARRIER_ROSTER: dict[str, list[CarrierDef]] = {
    "US": [
        CarrierDef(
            name="NPR",
            country="US",
            role="public broadcaster",
            feeds=["https://feeds.npr.org/1001/rss.xml"],
            lean="centre",
        ),
        CarrierDef(
            name="Fox News",
            country="US",
            role="cable news",
            feeds=["https://feeds.foxnews.com/foxnews/latest"],
            lean="right",
        ),
        CarrierDef(
            name="Democracy Now",
            country="US",
            role="independent broadcaster",
            feeds=["https://www.democracynow.org/democracynow.rss"],
            lean="left",
        ),
    ],
    "GB": [
        CarrierDef(
            name="BBC",
            country="GB",
            role="public broadcaster",
            feeds=["https://feeds.bbci.co.uk/news/rss.xml"],
            lean="centre",
        ),
        CarrierDef(
            name="The Guardian",
            country="GB",
            role="broadsheet",
            feeds=["https://www.theguardian.com/world/rss"],
            lean="left",
        ),
        CarrierDef(
            name="The Daily Telegraph",
            country="GB",
            role="broadsheet",
            feeds=["https://www.telegraph.co.uk/rss.xml"],
            lean="right",
        ),
    ],
    "RU": [
        CarrierDef(
            name="RT",
            country="RU",
            role="state international broadcaster",
            feeds=["https://www.rt.com/rss/"],
            lean="state",
        ),
        CarrierDef(
            name="TASS",
            country="RU",
            role="state news agency",
            feeds=["https://tass.com/rss/v2.xml"],
            lean="state",
        ),
        CarrierDef(
            name="Meduza",
            country="RU",
            role="independent outlet (Latvia-based)",
            feeds=["https://meduza.io/rss/all"],
            lean="left",
        ),
    ],
}
