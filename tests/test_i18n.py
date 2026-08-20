from debscp.i18n import translation


def test_spanish_catalog_is_packaged() -> None:
    assert translation("es").gettext("Connect") == "Conectar"
