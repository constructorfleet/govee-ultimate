"""Minimal async HTTP client primitives used for testing."""

from __future__ import annotations

import inspect
import json
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urljoin, urlparse

__all__ = [
    "AsyncClient",
    "HTTPError",
    "HTTPStatusError",
    "MockTransport",
    "Request",
    "Response",
    "URL",
]


class HTTPError(Exception):
    """Base error type raised for HTTP client failures."""


class HTTPStatusError(HTTPError):
    """Raised when a response indicates an HTTP error status."""

    def __init__(
        self,
        message: str,
        *,
        request: Request | None = None,
        response: Response | None = None,
    ) -> None:  # type: ignore[name-defined]
        """Store the originating request and response for error inspection."""

        super().__init__(message)
        self.request = request
        self.response = response


class URL(str):
    """Lightweight URL representation supporting relative resolution."""

    def __new__(cls, url: str, base_url: str | URL | None = None) -> URL:
        """Create a new URL object optionally relative to a base URL."""
        if base_url is not None:
            url = urljoin(str(base_url), url)
        obj = str.__new__(cls, url)
        obj._parsed = urlparse(url)
        return obj

    @property
    def path(self) -> str:
        """Return the path component of the URL."""

        return self._parsed.path


class Request:
    """Simplified HTTP request container passed to transport handlers."""

    def __init__(
        self,
        method: str,
        url: str | URL,
        *,
        content: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        """Store request metadata for transport handlers."""

        self.method = method.upper()
        self.url = URL(str(url)) if not isinstance(url, URL) else url
        self.headers = headers or {}
        self.content = content or b""


class Response:
    """Simplified HTTP response returned by transport handlers."""

    def __init__(
        self,
        status_code: int,
        *,
        json: Any | None = None,
        text: str | None = None,
        content: bytes | None = None,
    ) -> None:
        """Capture response payload data and metadata."""

        self.status_code = status_code
        self._json = json
        if content is not None:
            self.content = content
        elif json is not None:
            self.content = json_dumps(json)
        elif text is not None:
            self.content = text.encode()
        else:
            self.content = b""
        self.text = self.content.decode(errors="ignore")
        self.headers: dict[str, str] = {}
        self.request: Request | None = None

    def json(self) -> Any:
        """Return a decoded JSON representation of the response body."""

        if self._json is not None:
            return self._json
        if not self.content:
            return None
        return json.loads(self.content.decode())

    def raise_for_status(self) -> None:
        """Raise an HTTPStatusError when the response is unsuccessful."""

        if self.status_code >= 400:
            message = f"HTTP error: status code {self.status_code}"
            raise HTTPStatusError(message, request=self.request, response=self)


class MockTransport:
    """Transport that routes requests to a user-supplied handler."""

    def __init__(
        self, handler: Callable[[Request], Response | Awaitable[Response]]
    ) -> None:
        """Store the callable responsible for handling requests."""

        self._handler = handler

    async def handle_async_request(self, request: Request) -> Response:
        """Execute the handler coroutine and ensure a Response is returned."""

        result = self._handler(request)
        if inspect.isawaitable(result):
            result = await result
        if not isinstance(result, Response):
            raise TypeError("MockTransport handler must return a Response instance")
        return result

    async def aclose(self) -> None:
        """Close the transport if it exposes an async close hook."""

        return None


class AsyncClient:
    """Highly constrained async HTTP client used within tests."""

    def __init__(
        self,
        *,
        transport: MockTransport | None = None,
        base_url: str | URL | None = None,
    ) -> None:
        """Configure the async client with optional transport and base URL."""

        self._transport = transport or MockTransport(
            lambda request: Response(
                500, text=f"No transport handler for {request.url}"
            )
        )
        self.base_url = URL(str(base_url)) if base_url is not None else None

    async def request(
        self,
        method: str,
        url: str | URL,
        *,
        json: Any | None = None,
        headers: dict[str, str] | None = None,
    ) -> Response:
        """Dispatch a request through the configured transport."""

        resolved = self._resolve_url(url)
        content: bytes | None = None
        if json is not None:
            content = json_dumps(json)
        request = Request(method, resolved, content=content, headers=headers)
        response = await self._transport.handle_async_request(request)
        response.request = request
        return response

    async def post(self, url: str | URL, *args: Any, **kwargs: Any) -> Response:
        """Issue a POST request."""

        return await self.request("POST", url, *args, **kwargs)

    async def get(self, url: str | URL, *args: Any, **kwargs: Any) -> Response:
        """Issue a GET request."""

        return await self.request("GET", url, *args, **kwargs)

    async def aclose(self) -> None:
        """Close the underlying transport if it supports async closing."""

        close = getattr(self._transport, "aclose", None)
        if close is None:
            return None
        result = close()
        if inspect.isawaitable(result):
            await result
        return None

    def _resolve_url(self, url: str | URL) -> URL:
        """Combine a relative URL with the client's configured base URL."""

        if isinstance(url, URL):
            return url
        if self.base_url is not None:
            return URL(url, base_url=self.base_url)
        return URL(url)


def json_dumps(data: Any) -> bytes:
    return json.dumps(data, separators=(",", ":")).encode()
