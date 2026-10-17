import asyncio
from html.parser import HTMLParser
from urllib.parse import urldefrag, urljoin

import httpx

from owlet.check import Result, Status, check
from owlet.config import ConfigError
from owlet.context import Context

LINK_ATTRIBUTES = {"a": "href", "link": "href", "img": "src", "script": "src"}
SKIPPED_LINK_RELS = {"preconnect", "dns-prefetch"}


class _LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        # preconnect/dns-prefetch hints point at bare origins, not fetchable resources.
        if tag == "link" and set((attributes.get("rel") or "").lower().split()) & SKIPPED_LINK_RELS:
            return
        value = attributes.get(LINK_ATTRIBUTES.get(tag, ""))
        if value:
            self.links.append(value)


def _validate_broken_links(*, max_links: int, max_concurrent_requests: int) -> None:
    if max_links < 1:
        raise ConfigError(f"max_links must be at least 1, got {max_links}.")
    if max_concurrent_requests < 1:
        raise ConfigError(f"max_concurrent_requests must be at least 1, got {max_concurrent_requests}.")


@check(validate=_validate_broken_links)
async def broken_links(ctx: Context, *, max_links: int = 50, max_concurrent_requests: int = 10) -> Result:
    """Links and resources on the page don't return 4xx/5xx (first `max_links` unique URLs)."""
    response = await ctx.get(ctx.target)
    parser = _LinkParser()
    parser.feed(response.text)

    links: list[str] = []
    for href in parser.links:
        absolute = urldefrag(urljoin(str(response.url), href)).url
        if absolute.startswith(("http://", "https://")) and absolute not in links:
            links.append(absolute)
    links = links[:max_links]

    semaphore = asyncio.Semaphore(max_concurrent_requests)
    broken = await asyncio.gather(*(_find_problem(ctx, semaphore, link) for link in links))
    problems = [problem for problem in broken if problem]

    if problems:
        return Result(Status.FAIL, f"{len(problems)} of {len(links)} links broken:", details=problems)
    return Result(Status.PASS, f"All {len(links)} links OK.")


async def _find_problem(ctx: Context, semaphore: asyncio.Semaphore, link: str) -> str | None:
    async with semaphore:
        try:
            response = await ctx.http_client.head(link, follow_redirects=True)
            # Some servers don't support HEAD or reject it; retry with GET before calling the link broken.
            if response.status_code in (403, 405, 501):
                response = await ctx.get(link)
        except (httpx.HTTPError, httpx.InvalidURL) as e:
            return f"{link} ({type(e).__name__})"
    if response.is_client_error or response.is_server_error:
        return f"{link} ({response.status_code})"
    return None
