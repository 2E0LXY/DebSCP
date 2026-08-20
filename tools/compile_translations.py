#!/usr/bin/env python3
"""Compile the project's small gettext PO catalogs without external msgfmt."""

from __future__ import annotations

import ast
import struct
import sys
from pathlib import Path


def parse_po(path: Path) -> dict[str, str]:
    messages: dict[str, str] = {}
    msgid: list[str] = []
    msgstr: list[str] = []
    section: list[str] | None = None
    for raw in path.read_text(encoding="utf-8").splitlines() + ['msgid ""']:
        line = raw.strip()
        if line.startswith("msgid "):
            if msgid and msgstr:
                messages["".join(msgid)] = "".join(msgstr)
            msgid, msgstr = [ast.literal_eval(line[6:])], []
            section = msgid
        elif line.startswith("msgstr "):
            msgstr = [ast.literal_eval(line[7:])]
            section = msgstr
        elif line.startswith('"') and section is not None:
            section.append(ast.literal_eval(line))
    return messages


def compile_mo(messages: dict[str, str], destination: Path) -> None:
    keys = sorted(messages)
    ids = b""
    values = b""
    offsets_ids: list[tuple[int, int]] = []
    offsets_values: list[tuple[int, int]] = []
    for key in keys:
        encoded = key.encode()
        offsets_ids.append((len(encoded), len(ids)))
        ids += encoded + b"\0"
        translated = messages[key].encode()
        offsets_values.append((len(translated), len(values)))
        values += translated + b"\0"
    count = len(keys)
    key_table = 7 * 4
    value_table = key_table + count * 8
    key_offset = value_table + count * 8
    value_offset = key_offset + len(ids)
    output = struct.pack("<7I", 0x950412DE, 0, count, key_table, value_table, 0, 0)
    output += b"".join(struct.pack("<2I", length, key_offset + offset) for length, offset in offsets_ids)
    output += b"".join(struct.pack("<2I", length, value_offset + offset) for length, offset in offsets_values)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(output + ids + values)


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    for source in (root / "translations").glob("*.po"):
        language = source.stem
        destination = root / "src" / "debscp" / "locale" / language / "LC_MESSAGES" / "debscp.mo"
        compile_mo(parse_po(source), destination)
        print(destination)
    return 0


if __name__ == "__main__":
    sys.exit(main())
