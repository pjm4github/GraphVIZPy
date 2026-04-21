"""One-shot script: extract the Phase 1 (rank assignment) methods
from dot_layout.py into rank.py as free functions.

Same transformation rules as filters/extract_mincross.py and
filters/extract_splines.py.  See those porting_scripts for details.

Usage:
    .venv/Scripts/python.exe filters/extract_rank.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# Methods to extract, ordered to mirror the pipeline in phase1_rank.
METHODS = [
    "_phase1_rank",
    "_break_cycles",
    "_classify_edges",
    "_classify_flat_edges",
    "_inject_same_rank_edges",
    "_network_simplex_rank",
    "_cluster_aware_rank",
    "_apply_rank_constraints",
    "_compact_ranks",
    "_add_virtual_nodes",
    "_build_ranks",
]

SRC = Path("gvpy/engines/dot/dot_layout.py")
DST = Path("gvpy/engines/dot/rank.py")


def find_signature_end(lines: list[str], start: int) -> int:
    depth = 0
    for i in range(start, len(lines)):
        line = lines[i]
        stripped = re.sub(r"#.*$", "", line)
        stripped = re.sub(r"'[^']*'", "''", stripped)
        stripped = re.sub(r'"[^"]*"', '""', stripped)
        for ch in stripped:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
        if depth <= 0 and line.rstrip().endswith(":"):
            return i
    return start


def find_method_range(lines: list[str], name: str) -> tuple[int, int] | None:
    start = None
    sig_re = re.compile(rf"^    def {re.escape(name)}\(")
    for i, line in enumerate(lines):
        if sig_re.match(line):
            start = i
            break
    if start is None:
        return None
    sig_end = find_signature_end(lines, start)
    last_body_line = sig_end
    for i in range(sig_end + 1, len(lines)):
        line = lines[i]
        if line.rstrip("\n").strip() == "":
            continue
        indent_spaces = len(line) - len(line.lstrip(" "))
        if indent_spaces >= 8:
            last_body_line = i
            continue
        break
    return (start, last_body_line + 1)


def is_already_wrapper(lines: list[str], start: int, end: int) -> bool:
    sig_end = find_signature_end(lines, start)
    body_lines = lines[sig_end + 1:end]
    if len(body_lines) > 6:
        return False
    body = "".join(body_lines)
    return ("from gvpy.engines.layout.dot import rank" in body
            and "rank." in body)


def transform_body_to_function(lines: list[str], start: int, end: int,
                               method_name: str) -> list[str]:
    """Transform a class method body into a free-function body.

    Bug fix 2026-04-12: the previous version used ``re.sub(r"\\bself\\b", ...)``
    which replaced ``self`` even inside string literals — e.g. an
    edge type literal ``"self"`` got rewritten to ``"layout"``.
    Now we skip replacements inside strings (single-quoted, double-quoted,
    triple-quoted) by walking the line character by character with a
    simple state machine.
    """
    func_name = method_name.lstrip("_")
    result: list[str] = []
    for i, line in enumerate(lines[start:end]):
        abs_i = start + i
        if line.startswith("    "):
            line = line[4:]
        if abs_i == start:
            line = re.sub(
                rf"\bdef {re.escape(method_name)}\(",
                f"def {func_name}(",
                line,
            )
        line = _replace_self_outside_strings(line)
        result.append(line)
    while result and result[-1].strip() == "":
        result.pop()
    return result


def _replace_self_outside_strings(line: str) -> str:
    """Replace ``self.attr`` -> ``layout.attr`` and standalone ``self``
    -> ``layout``, but only outside string literals.

    Handles single-quoted, double-quoted, and triple-quoted strings,
    plus escaped quotes inside strings.  This avoids the regression
    where edge_type literals like ``"self"`` were getting clobbered.
    """
    out: list[str] = []
    i = 0
    n = len(line)
    while i < n:
        ch = line[i]
        # Detect string start (triple or single)
        if ch in ('"', "'"):
            quote = ch
            triple = line[i:i + 3] == quote * 3
            if triple:
                end = line.find(quote * 3, i + 3)
                if end == -1:
                    out.append(line[i:])
                    return "".join(out)
                out.append(line[i:end + 3])
                i = end + 3
            else:
                # Single-line string — find closing quote, skip escapes
                j = i + 1
                while j < n:
                    if line[j] == "\\" and j + 1 < n:
                        j += 2
                        continue
                    if line[j] == quote:
                        j += 1
                        break
                    j += 1
                out.append(line[i:j])
                i = j
            continue
        # Detect comment — everything to end of line is unchanged
        if ch == "#":
            out.append(line[i:])
            return "".join(out)
        # Regular char — copy
        out.append(ch)
        i += 1
    text = "".join(out)
    # Now do replacements only on non-string portions.  We re-build by
    # walking the line again and substituting in non-string regions.
    return _apply_self_to_layout(line)


def _apply_self_to_layout(line: str) -> str:
    """Walk the line in segments (non-string vs string) and apply
    self -> layout only to non-string segments.
    """
    result: list[str] = []
    i = 0
    n = len(line)
    while i < n:
        ch = line[i]
        if ch in ('"', "'"):
            quote = ch
            triple = line[i:i + 3] == quote * 3
            if triple:
                end = line.find(quote * 3, i + 3)
                if end == -1:
                    result.append(line[i:])
                    return "".join(result)
                result.append(line[i:end + 3])
                i = end + 3
                continue
            j = i + 1
            while j < n:
                if line[j] == "\\" and j + 1 < n:
                    j += 2
                    continue
                if line[j] == quote:
                    j += 1
                    break
                j += 1
            result.append(line[i:j])
            i = j
            continue
        if ch == "#":
            # Comment — copy verbatim to end
            result.append(line[i:])
            return "".join(result)
        # Find next string start or comment
        next_str = n
        for k in range(i, n):
            if line[k] in ('"', "'", "#"):
                next_str = k
                break
        segment = line[i:next_str]
        # Apply self->layout in this code segment
        segment = segment.replace("self.", "layout.")
        segment = re.sub(r"\bself\b", "layout", segment)
        result.append(segment)
        i = next_str
    return "".join(result)


def make_wrapper(method_name: str, lines: list[str],
                 start: int, sig_end: int) -> list[str]:
    func_name = method_name.lstrip("_")
    sig_lines = lines[start:sig_end + 1]
    indent = "        "
    body = [
        f'{indent}"""Delegates to gvpy.engines.layout.dot.rank.{func_name}."""\n',
        f"{indent}from gvpy.engines.layout.dot import rank\n",
        f"{indent}return rank.{func_name}(self, *args, **kwargs)\n",
        "\n",
    ]
    full_sig = "".join(sig_lines).rstrip()
    m = re.match(rf"^(\s*def {re.escape(method_name)}\()"
                 r"([^)]*?)"
                 r"(\))"
                 r"(\s*->\s*.+?)?"
                 r":\s*$",
                 full_sig, re.DOTALL)
    if m:
        prefix = m.group(1)
        ret_anno = m.group(4) or ""
        new_sig = f"{prefix}self, *args, **kwargs){ret_anno}:\n"
        return [new_sig, *body]
    else:
        print(f"  WARN: could not rewrite signature for {method_name}",
              file=sys.stderr)
        return [*sig_lines, *body]


def main() -> int:
    src_lines = SRC.read_text().splitlines(keepends=True)
    ranges: dict[str, tuple[int, int, int]] = {}
    for name in METHODS:
        r = find_method_range(src_lines, name)
        if r is None:
            print(f"ERROR: method {name} not found in {SRC}", file=sys.stderr)
            return 1
        start, end = r
        sig_end = find_signature_end(src_lines, start)
        ranges[name] = (start, sig_end, end)
        print(f"  {name:30s} lines {start + 1}..{end}  (size={end - start})")

    to_extract = []
    for name in METHODS:
        start, sig_end, end = ranges[name]
        if is_already_wrapper(src_lines, start, end):
            print(f"  SKIP {name} -- already a wrapper")
            continue
        to_extract.append(name)

    if not to_extract:
        print("All methods already extracted.")
        return 0

    extracted_functions: list[list[str]] = []
    for name in to_extract:
        start, sig_end, end = ranges[name]
        func_lines = transform_body_to_function(src_lines, start, end, name)
        extracted_functions.append(func_lines)
        print(f"  EXTRACTED {name} -> {name.lstrip('_')}")

    dst_text = DST.read_text()
    append_parts = [dst_text.rstrip() + "\n"]
    for func_lines in extracted_functions:
        append_parts.append("\n\n")
        append_parts.append("".join(func_lines))
    append_parts.append("\n")
    DST.write_text("".join(append_parts))

    ordered = sorted(to_extract, key=lambda n: ranges[n][0], reverse=True)
    for name in ordered:
        start, sig_end, end = ranges[name]
        wrapper = make_wrapper(name, src_lines, start, sig_end)
        src_lines[start:end] = wrapper

    SRC.write_text("".join(src_lines))
    print(f"\nExtracted {len(to_extract)} methods.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
