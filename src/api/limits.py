"""Bound upload bodies before multipart parsing, using temporary disk storage."""

from collections.abc import Callable
from tempfile import TemporaryFile

from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class UploadBodyLimit:
    def __init__(
        self, app: ASGIApp, max_bytes: int, record_rejection: Callable[[str, str, str], None]
    ) -> None:
        self.app = app
        self.max_bytes = max_bytes
        self.record_rejection = record_rejection

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] != "/v1/documents":
            await self.app(scope, receive, send)
            return
        received = 0
        with TemporaryFile() as body:
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                chunk = message.get("body", b"")
                received += len(chunk)
                if received > self.max_bytes:
                    await run_in_threadpool(
                        self.record_rejection,
                        "",
                        "file_too_large",
                        "The upload request exceeds the size limit.",
                    )
                    response = JSONResponse(
                        status_code=413,
                        content={
                            "error": {
                                "code": "file_too_large",
                                "message": "The upload request exceeds the size limit.",
                            }
                        },
                    )
                    await response(scope, receive, send)
                    return
                await run_in_threadpool(body.write, chunk)
                if not message.get("more_body", False):
                    break
            body.seek(0)
            replayed = False

            async def replay() -> Message:
                nonlocal replayed
                if replayed:
                    return await receive()
                chunk = await run_in_threadpool(body.read, 65536)
                more = body.tell() < received
                replayed = not more
                return {"type": "http.request", "body": chunk, "more_body": more}

            await self.app(scope, replay, send)
