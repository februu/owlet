from dataclasses import dataclass

import httpx


@dataclass
class Context:

    http_client: httpx.AsyncClient

    