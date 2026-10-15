import asyncio
import contextlib
import ssl
from datetime import UTC, datetime
from urllib.parse import urlsplit

from owlet.check import Result, Status, check
from owlet.context import Context

MIN_DAYS_LEFT = 14
WARN_DAYS_LEFT = 30
CONNECT_TIMEOUT_SECONDS = 10


@check
async def ssl_certificate(ctx: Context) -> Result:
    """Certificate verifies and has at least MIN_DAYS_LEFT days before expiry (warns under WARN_DAYS_LEFT)."""
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
    if days_left < MIN_DAYS_LEFT:
        return Result(Status.FAIL, message)
    if days_left < WARN_DAYS_LEFT:
        return Result(Status.WARN, message)
    return Result(Status.PASS, message)
