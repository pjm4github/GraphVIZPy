"""One-shot script: extract cluster.py and dotinit.py methods from
dot_layout.py.

Same transformation rules as tools/extract_rank.py (which has the
string-aware self->layout substitution).  This version handles two
target modules and two method lists in a single run.

Usage:
    .venv/Scripts/python.exe tools/extract_cluster_init.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

CLUSTER_METHODS = [
    "_collect_clusters",
    "_collect_nodes_into",
    "_scan_clusters",
    "_dedup_cluster_nodes",
    "_separate_sibling_clusters",
    "_shift_cluster_nodes_y",
    "_shift_cluster_nodes_x",
]

INIT_METHODS = [
    "_init_from_graph",
    "_collect_rank_constraints",
    "_scan_subgraphs",
    "_collect_edges",
    "_collect_edges_recursive",
]

SRC = Path("gvpy/engines/dot/dot_layout.py")
CLUSTER_DST = Path("gvpy/engines/dot/cluster.py")
INIT_DST = Path("gvpy/engines/dot/dotinit.py")


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


def is_already_wrapper(lines: list[str], start: int, end: int,
                      module: str) -> bool:
    sig_end = find_signature_end(lines, start)
    body_lines = lines[sig_end + 1:end]
    if len(body_lines) > 6:
        return False
    body = "".join(body_lines)
    return (f"from gvpy.engines.dot import {module}" in body
            and f"{module}." in body)


def _apply_self_to_layout(line: str) -> str:
    """Walk the line in segments and apply self->layout only outside
    string literals and comments.  Same logic as
    tools/extract_rank.py."""
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
            result.append(line[i:])
            return "".join(result)
        next_str = n
        for k in range(i, n):
            if line[k] in ('"', "'", "#"):
                next_str = k
                break
        segment = line[i:next_str]
        segment = segment.replace("self.", "layout.")
        segment = re.sub(r"\bself\b", "layout", segment)
        result.append(segment)
        i = next_str
    return "".join(result)


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
        line = _apply_self_to_layout(line)
        result.append(line)
    while result and result[-1].strip() == "":
        result.pop()
    return result


def make_wrapper(method_name: str, lines: list[str],
                 start: int, sig_end: int, module: str) -> list[str]:
    func_name = method_name.lstrip("_")
    sig_lines = lines[start:sig_end + 1]
    indent = "        "
    body = [
        f'{indent}"""Delegates to gvpy.engines.dot.{module}.{func_name}."""\n',
        f"{indent}from gvpy.engines.dot import {module}\n",
        f"{indent}return {module}.{func_name}(self, *args, **kwargs)\n",
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


def extract_batch(src_lines: list[str], methods: list[str],
                  dst_path: Path, module_name: str) -> tuple[list[str], int]:
    """Extract a batch of methods to dst_path, return updated src_lines
    and count extracted."""
    ranges: dict[str, tuple[int, int, int]] = {}
    for name in methods:
        r = find_method_range(src_lines, name)
        if r is None:
            print(f"ERROR: method {name} not found", file=sys.stderr)
            return src_lines, 0
        start, end = r
        sig_end = find_signature_end(src_lines, start)
        ranges[name] = (start, sig_end, end)
        print(f"  {name:30s} L{start + 1}..{end}  ({end - start} lines)")

    to_extract = []
    for name in methods:
        start, sig_end, end = ranges[name]
        if is_already_wrapper(src_lines, start, end, module_name):
            print(f"  SKIP {name} (already wrapper)")
            continue
        to_extract.append(name)

    if not to_extract:
        return src_lines, 0

    extracted_functions: list[list[str]] = []
    for name in to_extract:
        start, sig_end, end = ranges[name]
        func_lines = transform_body_to_function(src_lines, start, end, name)
        extracted_functions.append(func_lines)

    # Append to dst
    dst_text = dst_path.read_text(encoding="utf-8")
    append_parts = [dst_text.rstrip() + "\n"]
    for func_lines in extracted_functions:
        append_parts.append("\n\n")
        append_parts.append("".join(func_lines))
    append_parts.append("\n")
    dst_path.write_text("".join(append_parts), encoding="utf-8")

    # Replace in src (reverse order to keep line numbers valid)
    ordered = sorted(to_extract, key=lambda n: ranges[n][0], reverse=True)
    for name in ordered:
        start, sig_end, end = ranges[name]
        wrapper = make_wrapper(name, src_lines, start, sig_end, module_name)
        src_lines[start:end] = wrapper

    return src_lines, len(to_extract)


def main() -> int:
    src_lines = SRC.read_text(encoding="utf-8").splitlines(keepends=True)

    print("=== Extracting cluster methods -> cluster.py ===")
    src_lines, n1 = extract_batch(src_lines, CLUSTER_METHODS, CLUSTER_DST,
                                  "cluster")
    print(f"Extracted {n1} cluster methods.")

    print("\n=== Extracting init methods -> dotinit.py ===")
    src_lines, n2 = extract_batch(src_lines, INIT_METHODS, INIT_DST,
                                  "dotinit")
    print(f"Extracted {n2} init methods.")

    SRC.write_text("".join(src_lines), encoding="utf-8")
    print(f"\nTotal extracted: {n1 + n2} methods")
    return 0


if __name__ == "__main__":
    sys.exit(main())
