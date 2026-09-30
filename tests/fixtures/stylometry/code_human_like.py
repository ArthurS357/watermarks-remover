#!/usr/bin/env python3
"""Remove zero-width and other invisible characters from a text file."""

import sys
from pathlib import Path

INVISIBLE = "​‌⁠﻿"


def clean(text: str) -> tuple[str, int]:
    removed = sum(text.count(c) for c in INVISIBLE)
    return text.translate({ord(c): None for c in INVISIBLE}), removed


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: limpa.py FILE", file=sys.stderr)
        return 2
    path = Path(argv[1])
    cleaned, removed = clean(path.read_text(encoding="utf-8"))
    path.with_suffix(path.suffix + ".clean").write_text(cleaned, encoding="utf-8")
    print(f"{removed} invisible characters removed")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
