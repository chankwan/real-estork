"""
RealEstork — Spider Registry
Loads all spiders from config/spiders.yaml and instantiates them.
"""

from __future__ import annotations

from typing import Any

import yaml
from loguru import logger

from spiders.base import BaseSpider, RawListing
from spiders.nhatot import NhatotSpider
from spiders.alonhadat import AlonhadatSpider
from spiders.batdongsan import BatdongsanSpider
from spiders.muaban import MuabanSpider

# Registry: name → class
SPIDER_REGISTRY: dict[str, type[BaseSpider]] = {
    "nhatot": NhatotSpider,
    "alonhadat": AlonhadatSpider,
    "batdongsan": BatdongsanSpider,
    "muaban": MuabanSpider,
    # Add new spiders here as they're implemented
}


class SpiderEngine:
    """
    Manages all enabled spiders.
    Plugin-based: thêm site mới = thêm file + registry entry + YAML config.
    """

    def __init__(self, config_path: str = "config/spiders.yaml") -> None:
        self.spiders: list[BaseSpider] = []
        self._load_config(config_path)

    def _load_config(self, config_path: str) -> None:
        """Load spider configs from YAML, instantiate enabled spiders."""
        with open(config_path, encoding="utf-8") as f:
            config = yaml.safe_load(f)

        for spider_config in config.get("spiders", []):
            name = spider_config.get("name")
            enabled = spider_config.get("enabled", False)

            if not enabled:
                logger.debug(f"[engine] Spider '{name}' disabled, skipping")
                continue

            spider_class = SPIDER_REGISTRY.get(name)
            if spider_class is None:
                logger.warning(f"[engine] No spider class registered for '{name}'")
                continue

            spider = spider_class(spider_config)
            self.spiders.append(spider)
            logger.info(f"[engine] Loaded spider: {name} (interval={spider.interval_minutes}min)")

    async def fetch_all(
        self,
        only: list[str] | None = None,
        exclude: list[str] | None = None,
    ) -> list[RawListing]:
        """
        Run enabled spiders concurrently.
        - only: restrict to these spider names (whitelist).
        - exclude: skip these spider names (blacklist).
        Returns combined list of raw listings.
        """
        import asyncio

        selected = [
            s for s in self.spiders
            if (only is None or s.name in only)
            and (exclude is None or s.name not in exclude)
        ]
        tasks = [spider.run() for spider in selected]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_listings: list[RawListing] = []
        for spider, result in zip(selected, results):
            if isinstance(result, Exception):
                logger.error(f"[engine] Spider '{spider.name}' failed: {result}")
            elif isinstance(result, list):
                logger.info(f"[engine] Spider '{spider.name}': {len(result)} listings")
                all_listings.extend(result)

        return all_listings

    async def fetch_one(self, spider_name: str) -> list[RawListing]:
        """Run a single spider by name (for CLI/testing)."""
        spider = next((s for s in self.spiders if s.name == spider_name), None)
        if spider is None:
            logger.error(f"[engine] Spider '{spider_name}' not found or disabled")
            return []
        return await spider.run()

    def get_spider(self, spider_name: str) -> BaseSpider | None:
        """Return the loaded spider instance by name, or None if not registered/disabled."""
        return next((s for s in self.spiders if s.name == spider_name), None)
