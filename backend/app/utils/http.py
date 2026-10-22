"""HTTP configuration and localized errors shared by the separate applications."""
from fastapi import FastAPI, HTTPException, Request
from fastapi.exception_handlers import http_exception_handler, request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from ..dependencies import request_language
from ..domain.errors import DomainError, detail_for, status_for
from ..domain.messages import Message, localize

def api_docs_urls(config) -> dict[str, str | None]:
    return {
        "docs_url": None if config.is_production else "/docs",
        "redoc_url": None if config.is_production else "/redoc",
        "openapi_url": None if config.is_production else "/openapi.json",
    }


# WP29: an error's text follows the language the screen asked for (Accept-Language);
# a request that names no language gets every message as written, as before.
async def domain_error_handler(request: Request, exc: DomainError):
    # Reuse FastAPI's serializer so bytes, headers and bodyless codes agree.
    return await http_exception_handler(
        request,
        HTTPException(status_code=status_for(exc), detail=detail_for(exc, request_language(request))),
    )


async def localized_http_exception_handler(request: Request, exc: StarletteHTTPException):
    language = request_language(request)
    if language is not None:
        exc = StarletteHTTPException(exc.status_code, detail=localize(exc.detail, language), headers=exc.headers)
    return await http_exception_handler(request, exc)


async def localized_validation_error_handler(request: Request, exc: RequestValidationError):
    # A schema validator's own Message replaces pydantic's "Value error, …" line;
    # pydantic's built-in messages (missing field, wrong type) stay as pydantic writes them.
    language = request_language(request)
    if language is not None:
        errors = []
        for error in exc.errors():
            cause = (error.get("ctx") or {}).get("error")
            text = cause.args[0] if isinstance(cause, ValueError) and len(cause.args) == 1 else None
            errors.append({**error, "msg": text.in_language(language)} if isinstance(text, Message) else error)
        exc = RequestValidationError(errors, body=exc.body)
    return await request_validation_exception_handler(request, exc)


def install_exception_handlers(app: FastAPI):
    app.add_exception_handler(DomainError, domain_error_handler)
    app.add_exception_handler(StarletteHTTPException, localized_http_exception_handler)
    app.add_exception_handler(RequestValidationError, localized_validation_error_handler)
