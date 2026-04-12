"""One-shot script: extract the remaining Phase 3 methods from
dot_layout.py into position.py as free functions.

For each method in METHODS:
  * Read its body from dot_layout.py
  * Append to position.py as a free function taking ``layout``
  * Replace the body in dot_layout.py with a 3-line delegating wrapper

The transformation rules are:
  * ``def _name(self ...)``  ->  ``def name(layout ...)``
  * ``self.attr``  ->  ``layout.attr``
  * ``self,``      ->  ``layout,``
  * ``self)``      ->  ``layout)``  (for standalone ``self`` at end of arg)
  * Leading 4-space class indentation removed (functions go to module scope)
  * Inner references to ``self`` inside nested function bodies are also
    renamed (since those closures would bind to the outer scope of the
    method, which is now ``layout``)

Idempotent check: if the method in dot_layout.py is already a 3-line
wrapper, skip it.

Usage:
    .venv/Scripts/python.exe tools/extract_phase3.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# Methods to extract, in declaration order.  Order doesn't matter for
# correctness (we rewrite in reverse to keep line numbers valid), but
# listing them in declaration order makes the position.py output easier
# to read.
METHODS = [
    "_compute_cluster_boxes",
    "_expand_leaves",
    "_insert_flat_label_nodes",
    "_set_ycoords",
    "_simple_x_position",
    "_median_x_improvement",
    "_bottomup_ns_x_position",
    "_resolve_cluster_overlaps",
    "_post_rankdir_keepout",
    "_center_ranks",
    "_apply_rankdir",
]

SRC = Path("gvpy/engines/dot/dot_layout.py")
DST = Path("gvpy/engines/dot/position.py")


def find_method_range(lines: list[str], name: str) -> tuple[int, int] | None:
    """Return (start_line_idx, end_line_idx_exclusive) for method ``name``.

    The range starts at ``def _name(self`` and ends at the next line at
    the same indent level that begins with ``def`` or ``class``, or at
    the end of the class/file.
    """
    start = None
    sig_re = re.compile(rf"^    def {re.escape(name)}\(")
    for i, line in enumerate(lines):
        if sig_re.match(line):
            start = i
            break
    if start is None:
        return None
    # Find end: next line that starts with "    def " or "class "
    for i in range(start + 1, len(lines)):
        if lines[i].startswith("    def ") or lines[i].startswith("class "):
            return (start, i)
    return (start, len(lines))


def is_already_wrapper(lines: list[str], start: int, end: int) -> bool:
    """True if the method body is already a delegating wrapper.

    Strict definition: the body (after the signature line) has at most
    6 lines and contains both ``from gvpy.engines.layout.dot import position``
    and ``position.`` as a function call.
    """
    body_lines = lines[start + 1:end]
    if len(body_lines) > 6:
        return False
    body = "".join(body_lines)
    return ("from gvpy.engines.layout.dot import position" in body
            and "position." in body)


def transform_body_to_function(lines: list[str], start: int, end: int,
                               method_name: str) -> list[str]:
    """Convert a method body (indented 4 spaces) into a module-level
    function definition.

    Returns new function source lines with leading 4-space indent
    removed, self->layout, method name leading-underscore stripped.
    """
    func_name = method_name.lstrip("_")
    result: list[str] = []
    for i, line in enumerate(lines[start:end]):
        # Strip one level of class indentation (4 spaces)
        if line.startswith("    "):
            line = line[4:]
        elif line.strip() == "":
            pass  # blank line is fine
        # First line (signature) becomes ``def funcname(layout...``
        if i == 0:
            # Replace "def _name(self" with "def name(layout"
            line = line.replace(f"def {method_name}(self",
                                f"def {func_name}(layout")
        # Replace self. with layout. (greedy but safe — method bodies
        # don't have non-self `.self` patterns)
        line = line.replace("self.", "layout.")
        # Standalone "self" (as arg, not attribute access)
        #   e.g. func(self)  →  func(layout)
        #   e.g. DotGraphInfo._flip_record_lr  →  unchanged
        # Word-boundary replace for "self" that isn't a prefix/suffix:
        line = re.sub(r"\bself\b", "layout", line)
        result.append(line)
    # Trim trailing blank lines
    while result and result[-1].strip() == "":
        result.pop()
    return result


def make_wrapper(method_name: str, signature_line: str) -> list[str]:
    """Build a 3-line delegating wrapper for a method.

    Preserves the original signature (including return type hint) so
    IDE tools still show the correct interface.
    """
    func_name = method_name.lstrip("_")
    indent = "        "  # 8 spaces = inside class method body
    return [
        signature_line,  # keeps `def _method(self) -> bool:` intact
        f'{indent}"""Delegates to gvpy.engines.layout.dot.position.{func_name}."""\n',
        f"{indent}from gvpy.engines.layout.dot import position\n",
        f"{indent}return position.{func_name}(self)\n",
        "\n",
    ]


def main() -> int:
    src_lines = SRC.read_text().splitlines(keepends=True)

    # Find all method ranges up-front
    ranges: dict[str, tuple[int, int]] = {}
    for name in METHODS:
        r = find_method_range(src_lines, name)
        if r is None:
            print(f"ERROR: method {name} not found in {SRC}", file=sys.stderr)
            return 1
        ranges[name] = r
        start, end = r
        size = end - start
        print(f"  {name:30s} lines {start + 1}..{end}  ({size} lines)")

    # Check for already-wrappers (idempotence)
    to_extract = []
    for name in METHODS:
        start, end = ranges[name]
        if is_already_wrapper(src_lines, start, end):
            print(f"  SKIP {name} — already a wrapper")
            continue
        to_extract.append(name)

    if not to_extract:
        print("All methods already extracted — nothing to do.")
        return 0

    # ── Extract: build new function bodies for position.py ──
    extracted_functions: list[list[str]] = []
    for name in to_extract:
        start, end = ranges[name]
        func_lines = transform_body_to_function(src_lines, start, end, name)
        extracted_functions.append(func_lines)
        print(f"  EXTRACTED {name} -> {name.lstrip('_')}")

    # ── Rewrite position.py: append new functions after existing ones ──
    dst_text = DST.read_text()
    # Append extracted functions with blank-line separators
    append_parts = [dst_text.rstrip() + "\n"]
    for func_lines in extracted_functions:
        append_parts.append("\n\n")
        append_parts.append("".join(func_lines))
    append_parts.append("\n")
    DST.write_text("".join(append_parts))

    # ── Rewrite dot_layout.py: replace bodies with wrappers ──
    # Process in REVERSE order of start line so indices stay valid
    ordered = sorted(to_extract, key=lambda n: ranges[n][0], reverse=True)
    for name in ordered:
        start, end = ranges[name]
        signature = src_lines[start]
        wrapper = make_wrapper(name, signature)
        src_lines[start:end] = wrapper

    SRC.write_text("".join(src_lines))
    print(f"\nExtracted {len(to_extract)} methods.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
