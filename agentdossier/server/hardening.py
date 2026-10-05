"""Request hardening: body cap (pure ASGI) and security headers."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse

CSP = (
    "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
    "font-src 'self' data:; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; "
    "base-uri 'self'; form-action 'self'"
)


class BodyCapMiddleware:
    """Pure-ASGI body cap: buffers up to ``limit`` bytes (chunked bodies included), answers 413
    beyond it, and replays the buffered body to the app otherwise. Content-Length alone is not
    enough because a client can lie about it or send chunked."""

    def __init__(self, app, limit: int):  # noqa: ANN001
        self.app, self.limit = app, limit

    async def __call__(self, scope, receive, send):  # noqa: ANN001
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        chunks: list[bytes] = []
        total = 0
        while True:
            msg = await receive()
            if msg["type"] != "http.request":
                break  # disconnect before the body ended; let the app see it
            body = msg.get("body", b"") or b""
            total += len(body)
            if total > self.limit:
                payload = b'{"error": "request body too large"}'
                await send(
                    {
                        "type": "http.response.start",
                        "status": 413,
                        "headers": [
                            (b"content-type", b"application/json"),
                            (b"content-length", str(len(payload)).encode()),
                        ],
                    }
                )
                await send({"type": "http.response.body", "body": payload})
                return
            chunks.append(body)
            if not msg.get("more_body", False):
                break
        buffered = b"".join(chunks)
        sent = False

        async def replay():  # noqa: ANN202
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": buffered, "more_body": False}
            return await receive()

        return await self.app(scope, replay, send)


def security_headers(
    *, max_body_bytes: int, hsts: bool
) -> Callable[[Request, Callable[[Request], Awaitable[Response]]], Awaitable[Response]]:
    """HTTP middleware: early 413 on a declared oversize body, then the response headers."""

    async def middleware(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        length = request.headers.get("content-length")
        if length and length.isdigit() and int(length) > max_body_bytes:
            return JSONResponse({"error": "request body too large"}, status_code=413)
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        response.headers.setdefault(
            "Cache-Control",
            "no-store"
            if request.url.path.startswith(("/api/", "/scim/", "/auth/"))
            else "public, max-age=300",
        )
        if not request.url.path.startswith("/api/docs"):
            response.headers.setdefault("Content-Security-Policy", CSP)
        if hsts:
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response

    return middleware
