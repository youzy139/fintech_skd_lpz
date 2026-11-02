from __future__ import annotations

import asyncio
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request as HttpRequest, urlopen

import websockets
from fastapi import Request, Response, WebSocket
from fastapi.websockets import WebSocketDisconnect
from websockets.exceptions import ConnectionClosed, InvalidHandshake

from app.core.observability import current_request_id
from app.core.auth import outgoing_auth_headers
from app.services.proxy_headers import response_headers
from app.services.remote_feature import FeatureServiceError


async def forward_feature_request(request: Request, base_url: str, timeout_seconds: float) -> Response:
    query = f"?{request.url.query}" if request.url.query else ""
    body = await request.body()
    headers = {"X-Request-ID": current_request_id(), "Accept": "application/json"}
    headers.update(outgoing_auth_headers())
    for name in ("Content-Type", "Idempotency-Key"):
        value = request.headers.get(name)
        if value:
            headers[name] = value

    def send() -> tuple[int, bytes, dict[str, str]]:
        upstream = HttpRequest(base_url.rstrip("/") + request.url.path + query, data=body or None, headers=headers, method=request.method)
        try:
            with urlopen(upstream, timeout=timeout_seconds) as response:
                return response.status, response.read(), response_headers(response.headers)
        except HTTPError as error:
            return error.code, error.read(), response_headers(error.headers)
        except (URLError, TimeoutError, OSError) as error:
            raise FeatureServiceError("特征与状态服务暂时不可用") from error

    status, payload, headers = await asyncio.to_thread(send)
    return Response(content=payload, status_code=status, headers=headers)


def websocket_url(base_url: str, path: str, query: str) -> str:
    parsed = urlsplit(base_url)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    return f"{scheme}://{parsed.netloc}{path}" + (f"?{query}" if query else "")


async def forward_feature_websocket(websocket: WebSocket, base_url: str, timeout_seconds: float) -> None:
    await websocket.accept()
    url = websocket_url(base_url, websocket.url.path, websocket.url.query)
    tasks: set[asyncio.Task[Any]] = set()
    try:
        async with websockets.connect(url, additional_headers={"X-Request-ID": current_request_id(), **outgoing_auth_headers()}, open_timeout=timeout_seconds, close_timeout=timeout_seconds, proxy=None) as upstream:
            async def client_to_upstream() -> None:
                while True:
                    message = await websocket.receive()
                    if message["type"] == "websocket.disconnect":
                        await upstream.close()
                        return
                    if message.get("text") is not None:
                        await upstream.send(message["text"])
                    elif message.get("bytes") is not None:
                        await upstream.send(message["bytes"])

            async def upstream_to_client() -> None:
                async for message in upstream:
                    if isinstance(message, bytes):
                        await websocket.send_bytes(message)
                    else:
                        await websocket.send_text(message)
                await websocket.close(code=upstream.close_code or 1000, reason=upstream.close_reason or "")

            tasks = {asyncio.create_task(client_to_upstream()), asyncio.create_task(upstream_to_client())}
            completed, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in completed:
                task.result()
    except WebSocketDisconnect:
        pass
    except ConnectionClosed as error:
        close = error.rcvd or error.sent
        await websocket.close(code=close.code if close else 1011, reason=close.reason if close else "")
    except (OSError, TimeoutError, InvalidHandshake):
        await websocket.close(code=1013)
    finally:
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        try:
            await websocket.close()
        except RuntimeError:
            pass
