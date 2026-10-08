"""version-info: dependency and runtime version inventory."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("version-info")
except PackageNotFoundError:
    __version__ = "0.0.0+unknown"
