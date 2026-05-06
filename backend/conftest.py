"""pytest configuration for backend tests.

Handles path setup for both:
- Host execution: AssetManagement/ is sys.path root, import as 'backend.app.*'
- Container execution: /app is sys.path root, import as 'app.*'
"""
import sys
import os

# When running in the Docker container, /app/app exists and 'backend' does not.
# Add a thin shim so 'backend.app' resolves to 'app' inside the container.
try:
    import backend  # noqa: F401 – already importable
except ImportError:
    # Container environment: /app is sys.path root, package is 'app'
    import types
    backend_mod = types.ModuleType("backend")
    import app as _app  # noqa: F401
    backend_mod.app = _app  # type: ignore[attr-defined]
    sys.modules["backend"] = backend_mod
    sys.modules["backend.app"] = _app

    # Re-export subpackages already imported under 'app.*'
    import importlib
    for sub in ("models", "database", "schemas"):
        fqn = f"app.{sub}"
        try:
            mod = importlib.import_module(fqn)
            sys.modules[f"backend.{fqn}"] = mod
        except ImportError:
            pass
