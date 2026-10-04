"""Recommended SearXNG engines; instance availability still requires verification."""

WEB_ENGINES = ("google", "bing", "duckduckgo", "brave", "baidu", "wikipedia")
DEFAULT_ENGINES = (*WEB_ENGINES, "github", "stackoverflow", "pubmed", "arxiv", "google news")
INTENT_ENGINE_GROUPS = {
    "general": WEB_ENGINES,
    "deep": WEB_ENGINES,
    "people": WEB_ENGINES,
    "academic": ("pubmed", "arxiv", "google scholar", "semantic scholar"),
    "coding": ("github", "gitlab", "stackoverflow"),
    "news": ("bing news", "google news", "brave.news"),
}
