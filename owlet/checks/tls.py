import asyncio
import contextlib
import ssl
from datetime import UTC, datetime
from urllib.parse import urlsplit

from owlet.check import Result, Status, check
from owlet.config import ConfigError
from owlet.context import Context

CONNECT_TIMEOUT_SECONDS = 10


def _validate_ssl_certificate(*, fail_days: int, warn_days: int) -> None:
    if fail_days > warn_days:
        raise ConfigError(f"fail_days ({fail_days}) must not be greater than warn_days ({warn_days}).")


@check(validate=_validate_ssl_certificate)
async def ssl_certificate(ctx: Context, *, fail_days: int = 14, warn_days: int = 30) -> Result:
    """Certificate verifies and has at least `fail_days` days before expiry (warns under `warn_days`)."""
    parts = urlsplit(ctx.target)
    if parts.scheme != "https":
        return Result(Status.SKIP, "Site is not served over HTTPS.")

    host = parts.hostname
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, parts.port or 443, ssl=ssl.create_default_context(), server_hostname=host),
            timeout=CONNECT_TIMEOUT_SECONDS,
        )
    except ssl.SSLCertVerificationError as e:
        return Result(Status.FAIL, f"Certificate verification failed: {e.verify_message}.")

    try:
        cert = writer.get_extra_info("peercert")
    finally:
        writer.close()
        with contextlib.suppress(OSError):
            await writer.wait_closed()

    expires = datetime.fromtimestamp(ssl.cert_time_to_seconds(cert["notAfter"]), UTC)
    days_left = (expires - datetime.now(UTC)).days
    message = f"Certificate valid, expires {expires:%Y-%m-%d} ({days_left} days left)."
    if days_left < fail_days:
        return Result(Status.FAIL, message)
    if days_left < warn_days:
        return Result(Status.WARN, message)
    return Result(Status.PASS, message)
