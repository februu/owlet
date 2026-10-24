import asyncio
from collections.abc import Mapping
from enum import IntEnum

import httpx

from owlet.check import Result, Status
from owlet.config import HttpConfig
from owlet.context import Context
from owlet.plan import Plan


class ExitCode(IntEnum):
    """Process exit codes."""

    OK = 0
    """Every check passed, warned (outside strict mode) or was skipped."""
    CHECKS_FAILED = 1
    """At least one check failed or errored, or warned in strict mode."""
    USAGE_ERROR = 2
    """Owlet couldn't run: invalid command-line arguments, or a missing or invalid config."""
    INTERNAL_ERROR = 3
    """Owlet itself crashed outside a check, e.g. a check module failed to import. A bug, not a problem with the site."""
    INTERRUPTED = 130
    """The run was cancelled with Ctrl+C."""


class Owlet:
    """Runs a resolved Plan and judges its results."""

    def __init__(self, plan: Plan):
        self.plan = plan

    async def run(self) -> list[Result]:
        async with _http_client(self.plan.http, self.plan.target) as http_client:
            context = Context(target=self.plan.target, http_client=http_client, timeout_seconds=self.plan.http.timeout_seconds)
            try:
                async with asyncio.TaskGroup() as tg:
                    tasks = [
                        tg.create_task(planned.check.run(context, planned.options, planned.timeout_seconds)) for planned in self.plan.checks
                    ]
            finally:
                await context.close()
            return [result for task in tasks for result in task.result()]

    def is_failure(self, result: Result) -> bool:
        """Whether this result fails the run: FAIL and ERROR always, WARN in strict mode."""
        return result.status in (Status.FAIL, Status.ERROR) or (self.plan.strict and result.status is Status.WARN)

    def exit_code(self, results: list[Result]) -> ExitCode:
        return ExitCode.CHECKS_FAILED if any(self.is_failure(result) for result in results) else ExitCode.OK


def _http_client(settings: HttpConfig, target: str) -> httpx.AsyncClient:
    hooks = [_TargetHeaders(target, settings.headers)] if settings.headers else []
    return httpx.AsyncClient(
        timeout=settings.timeout_seconds,
        verify=settings.verify,
        limits=httpx.Limits(max_connections=settings.max_connections),
        headers={"User-Agent": settings.user_agent},
        event_hooks={"request": hooks},
    )


class _TargetHeaders:
    """A request hook that sends the configured headers only to the target's host, and only over HTTPS for an https:// target.

    httpx runs request hooks on every redirect hop and copies the previous hop's headers into the next, so this removes them
    from requests that don't qualify too, e.g. a redirect from the target to another site.
    """

    def __init__(self, target: str, headers: Mapping[str, str]):
        # Parsed by httpx like the requests are, so hosts compare the same way, e.g. international domains as punycode.
        url = httpx.URL(target)
        self.host = url.host
        self.allow_http = url.scheme == "http"
        self.headers = headers

    async def __call__(self, request: httpx.Request) -> None:
        if request.url.host == self.host and (request.url.scheme == "https" or self.allow_http):
            request.headers.update(self.headers)
        else:
            for name in self.headers:
                request.headers.pop(name, None)
