"""One-shot script: extract the Phase 2 (crossing minimization)
methods from dot_layout.py into mincross.py as free functions.

Improved over ``extract_phase3.py``:
  * Handles multi-line method signatures (tracks paren balance)
  * Wrapper passes through ``*args, **kwargs`` so any method signature
    works without the script parsing arg names

Usage:
    .venv/Scripts/python.exe filters/extract_mincross.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

METHODS = [
    "_phase2_ordering",
    "_run_mincross",
    "_remincross_full",
    "_skeleton_mincross",
    "_cluster_medians",
    "_cluster_reorder",
    "_cluster_transpose",
    "_cluster_build_ranks",
    "_order_by_weighted_median",
    "_transpose_rank",
    "_count_crossings_for_pair",
    "_count_all_crossings",
    "_count_scoped_crossings",
    "_save_ordering",
    "_restore_ordering",
    "_flat_reorder",
    "_mark_low_clusters",
    "_mval_edge",
]

SRC = Path("gvpy/engines/dot/dot_layout.py")
DST = Path("gvpy/engines/dot/mincross.py")


def find_signature_end(lines: list[str], start: int) -> int:
    """Return index of the last line of a (possibly multi-line)
    method signature starting at ``lines[start]``.

    Tracks paren depth and stops at the line that closes the signature
    with '):' or ') -> ...:'.  Correctly handles comments and string
    literals — no, not rigorously, but good enough for
    well-formatted Python source (which is what we have).
    """
    depth = 0
    for i in range(start, len(lines)):
        line = lines[i]
        # Strip comments and simple string literals — not perfect but
        # enough for our input.
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
    return start  # fallback


def find_method_range(lines: list[str], name: str) -> tuple[int, int] | None:
    """Return (start_line_idx, end_line_idx_exclusive) for method ``name``.

    The end is the index AFTER the last line that belongs to the method's
    body — detected by walking forward from the signature until we see
    a line at indent <= 4 spaces that isn't blank or a continuation of
    a body expression.  This excludes class attributes, comments, and
    blank lines that sit between this method and the next method.
    """
    start = None
    sig_re = re.compile(rf"^    def {re.escape(name)}\(")
    for i, line in enumerate(lines):
        if sig_re.match(line):
            start = i
            break
    if start is None:
        return None
    # Scan forward to find the actual last line of the method body.
    # Method body lines are indented by at least 8 spaces (one inside
    # the class + one inside the function).  Blank lines may appear
    # anywhere.  The signature itself may span multiple lines at 4-
    # space indent; after the closing ``):`` the body starts.
    sig_end = find_signature_end(lines, start)
    last_body_line = sig_end
    for i in range(sig_end + 1, len(lines)):
        line = lines[i]
        stripped_nl = line.rstrip("\n")
        if stripped_nl.strip() == "":
            # Blank line — provisionally inside, don't update last
            continue
        # Check indent
        indent_spaces = len(line) - len(line.lstrip(" "))
        if indent_spaces >= 8:
            last_body_line = i
            continue
        # indent < 8: could be a class-level construct (4-space indent)
        # or top-level (0 indent).  Either way, the method has ended.
        break
    return (start, last_body_line + 1)


def is_already_wrapper(lines: list[str], start: int, end: int) -> bool:
    """Strict check: body is a 3-4 line wrapper that references mincross."""
    # Signature may span multiple lines — find the line after it
    sig_end = find_signature_end(lines, start)
    body_lines = lines[sig_end + 1:end]
    if len(body_lines) > 6:
        return False
    body = "".join(body_lines)
    return ("from gvpy.engines.layout.dot import mincross" in body
            and "mincross." in body)


def transform_body_to_function(lines: list[str], start: int, end: int,
                               method_name: str) -> list[str]:
    """Build a free-function version of the method.

    Returns the list of lines ready to append to mincross.py.
    Handles both single-line signatures (``def _name(self, ...):``)
    and multi-line ones where ``self`` is on a separate line:

        def _name(
            self,
            arg1: int,
        ) -> ret:
    """
    func_name = method_name.lstrip("_")
    result: list[str] = []
    for i, line in enumerate(lines[start:end]):
        abs_i = start + i
        # Strip one level of class indentation (4 spaces)
        if line.startswith("    "):
            line = line[4:]
        # First line: rename the function itself (drop leading underscore)
        if abs_i == start:
            # Match ``def _name(`` whether or not ``self`` follows
            line = re.sub(
                rf"\bdef {re.escape(method_name)}\(",
                f"def {func_name}(",
                line,
            )
        # Replace self.ATTR with layout.ATTR
        line = line.replace("self.", "layout.")
        # Standalone ``self`` (not prefix/suffix of another ident) —
        # this catches the bare ``self,`` arg whether it's on the
        # first line or a continuation line.
        line = re.sub(r"\bself\b", "layout", line)
        result.append(line)
    # Trim trailing blank lines
    while result and result[-1].strip() == "":
        result.pop()
    return result


def make_wrapper(method_name: str, lines: list[str],
                 start: int, sig_end: int) -> list[str]:
    """Build a delegating wrapper that preserves the original
    (possibly multi-line) signature and passes args through.

    Uses ``*args, **kwargs`` so we don't have to parse the signature
    argument list — the original declared signature stays visible to
    IDEs for the wrapper itself, and the real signature (with types)
    lives on the function in mincross.py.
    """
    func_name = method_name.lstrip("_")
    # Collect the original signature as-is
    sig_lines = lines[start:sig_end + 1]
    indent = "        "
    body = [
        f'{indent}"""Delegates to gvpy.engines.layout.dot.mincross.{func_name}."""\n',
        f"{indent}from gvpy.engines.layout.dot import mincross\n",
        f"{indent}return mincross.{func_name}(self, *args, **kwargs)\n",
        "\n",
    ]
    # Rewrite the signature to use *args, **kwargs instead of the
    # declared args — this avoids the need to thread typed names
    # through, and keeps the wrapper simple.
    #
    # Pattern: def _method(self, ARGS):  ->  def _method(self, *args, **kwargs):
    # For a multi-line signature, we concatenate everything into one
    # line and rewrite.
    full_sig = "".join(sig_lines).rstrip()
    # Extract the return type annotation (if any) to preserve it
    m = re.match(rf"^(\s*def {re.escape(method_name)}\()"
                 r"([^)]*?)"  # non-greedy content inside parens
                 r"(\))"
                 r"(\s*->\s*.+?)?"
                 r":\s*$",
                 full_sig, re.DOTALL)
    if m:
        prefix = m.group(1)  # "    def _method("
        ret_anno = m.group(4) or ""  # " -> bool" or ""
        new_sig = f"{prefix}self, *args, **kwargs){ret_anno}:\n"
        return [new_sig, *body]
    else:
        # Fallback: keep the original signature lines verbatim
        print(f"  WARN: could not rewrite signature for {method_name}, "
              f"leaving original", file=sys.stderr)
        return [*sig_lines, *body]


def main() -> int:
    src_lines = SRC.read_text().splitlines(keepends=True)

    ranges: dict[str, tuple[int, int, int]] = {}  # name -> (start, sig_end, end)
    for name in METHODS:
        r = find_method_range(src_lines, name)
        if r is None:
            print(f"ERROR: method {name} not found in {SRC}", file=sys.stderr)
            return 1
        start, end = r
        sig_end = find_signature_end(src_lines, start)
        ranges[name] = (start, sig_end, end)
        size = end - start
        sig_lines = sig_end - start + 1
        print(f"  {name:30s} lines {start + 1}..{end}  "
              f"(size={size}, sig_lines={sig_lines})")

    to_extract = []
    for name in METHODS:
        start, sig_end, end = ranges[name]
        if is_already_wrapper(src_lines, start, end):
            print(f"  SKIP {name} -- already a wrapper")
            continue
        to_extract.append(name)

    if not to_extract:
        print("All methods already extracted -- nothing to do.")
        return 0

    # Extract bodies for mincross.py
    extracted_functions: list[list[str]] = []
    for name in to_extract:
        start, sig_end, end = ranges[name]
        func_lines = transform_body_to_function(src_lines, start, end, name)
        extracted_functions.append(func_lines)
        print(f"  EXTRACTED {name} -> {name.lstrip('_')}")

    # Append to mincross.py
    dst_text = DST.read_text()
    append_parts = [dst_text.rstrip() + "\n"]
    for func_lines in extracted_functions:
        append_parts.append("\n\n")
        append_parts.append("".join(func_lines))
    append_parts.append("\n")
    DST.write_text("".join(append_parts))

    # Rewrite dot_layout.py: replace bodies with wrappers (in reverse
    # order of start line so indices stay valid)
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
