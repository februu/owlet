import asyncio
import contextlib
import ssl
from datetime import UTC, datetime
from urllib.parse import urlsplit

from owlet.check import Result
from owlet.context import Context

MIN_DAYS_LEFT = 14
CONNECT_TIMEOUT_SECONDS = 10


async def ssl_certificate(ctx: Context) -> list[Result]:
    parts = urlsplit(ctx.target)
    if parts.scheme != "https":
        return [Result("ssl_certificate", False, "Site is not served over HTTPS.")]

    host = parts.hostname
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, parts.port or 443, ssl=ssl.create_default_context(), server_hostname=host),
            timeout=CONNECT_TIMEOUT_SECONDS,
        )
    except ssl.SSLCertVerificationError as e:
        return [Result("ssl_certificate", False, f"Certificate verification failed: {e.verify_message}.")]

    try:
        cert = writer.get_extra_info("peercert")
    finally:
        writer.close()
        with contextlib.suppress(OSError):
            await writer.wait_closed()

    expires = datetime.fromtimestamp(ssl.cert_time_to_seconds(cert["notAfter"]), UTC)
    days_left = (expires - datetime.now(UTC)).days
    return [
        Result(
            "ssl_certificate",
            days_left >= MIN_DAYS_LEFT,
            f"Certificate valid, expires {expires:%Y-%m-%d} ({days_left} days left).",
        )
    ]
