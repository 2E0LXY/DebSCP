from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_only_main_launcher_is_installed_as_an_application() -> None:
    rules = (ROOT / "debian" / "rules").read_text(encoding="utf-8")
    main = (ROOT / "packaging" / "debscp.desktop").read_text(encoding="utf-8")
    helper = (ROOT / "packaging" / "debscp-send.desktop").read_text(encoding="utf-8")

    assert "Type=Application" in main
    assert "Exec=debscp-gui" in main
    assert "usr/share/applications/debscp.desktop" in rules
    assert "usr/share/kio/servicemenus/debscp-send.desktop" in rules
    assert "usr/share/applications/debscp-send.desktop" not in rules
    assert "Type=Service" in helper
    assert "Exec=debscp-send %F" in helper
