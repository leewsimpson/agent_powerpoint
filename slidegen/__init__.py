from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("pptxai1")
except PackageNotFoundError:  # pragma: no cover - best effort during development
    __version__ = "0.0.0"

__all__ = ["__version__"]
