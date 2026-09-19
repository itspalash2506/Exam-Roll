"""Body size limit middleware (P0-6, DECISIONS.md 2026-09-19).

Tested at the raw ASGI level (scope/receive/send) rather than through the
real app + httpx client: BodySizeLimitMiddleware is registered as the
OUTERMOST middleware specifically so it runs before Starlette does any
multipart parsing, and httpx's automatic Content-Length handling makes it
hard to reliably fake a lying header through a real client — the ASGI-level
test is both more precise (it's testing the actual mechanism, not a proxy
for it) and not subject to httpx quirks.

The "no partial job directory left on disk" property from the design
follows structurally rather than needing its own filesystem test: when the
middleware raises mid-stream, it does so from inside `counted_receive()`,
which FastAPI's `File(...)` dependency resolution is still awaiting — the
upload.py route function body (the code that actually creates a job
directory) has not started executing yet and never will for this request.
"""

import pytest

from app.middleware.body_size_limit import BodySizeLimitMiddleware


async def _echo_app(scope, receive, send):
    """A minimal downstream app: drains the whole body, then responds 200."""
    while True:
        message = await receive()
        if not message.get("more_body", False):
            break
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})


def _scope(headers=None):
    return {"type": "http", "headers": headers or []}


def _chunked_receive(chunks: list[bytes]):
    """Returns a receive() coroutine that streams `chunks` with no
    Content-Length header involved — mirrors a client that doesn't declare
    its body size upfront (chunked transfer encoding)."""
    remaining = list(chunks)

    async def receive():
        if remaining:
            chunk = remaining.pop(0)
            return {"type": "http.request", "body": chunk, "more_body": bool(remaining)}
        return {"type": "http.request", "body": b"", "more_body": False}

    return receive


async def test_rejects_on_declared_content_length_without_reading_body():
    mw = BodySizeLimitMiddleware(_echo_app, max_bytes=100)
    sent = []

    async def send(message):
        sent.append(message)

    async def receive():
        raise AssertionError(
            "body must never be read when Content-Length alone already exceeds the limit"
        )

    scope = _scope(headers=[(b"content-length", b"1000")])
    await mw(scope, receive, send)

    assert sent[0]["type"] == "http.response.start"
    assert sent[0]["status"] == 413


async def test_allows_body_within_the_limit():
    mw = BodySizeLimitMiddleware(_echo_app, max_bytes=100)
    sent = []

    async def send(message):
        sent.append(message)

    scope = _scope()
    await mw(scope, _chunked_receive([b"hello", b"world"]), send)

    assert sent[0]["status"] == 200


async def test_aborts_mid_stream_when_no_content_length_declared():
    """The slow path: no Content-Length header, so the middleware counts
    bytes as they stream past and must abort once the running total crosses
    the limit — even though no single chunk on its own does."""
    mw = BodySizeLimitMiddleware(_echo_app, max_bytes=10)
    sent = []

    async def send(message):
        sent.append(message)

    # 5 + 5 = 10 (still within limit); + 5 more = 15 > 10.
    scope = _scope()
    await mw(scope, _chunked_receive([b"12345", b"67890", b"EXTRA"]), send)

    assert sent[0]["type"] == "http.response.start"
    assert sent[0]["status"] == 413


async def test_non_http_scope_passes_through_untouched():
    """WebSocket connections (scope type "websocket") must not be affected —
    this middleware only guards HTTP request bodies."""
    calls = []

    async def app(scope, receive, send):
        calls.append(scope["type"])

    mw = BodySizeLimitMiddleware(app, max_bytes=10)
    await mw({"type": "websocket"}, None, None)
    assert calls == ["websocket"]


async def test_malformed_content_length_header_falls_through_to_streaming():
    """A non-integer Content-Length must not crash the fast path — it falls
    through to the streaming counter instead of being trusted blindly."""
    mw = BodySizeLimitMiddleware(_echo_app, max_bytes=100)
    sent = []

    async def send(message):
        sent.append(message)

    scope = _scope(headers=[(b"content-length", b"not-a-number")])
    await mw(scope, _chunked_receive([b"short"]), send)

    assert sent[0]["status"] == 200
