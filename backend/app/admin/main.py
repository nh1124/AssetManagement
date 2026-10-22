"""Separate administrator process: uvicorn app.admin.main:app --host 127.0.0.1."""
from pathlib import Path
from fastapi import FastAPI
from starlette.exceptions import HTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.staticfiles import StaticFiles

from ..config import settings
from ..utils.http import api_docs_urls, install_exception_handlers
from ..utils.observability import RequestLogMiddleware, setup_logging
from .auth import StepUpRequired, step_up_handler
from .middleware import OriginGuard, SecurityHeaders
from .routers import admins, audit, clients, me, overview, session, settings as settings_routes


class AdminSPA(StaticFiles):
    async def get_response(self, path, scope):
        if path == "admin/api" or path.startswith("admin/api/"):
            raise HTTPException(404)
        try:
            return await super().get_response(path, scope)
        except HTTPException as exc:
            if exc.status_code != 404 or scope["method"] != "GET":
                raise
            return await super().get_response("index.html", scope)


class AdminApplication(FastAPI):
    def build_middleware_stack(self):
        # Decorate the complete error/guard stack so even guard refusals and
        # unhandled errors have headers. Logging remains outermost.
        return RequestLogMiddleware(SecurityHeaders(super().build_middleware_stack()), component="admin")


def create_app(config=settings):
    config.validate_admin_production_settings()
    setup_logging()
    app = AdminApplication(title="AssetManagement Admin", **api_docs_urls(config))
    app.state.config = config
    install_exception_handlers(app)
    app.add_exception_handler(StepUpRequired, step_up_handler)
    for module in (session, me, admins, overview, clients, settings_routes, audit):
        for route in module.router.routes:
            app.add_api_route(route.path, route.endpoint, methods=route.methods,
                              response_model=route.response_model, status_code=route.status_code)

    @app.get("/health")
    def health():
        return {"status": "healthy"}

    if config.admin_ui_dir and Path(config.admin_ui_dir).is_dir():
        app.mount("/", AdminSPA(directory=config.admin_ui_dir, html=True), name="admin-ui")

    # Starlette adds each new middleware outside the previous one.
    app.add_middleware(OriginGuard, allowed_origins=[v.strip() for v in config.admin_allowed_origins.split(",") if v.strip()])
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=[v.strip() for v in config.admin_allowed_hosts.split(",") if v.strip()], www_redirect=False)
    return app


app = create_app()
