"""Map constraints onto existing adapter parameters and apply conservative filters."""

from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

DAYS = {"day": 1, "week": 7, "month": 30, "year": 365}


def provider_options(provider, task, now=None):
    options = {}
    window = task.freshness
    if window in DAYS:
        if provider == "brave":
            options["freshness"] = {"day": "pd", "week": "pw", "month": "pm", "year": "py"}[window]
        elif provider == "serper":
            options["tbs"] = "qdr:" + {"day": "d", "week": "w", "month": "m", "year": "y"}[window]
        elif provider in {"tavily", "searxng"}:
            options["time_range"] = "month" if provider == "searxng" and window == "week" else window
        elif provider == "exa_ai":
            now = now or datetime.now(UTC)
            options["startPublishedDate"] = (now - timedelta(days=DAYS[window])).isoformat()
        # Perplexity unified adapter has no proven recency translation; post-filter applies.
    if provider == "tavily":
        options["topic"] = "news" if task.intent == "news" else "general"
    return options


def parse_date(value):
    if not value:
        return None
    try:
        date = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        try:
            date = parsedate_to_datetime(value)
        except (ValueError, TypeError, OverflowError):
            return None
    return date.replace(tzinfo=UTC) if date.tzinfo is None else date.astimezone(UTC)


def filter_results(results, task, domains, now=None):
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(days=DAYS[task.freshness]) if task.freshness in DAYS else None
    includes = [d.lower() for d in domains if not d.startswith("-")]
    excludes = [d[1:].lower() for d in domains if d.startswith("-")]
    filtered = []
    for result in results:
        parts = urlsplit(result.url)
        if parts.scheme not in {"http", "https"} or not parts.hostname or not result.title.strip():
            continue
        try:
            _ = parts.port
        except ValueError:
            continue
        host = parts.hostname.lower()

        def matches(domain, hostname=host):
            return hostname == domain or hostname.endswith("." + domain)

        if (includes and not any(matches(d) for d in includes)) or any(matches(d) for d in excludes):
            continue
        if cutoff:
            # Publication takes precedence over a later crawl timestamp.
            date = parse_date(result.date or result.last_updated)
            if date is None or date < cutoff or date > now + timedelta(days=1):
                continue
        filtered.append(result)
    return filtered
