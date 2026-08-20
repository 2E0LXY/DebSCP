from debscp.policies import PresetStore, TransferPreset


def test_transfer_masks() -> None:
    preset = TransferPreset("source", include=["src/**", "*.md"], exclude=["**/*.pyc", "src/vendor/**"])
    assert preset.matches("src/debscp/main.py")
    assert preset.matches("README.md")
    assert not preset.matches("src/vendor/library.py")
    assert not preset.matches("image.png")


def test_preset_store_round_trip(tmp_path) -> None:
    store = PresetStore(tmp_path / "presets.json")
    values = [TransferPreset("docs", ["*.md"], ["private*"])]
    store.save(values)
    assert store.load() == values
