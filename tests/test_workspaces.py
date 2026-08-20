from debscp.workspaces import WorkspaceStore


def test_workspace_store(tmp_path) -> None:
    store = WorkspaceStore(tmp_path / "workspaces.json")
    store.set("production", ["web", "db", "web"])
    assert store.load() == {"production": ["web", "db"]}
    store.delete("production")
    assert store.load() == {}
