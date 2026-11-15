"""Browser session isolation for a single-user local application. No AI credentials in the browser."""
import os
import asyncio
import re
import secrets
from urllib.parse import urlsplit

from fastapi.responses import Response
from starlette.middleware.base import BaseHTTPMiddleware

COOKIE = "kairos_session"
HEADER = "X-Kairos-CSRF"
CSP = "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; media-src 'self' blob:; font-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'"


def redact(text, keys=()):
    for key in keys:
        if key and len(key) > 6:
            text = text.replace(key, "[REDACTED]")
    return re.sub(r"(?:sk-(?:ant-)?|gsk_|AIza)[A-Za-z0-9_\-]{16,}", "[REDACTED]", text)


class LocalSecurity(BaseHTTPMiddleware):
    def __init__(self, app, token, key_reader):
        super().__init__(app)
        self.token, self.key_reader = token, key_reader
        self.session = secrets.token_hex(32)
        self.mutations = asyncio.Lock()
        self.hosts = {"localhost", "127.0.0.1", "::1"}
        self.hosts.update(x.strip().lower() for x in os.getenv("CLIPPER_TRUSTED_HOSTS", "").split(",") if x.strip())

    async def dispatch(self, request, call_next):
        try:
            host = request.url.hostname
            origin = request.headers.get("origin")
            untrusted = origin and urlsplit(origin).netloc.lower() != request.headers.get("host", "").lower()
        except ValueError:
            return Response("Untrusted request origin", status_code=403)
        # Host validation also stops DNS rebinding to the loopback service.
        if host not in self.hosts or untrusted:
            return Response("Untrusted request origin", status_code=403)
        if request.url.path.startswith("/api/"):
            cookie = request.cookies.get(COOKIE + "_" + str(request.url.port or 80), "")
            if not secrets.compare_digest(cookie.encode(), self.session.encode()):
                return Response("Open Kairos in your browser first", status_code=401)
            if request.method not in ("GET", "HEAD", "OPTIONS") and not secrets.compare_digest(request.headers.get(HEADER, "").encode(), self.token.encode()):
                return Response("Invalid session token", status_code=403)
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            async with self.mutations:
                response = await call_next(request)
        else:
            response = await call_next(request)
        if "application/json" in response.headers.get("content-type", "") and "content-disposition" not in response.headers:
            body = b"".join([chunk async for chunk in response.body_iterator])
            filtered = redact(body.decode("utf-8"), self.key_reader()).encode("utf-8")
            headers = dict(response.headers); headers.pop("content-length", None)
            response = Response(filtered, status_code=response.status_code, headers=headers, media_type="application/json")
        response.headers.update({"X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer", "Content-Security-Policy": CSP})
        if request.url.path.startswith("/api/") or request.url.path == "/":
            response.headers["Cache-Control"] = "no-store"
        if request.url.path == "/":
            response.set_cookie(COOKIE + "_" + str(request.url.port or 80), self.session, httponly=True, samesite="strict", secure=request.url.scheme == "https")
        return response
