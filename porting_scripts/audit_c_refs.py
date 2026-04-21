"""Audit per-function C source references in extracted dot modules.

For each module-level function in the extracted phase modules, check
whether its docstring (or the first few lines of its body) mentions a
C source reference.  Report MISSING for any function that doesn't.
"""
from __future__ import annotations

import re
from pathlib import Path

FILES = [
    "rank.py", "mincross.py", "position.py", "dotsplines.py",
    "cluster.py", "dotinit.py",
]
ROOT = Path("gvpy/engines/dot")

# Patterns that count as a C reference
C_REF = re.compile(
    r"(lib/dotgen|lib/common|"
    r"\b(?:rank|mincross|position|dotsplines|splines|cluster|class\d?|"
    r"fastgr|sameport|flat|acyclic|ns|dotinit|shapes|labels)\.c"
    r"|Mirrors Graphviz|C analogue|C source|C ref|Graphviz\b)"
)


def audit(path: Path) -> list[tuple[str, bool]]:
    src = path.read_text(encoding="utf-8")
    out: list[tuple[str, bool]] = []
    # Find module-level functions: ``def name(`` at column 0
    for m in re.finditer(r"^def (\w+)\(", src, re.MULTILINE):
        name = m.group(1)
        # Look at the next ~40 lines after the def for a C ref
        start = m.end()
        end = min(len(src), start + 2000)
        chunk = src[start:end]
        # Stop at the next module-level def
        next_def = re.search(r"\n(?=def \w+\()", chunk)
        if next_def:
            chunk = chunk[: next_def.start()]
        has = bool(C_REF.search(chunk))
        out.append((name, has))
    return out


def main() -> int:
    for fname in FILES:
        path = ROOT / fname
        results = audit(path)
        ok = sum(1 for _, h in results if h)
        miss = sum(1 for _, h in results if not h)
        print(f"=== {fname:14s}  {ok}/{ok + miss} have C refs ===")
        for name, has in results:
            if not has:
                print(f"  MISSING  {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
