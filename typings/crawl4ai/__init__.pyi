"""Crawl4AI 0.9.4 public interfaces used by the isolated research reader.

This deliberately models only the called surface, not optional upstream APIs.
Real Linux browser tests verify the integration against the pinned distribution.
"""

from enum import Enum
from types import TracebackType
from typing import Self

class CacheMode(Enum):
    BYPASS = "bypass"

class BrowserConfig:
    # Inputs: explicit browser safety settings. Output: isolated browser configuration.
    def __init__(
        self,
        *,
        headless: bool,
        verbose: bool,
        ignore_https_errors: bool,
        accept_downloads: bool,
        use_persistent_context: bool,
        enable_stealth: bool,
    ) -> None: ...

class CrawlerRunConfig:
    # Inputs: extraction and robots settings. Output: one bounded crawl configuration.
    def __init__(
        self,
        *,
        cache_mode: CacheMode,
        check_robots_txt: bool,
        page_timeout: int,
        verbose: bool,
        log_console: bool,
        css_selector: str | None,
        word_count_threshold: int,
        remove_overlay_elements: bool,
    ) -> None: ...

class AsyncWebCrawler:
    # Inputs: browser configuration. Output: a crawler with that lifecycle policy.
    def __init__(self, *, config: BrowserConfig) -> None: ...
    # Inputs: initialized crawler. Output: the active asynchronous context.
    async def __aenter__(self) -> Self: ...
    # Inputs: exit exception details. Output: browser resources released.
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None: ...
    # Inputs: source URL and run configuration. Output: native extraction result.
    async def arun(self, *, url: str, config: CrawlerRunConfig) -> object: ...
