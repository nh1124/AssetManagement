"""Admin-only browser boundary and response headers."""
from starlette.responses import JSONResponse
from ..dependencies import request_language
from ..domain.messages import Message, localize
from starlette.requests import Request

CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
       "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; "
       "base-uri 'self'; form-action 'self'")


class OriginGuard:
    def __init__(self, app, allowed_origins):
        self.app, self.allowed_origins = app, frozenset(allowed_origins)

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["method"] in {"POST", "PUT", "PATCH", "DELETE"}:
            request = Request(scope)
            if request.headers.get("origin") not in self.allowed_origins:
                response = JSONResponse({"detail": localize(Message("Untrusted request origin.", ja="許可されていない送信元です。"), request_language(request))}, status_code=403)
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


class SecurityHeaders:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def secured(message):
            if message["type"] == "http.response.start":
                values = {"content-security-policy": CSP, "x-frame-options": "DENY",
                          "x-content-type-options": "nosniff", "referrer-policy": "no-referrer"}
                if scope["path"] == "/admin/api" or scope["path"].startswith("/admin/api/"):
                    values["cache-control"] = "no-store"
                headers = [(key, value) for key, value in message.get("headers", []) if key.decode().lower() not in values]
                message = {**message, "headers": headers + [(k.encode(), v.encode()) for k, v in values.items()]}
            await send(message)
        await self.app(scope, receive, secured)
