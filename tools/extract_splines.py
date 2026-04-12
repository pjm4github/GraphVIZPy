"""One-shot script: extract the Phase 4 (spline routing)
methods from dot_layout.py into splines.py as free functions.

Same transformation rules as tools/extract_mincross.py.  See that
script's docstring for full details.

Usage:
    .venv/Scripts/python.exe tools/extract_splines.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

METHODS = [
    # Entry point
    "_phase4_routing",
    # Clipping and utilities
    "_clip_compound_edges",
    "_clip_to_bb",
    "_to_bezier",
    # Endpoint calculation
    "_edge_start_point",
    "_edge_end_point",
    "_record_port_point",
    "_port_point",
    "_compute_label_pos",
    # Samehead/sametail
    "_apply_sameport",
    # Routing
    "_ortho_route",
    "_route_through_chain",
    "_boundary_point",
    "_self_loop_points",
    "_maximal_bbox",
    "_rank_box",
    "_route_regular_edge",
    # Flat edge routing
    "_classify_flat_edge",
    "_count_flat_edge_index",
    "_flat_edge_route",
    "_flat_adjacent",
    "_flat_labeled",
    "_flat_arc",
]

SRC = Path("gvpy/engines/dot/dot_layout.py")
DST = Path("gvpy/engines/dot/splines.py")


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
    return ("from gvpy.engines.layout.dot import splines" in body
            and "splines." in body)


def transform_body_to_function(lines: list[str], start: int, end: int,
                               method_name: str) -> list[str]:
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
        line = line.replace("self.", "layout.")
        line = re.sub(r"\bself\b", "layout", line)
        result.append(line)
    while result and result[-1].strip() == "":
        result.pop()
    return result


def make_wrapper(method_name: str, lines: list[str],
                 start: int, sig_end: int) -> list[str]:
    func_name = method_name.lstrip("_")
    sig_lines = lines[start:sig_end + 1]
    indent = "        "
    body = [
        f'{indent}"""Delegates to gvpy.engines.layout.dot.splines.{func_name}."""\n',
        f"{indent}from gvpy.engines.layout.dot import splines\n",
        f"{indent}return splines.{func_name}(self, *args, **kwargs)\n",
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
        print(f"  {name:30s} lines {start + 1}..{end}  "
              f"(size={end - start})")

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
