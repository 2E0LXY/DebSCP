from __future__ import annotations

import keyring
from keyring.errors import KeyringError, NoKeyringError

_SERVICE = "io.github.2E0LXY.DebSCP"


class CredentialStore:
    """Stores session passwords in the operating system credential service."""

    def get(self, session_name: str) -> str | None:
        try:
            return keyring.get_password(_SERVICE, session_name)
        except NoKeyringError:
            return None
        except KeyringError as exc:
            raise RuntimeError(f"Cannot read password from the system credential store: {exc}") from exc

    def set(self, session_name: str, password: str) -> None:
        try:
            keyring.set_password(_SERVICE, session_name, password)
        except KeyringError as exc:
            raise RuntimeError(f"Cannot save password in the system credential store: {exc}") from exc

    def delete(self, session_name: str) -> None:
        try:
            keyring.delete_password(_SERVICE, session_name)
        except (keyring.errors.PasswordDeleteError, NoKeyringError):
            pass
        except KeyringError as exc:
            raise RuntimeError(f"Cannot delete password from the system credential store: {exc}") from exc
