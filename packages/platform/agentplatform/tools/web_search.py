"""Web search tool — search the web via Brave or Google Custom Search APIs."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Literal

from pydantic import BaseModel, Field

from agentos.tools.base import BaseTool, SideEffect


# ── Schemas ────────────────────────────────────────────────────────


class WebSearchInput(BaseModel):
    """Input schema for web search."""

    query: str = Field(..., description="Search query string")
    max_results: int = Field(default=5, ge=1, le=20, description="Maximum results to return")
    engine: Literal["brave", "google"] = Field(
        default="brave", description="Search engine to use"
    )


class SearchResult(BaseModel):
    """A single search result."""

    title: str
    url: str
    snippet: str


class WebSearchOutput(BaseModel):
    """Output schema for web search."""

    results: list[SearchResult] = Field(default_factory=list)
    total_results: int = 0
    engine: str = ""
    error: str | None = None


# ── Tool ───────────────────────────────────────────────────────────


class WebSearchTool(BaseTool):
    """Search the web using Brave Search or Google Custom Search API."""

    def __init__(
        self,
        *,
        brave_api_key: str = "",
        google_api_key: str = "",
        google_cx: str = "",
    ) -> None:
        self._brave_api_key = brave_api_key
        self._google_api_key = google_api_key
        self._google_cx = google_cx

    @property
    def name(self) -> str:
        return "web_search"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def input_schema(self) -> type[BaseModel]:
        return WebSearchInput

    @property
    def output_schema(self) -> type[BaseModel]:
        return WebSearchOutput

    @property
    def side_effect(self) -> SideEffect:
        return SideEffect.READ

    def execute(self, input_data: BaseModel) -> BaseModel:
        assert isinstance(input_data, WebSearchInput)

        if input_data.engine == "brave":
            return self._search_brave(input_data.query, input_data.max_results)
        return self._search_google(input_data.query, input_data.max_results)

    def _search_brave(self, query: str, max_results: int) -> WebSearchOutput:
        if not self._brave_api_key:
            return WebSearchOutput(error="Brave API key not configured", engine="brave")

        params = urllib.parse.urlencode({"q": query, "count": max_results})
        url = f"https://api.search.brave.com/res/v1/web/search?{params}"
        req = urllib.request.Request(url, headers={
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "X-Subscription-Token": self._brave_api_key,
        })

        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            return WebSearchOutput(error=f"Brave search failed: {exc}", engine="brave")

        results: list[SearchResult] = []
        for item in data.get("web", {}).get("results", [])[:max_results]:
            results.append(SearchResult(
                title=item.get("title", ""),
                url=item.get("url", ""),
                snippet=item.get("description", ""),
            ))

        return WebSearchOutput(
            results=results,
            total_results=len(results),
            engine="brave",
        )

    def _search_google(self, query: str, max_results: int) -> WebSearchOutput:
        if not self._google_api_key or not self._google_cx:
            return WebSearchOutput(
                error="Google API key or Custom Search Engine ID not configured",
                engine="google",
            )

        params = urllib.parse.urlencode({
            "key": self._google_api_key,
            "cx": self._google_cx,
            "q": query,
            "num": min(max_results, 10),
        })
        url = f"https://www.googleapis.com/customsearch/v1?{params}"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})

        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            return WebSearchOutput(error=f"Google search failed: {exc}", engine="google")

        results: list[SearchResult] = []
        for item in data.get("items", [])[:max_results]:
            results.append(SearchResult(
                title=item.get("title", ""),
                url=item.get("link", ""),
                snippet=item.get("snippet", ""),
            ))

        return WebSearchOutput(
            results=results,
            total_results=len(results),
            engine="google",
        )
