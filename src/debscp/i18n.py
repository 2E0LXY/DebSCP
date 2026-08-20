from __future__ import annotations

import gettext
import locale
from pathlib import Path

DOMAIN = "debscp"
LOCALE_DIR = Path(__file__).with_name("locale")


def translation(language: str | None = None) -> gettext.NullTranslations:
    languages = [language] if language else None
    if languages is None:
        detected = locale.getlocale()[0]
        languages = [detected] if detected else None
    return gettext.translation(DOMAIN, localedir=LOCALE_DIR, languages=languages, fallback=True)


_ = translation().gettext
