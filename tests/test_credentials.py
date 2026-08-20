from __future__ import annotations

import keyring.errors

from debscp.credentials import CredentialStore


def test_credential_store_delegates_to_os_keyring(monkeypatch) -> None:
    saved: dict[tuple[str, str], str] = {}
    monkeypatch.setattr(
        "debscp.credentials.keyring.set_password",
        lambda service, name, value: saved.__setitem__((service, name), value),
    )
    monkeypatch.setattr("debscp.credentials.keyring.get_password", lambda service, name: saved.get((service, name)))
    monkeypatch.setattr("debscp.credentials.keyring.delete_password", lambda service, name: saved.pop((service, name)))
    store = CredentialStore()
    store.set("site", "secret")
    assert store.get("site") == "secret"
    store.delete("site")
    assert store.get("site") is None


def test_missing_keyring_backend_behaves_as_no_saved_password(monkeypatch) -> None:
    def unavailable(*_args) -> None:
        raise keyring.errors.NoKeyringError()

    monkeypatch.setattr("debscp.credentials.keyring.get_password", unavailable)
    assert CredentialStore().get("site") is None
