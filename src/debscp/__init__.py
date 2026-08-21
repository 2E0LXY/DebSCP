"""DebSCP: a native Linux dual-pane SFTP client."""

__version__ = "0.5.1"

__all__ = ["Client", "__version__"]


def __getattr__(name: str):
    if name == "Client":
        from .api import Client

        return Client
    raise AttributeError(name)
