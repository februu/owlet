import httpx
import pytest

from owlet.check import Status
from owlet.config import ConfigError

pytestmark = pytest.mark.anyio

TARGET = "https://site.test"


def redirect(location: str, status: int = 302) -> httpx.Response:
    return httpx.Response(status, headers={"Location": location})


# http_status


async def test_2xx_passes(site, run_check):
    site.serve({TARGET: httpx.Response(200)})

    (result,) = await run_check("http_status")

    assert (result.status, result.summary, result.details) == (Status.PASS, "Got 200.", ())
    assert result.data == {"status_code": 200, "final_url": TARGET, "redirects": 0}


async def test_any_2xx_passes(site, run_check):
    site.serve({TARGET: httpx.Response(204)})

    (result,) = await run_check("http_status")

    assert (result.status, result.summary) == (Status.PASS, "Got 204.")


async def test_redirects_within_the_limit_pass_and_list_each_hop(site, run_check):
    site.serve(
        {
            TARGET: redirect("https://www.site.test/", 301),
            "https://www.site.test/": redirect("/home"),
            "https://www.site.test/home": httpx.Response(200),
        }
    )

    (result,) = await run_check("http_status")

    assert result.status is Status.PASS
    assert result.summary == "Got 200 after 2 redirect(s), ending at https://www.site.test/home."
    assert result.details == (
        "301 https://site.test -> https://www.site.test/",
        "302 https://www.site.test/ -> https://www.site.test/home",
    )
    assert result.data == {"status_code": 200, "final_url": "https://www.site.test/home", "redirects": 2}


async def test_more_redirects_than_max_redirects_warn(site, run_check):
    site.serve({TARGET: redirect("/a"), "https://site.test/a": redirect("/b"), "https://site.test/b": httpx.Response(200)})

    (result,) = await run_check("http_status", max_redirects=1)

    assert result.status is Status.WARN
    assert result.summary == "Got 200 after 2 redirect(s) (more than 1), ending at https://site.test/b."
    assert len(result.details) == 2


async def test_redirects_up_to_max_redirects_pass(site, run_check):
    site.serve({TARGET: redirect("/a"), "https://site.test/a": httpx.Response(200)})

    (result,) = await run_check("http_status", max_redirects=1)

    assert result.status is Status.PASS


async def test_max_redirects_0_warns_on_any_redirect(site, run_check):
    site.serve({TARGET: redirect("/a"), "https://site.test/a": httpx.Response(200)})

    (result,) = await run_check("http_status", max_redirects=0)

    assert result.status is Status.WARN


@pytest.mark.parametrize("status", [400, 404, 410, 500, 503])
async def test_4xx_and_5xx_fail(site, run_check, status):
    site.serve({TARGET: httpx.Response(status)})

    (result,) = await run_check("http_status")

    assert (result.status, result.summary) == (Status.FAIL, f"Got {status}.")
    assert result.data["status_code"] == status


async def test_error_after_redirects_fails_and_says_where_it_ended(site, run_check):
    site.serve({TARGET: redirect("/gone")})

    (result,) = await run_check("http_status")

    assert result.status is Status.FAIL
    assert result.summary == "Got 404 after 1 redirect(s), ending at https://site.test/gone."
    assert result.details == ("302 https://site.test -> https://site.test/gone",)


async def test_failing_status_fails_even_beyond_max_redirects(site, run_check):
    site.serve({TARGET: redirect("/a"), "https://site.test/a": redirect("/gone")})

    (result,) = await run_check("http_status", max_redirects=0)

    assert result.status is Status.FAIL


async def test_redirect_without_location_fails(site, run_check):
    site.serve({TARGET: httpx.Response(302)})

    (result,) = await run_check("http_status")

    assert (result.status, result.summary) == (Status.FAIL, "Got 302 with no Location header.")


async def test_redirect_without_location_after_a_redirect_says_where_it_ended(site, run_check):
    site.serve({TARGET: redirect("/a"), "https://site.test/a": httpx.Response(307)})

    (result,) = await run_check("http_status")

    assert result.summary == "Got 307 with no Location header after 1 redirect(s), ending at https://site.test/a."


async def test_3xx_that_is_not_a_redirect_fails_without_blaming_location(site, run_check):
    site.serve({TARGET: httpx.Response(300, headers={"Location": "/a"})})

    (result,) = await run_check("http_status")

    assert (result.status, result.summary) == (Status.FAIL, "Got 300.")


async def test_redirect_loop_fails(site, run_check):
    site.serve({TARGET: redirect("/a"), "https://site.test/a": redirect("/b"), "https://site.test/b": redirect("/a")})

    (result,) = await run_check("http_status")

    assert (result.status, result.summary) == (Status.FAIL, "TooManyRedirects: Exceeded maximum allowed redirects.")


async def test_unreachable_target_fails(site, run_check):
    def refuse(request):
        raise httpx.ConnectError("Connection refused", request=request)

    site.respond = refuse

    (result,) = await run_check("http_status")

    assert (result.status, result.summary) == (Status.FAIL, "ConnectError: Connection refused")


async def test_negative_max_redirects_is_a_config_error(run_check):
    with pytest.raises(ConfigError, match="max_redirects must be at least 0, got -1"):
        await run_check("http_status", max_redirects=-1)
