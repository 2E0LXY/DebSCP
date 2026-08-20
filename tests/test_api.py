from debscp.api import Client
from debscp.backends.base import BackendCapabilities
from debscp.models import SessionConfig


class APIBackend:
    capabilities = BackendCapabilities(recursive=True)

    def __init__(self):
        self.calls = []

    def mkdir(self, path):
        self.calls.append(("mkdir", path))

    def rename(self, source, destination):
        self.calls.append(("rename", source, destination))

    def remove_tree(self, path):
        self.calls.append(("remove-tree", path))


def test_python_api_exposes_file_management_and_capabilities() -> None:
    client = Client(SessionConfig("test", "host", "user"))
    backend = APIBackend()
    client.backend = backend
    client.mkdir("/new")
    client.rename("/old", "/new")
    client.remove_tree("/tree")
    assert backend.calls == [("mkdir", "/new"), ("rename", "/old", "/new"), ("remove-tree", "/tree")]
    assert client.capabilities.recursive


def test_python_api_uses_stored_password_when_not_explicit(monkeypatch) -> None:
    captured = {}

    class FakeStore:
        def get(self, name):
            assert name == "test"
            return "stored-secret"

    def backend(config, password):
        captured["password"] = password
        return APIBackend()

    monkeypatch.setattr("debscp.api.CredentialStore", FakeStore)
    monkeypatch.setattr("debscp.api.create_backend", backend)
    Client(SessionConfig("test", "host", "user"))
    assert captured == {"password": "stored-secret"}
