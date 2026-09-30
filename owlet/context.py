from dataclasses import dataclass

import httpx


@dataclass
class Context:

    target: str
    http_client: httpx.AsyncClient

    