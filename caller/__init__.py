"""Top-level compatibility shim for `caller`.

This file makes the package importable regardless of layout. The real
implementation lives in `caller/src/caller/`. We add that path to
``__path__`` so Python can find the src-style package.
"""
from pathlib import Path
import sys
import importlib

# If a `src/caller` layout exists, add it to the package search path so
# `import caller` resolves to the src implementation.
_here = Path(__file__).resolve().parent
_src_pkg = _here / "src" / "caller"
if _src_pkg.exists():
    # Insert before existing entries to prefer src/ implementation
    sys.path.insert(0, str(_here / "src"))

# Re-export public API from the src package
try:
    from caller import Application, default_config, CallerConfig, PdfUploader, QueryClient  # type: ignore
except Exception:
    # Best-effort fallback: import local modules (legacy layout)
    try:
        from .app import Application  # type: ignore
        from .config import default_config, CallerConfig  # type: ignore
        from .pdf_uploader import PdfUploader  # type: ignore
        from .query_client import QueryClient  # type: ignore
    except Exception:
        # If imports fail, leave package minimal - user will see ImportError when using features
        Application = None
        default_config = None
        CallerConfig = None
        PdfUploader = None
        QueryClient = None

__all__ = [
    "Application",
    "default_config",
    "CallerConfig",
    "PdfUploader",
    "QueryClient",
]

__version__ = "0.1"
