"""DebSCP: a native Linux dual-pane SFTP client."""

__version__ = "0.2.0"

from .api import Client

__all__ = ["Client", "__version__"]
