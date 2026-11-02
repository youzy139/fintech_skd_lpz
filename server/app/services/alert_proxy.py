from __future__ import annotations

import asyncio
from urllib.error import HTTPError, URLError
from urllib.request import Request as HttpRequest, urlopen

from fastapi import Request, Response

from app.core.observability import current_request_id
from app.services.remote_alert import AlertServiceError


async def forward_alert_request(request: Request, base_url: str, timeout_seconds: float) -> Response:
    query = f"?{request.url.query}" if request.url.query else ""
    headers = {"X-Request-ID": current_request_id(), "Accept": "application/json"}

    def send() -> tuple[int, bytes, str]:
        upstream = HttpRequest(base_url.rstrip("/") + request.url.path + query, headers=headers, method=request.method)
        try:
            with urlopen(upstream, timeout=timeout_seconds) as response:
                return response.status, response.read(), response.headers.get("Content-Type", "application/json")
        except HTTPError as error:
            return error.code, error.read(), error.headers.get("Content-Type", "application/json")
        except (URLError, TimeoutError, OSError) as error:
            raise AlertServiceError("预警服务暂时不可用") from error

    status, payload, content_type = await asyncio.to_thread(send)
    return Response(content=payload, status_code=status, media_type=content_type)
