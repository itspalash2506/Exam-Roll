"""Request body size limit, enforced before multipart parsing begins (P0-6).

Starlette's built-in `max_part_size` (passable to `File(...)`) only guards
NON-FILE multipart parts. File parts are spooled to disk with no cap at all
before the route handler runs — so upload.py's own per-file check
(`stream_upload_to_job_dir` in file_utils.py) never gets a chance to fire
until after an arbitrarily large body has already landed on disk.

This is deliberately a PURE ASGI middleware — a plain callable class, not
`@app.middleware("http")` / `BaseHTTPMiddleware` — because a BaseHTTPMiddleware
wraps `call_next()` and only regains control once the route handler (and
therefore Starlette's own multipart parsing) has already finished with the
body. Sitting on the raw ASGI `receive` channel means this middleware sees
every body chunk before Starlette's request-parsing machinery does anything
with it at all.

Registration order (DECISIONS.md is the place for anything non-obvious, and
this qualifies): Starlette's LAST-added middleware runs FIRST — verified
empirically, since it's easy to get backwards by intuition. So this must be
added in main.py AFTER every other `add_middleware`/`@app.middleware` call,
not before, for it to actually be the outermost check that runs before CORS,
logging, or routing ever see the request.
"""

import json


class _RequestEntityTooLarge(Exception):
    """Internal signal: the streamed body crossed the configured limit."""


class BodySizeLimitMiddleware:
    def __init__(self, app, max_bytes: int):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Fast path: a truthful Content-Length lets us reject before reading
        # a single byte of the body. A missing or lying header falls through
        # to the streaming counter below — never trusted on its own.
        declared = self._declared_content_length(scope)
        if declared is not None and declared > self.max_bytes:
            await self._send_413(send)
            return

        total = 0

        async def counted_receive():
            nonlocal total
            message = await receive()
            if message["type"] == "http.request":
                total += len(message.get("body", b""))
                if total > self.max_bytes:
                    raise _RequestEntityTooLarge()
            return message

        response_started = False

        async def tracking_send(message):
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, counted_receive, tracking_send)
        except _RequestEntityTooLarge:
            if not response_started:
                await self._send_413(send)
            # else: the downstream app already began responding before the
            # limit was crossed — this codebase's endpoints all read the
            # full body before writing anything, so this branch is not
            # expected to be reached in practice. Nothing safe is left to do
            # but let the connection close rather than send a second
            # "http.response.start".

    @staticmethod
    def _declared_content_length(scope) -> int | None:
        for name, value in scope.get("headers") or []:
            if name == b"content-length":
                try:
                    return int(value)
                except ValueError:
                    return None
        return None

    @staticmethod
    async def _send_413(send) -> None:
        body = json.dumps({"data": None, "error": "Request body too large"}).encode("utf-8")
        await send({
            "type": "http.response.start",
            "status": 413,
            "headers": [(b"content-type", b"application/json")],
        })
        await send({"type": "http.response.body", "body": body})
