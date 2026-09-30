import asyncio
from html.parser import HTMLParser
from urllib.parse import urldefrag, urljoin

import httpx

from owlet.check import Result
from owlet.context import Context

MAX_LINKS = 50
MAX_CONCURRENT_REQUESTS = 10
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


async def broken_links(ctx: Context) -> list[Result]:
    response = await ctx.http_client.get(ctx.target, follow_redirects=True)
    parser = _LinkParser()
    parser.feed(response.text)

    links: list[str] = []
    for href in parser.links:
        absolute = urldefrag(urljoin(str(response.url), href)).url
        if absolute.startswith(("http://", "https://")) and absolute not in links:
            links.append(absolute)
    links = links[:MAX_LINKS]

    semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
    broken = await asyncio.gather(*(_find_problem(ctx, semaphore, link) for link in links))
    problems = [problem for problem in broken if problem]

    if problems:
        return [Result("broken_links", False, f"{len(problems)} of {len(links)} links broken:\n" + "\n".join(problems))]
    return [Result("broken_links", True, f"All {len(links)} links OK.")]


async def _find_problem(ctx: Context, semaphore: asyncio.Semaphore, link: str) -> str | None:
    async with semaphore:
        try:
            response = await ctx.http_client.head(link, follow_redirects=True)
            # Some servers don't support HEAD or reject it; retry with GET before calling the link broken.
            if response.status_code in (403, 405, 501):
                response = await ctx.http_client.get(link, follow_redirects=True)
        except httpx.HTTPError as e:
            return f"    {link} ({type(e).__name__})"
    if response.is_client_error or response.is_server_error:
        return f"    {link} ({response.status_code})"
    return None
