from urllib.parse import urljoin

from owlet.check import Result
from owlet.context import Context


async def robots_txt(ctx: Context) -> list[Result]:
    robots_url = urljoin(ctx.target, "/robots.txt")
    response = await ctx.http_client.get(robots_url, follow_redirects=True)
    if not response.is_success:
        return [Result("robots_txt", False, f"{robots_url} returned status code {response.status_code}.")]
    if not response.text.strip():
        return [Result("robots_txt", False, f"{robots_url} is empty.")]
    return [Result("robots_txt", True, f"Found {robots_url}.")]


async def sitemap(ctx: Context) -> list[Result]:
    sitemap_urls = []
    robots = await ctx.http_client.get(urljoin(ctx.target, "/robots.txt"), follow_redirects=True)
    if robots.is_success:
        for line in robots.text.splitlines():
            key, _, value = line.partition(":")
            if key.strip().lower() == "sitemap" and value.strip():
                sitemap_urls.append(value.strip())
    if not sitemap_urls:
        sitemap_urls.append(urljoin(ctx.target, "/sitemap.xml"))

    sitemap_url = sitemap_urls[0]
    response = await ctx.http_client.get(sitemap_url, follow_redirects=True)
    if not response.is_success:
        return [Result("sitemap", False, f"{sitemap_url} returned status code {response.status_code}.")]
    # Sitemaps may be gzipped (.xml.gz), which we can't inspect as text, so accept them as-is.
    if sitemap_url.endswith(".gz") or "<urlset" in response.text or "<sitemapindex" in response.text:
        return [Result("sitemap", True, f"Found {sitemap_url}.")]
    return [Result("sitemap", False, f"{sitemap_url} does not look like a sitemap.")]
