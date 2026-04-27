"""Side-by-side C vs Py cluster-crossing comparison for one DOT file.

Runs both engines on the given DOT, parses each SVG with the metric
already used by ``visual_audit.py``, and reports a one-line table:

  measure              C       Py     delta
  cluster_crossings    N1      N2     N2-N1

Usage:
    python _c_vs_py_crossings.py test_data/1879.dot [--svg-out PREFIX]
"""
from __future__ import annotations
import argparse
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "porting_scripts"))

from gvpy.grammar.gv_reader import read_dot_file  # noqa: E402
from gvpy.engines.layout.dot.dot_layout import DotLayout  # noqa: E402
from visual_audit import count_c_crossings, parse_c_svg  # noqa: E402

DOT_C = (
    "C:/Users/pmora/OneDrive/Documents/Git/GitHub/graphviz/"
    "cmake-build-debug-mingw/cmd/dot/dot.exe"
)


def _cluster_membership(g) -> dict[str, set[str]]:
    """Map cluster_name → set(member_node_names).

    ``g.subgraphs`` is a sequence of subgraph names (strings); the
    actual subgraph object lives in ``g._subgraphs[name]`` (or via
    ``g.get_subgraph(name)``).  Walk recursively for nested clusters.
    """
    out: dict[str, set[str]] = {}
    sub_names = getattr(g, "subgraphs", None) or []
    for name in sub_names:
        sg = None
        if hasattr(g, "_subgraphs"):
            sg = g._subgraphs.get(name)
        elif hasattr(g, "get_subgraph"):
            sg = g.get_subgraph(name)
        if sg is None:
            continue
        sg_name = getattr(sg, "name", name)
        if sg_name and sg_name.startswith("cluster"):
            out[sg_name] = set(getattr(sg, "nodes", ()) or ())
        # Recurse into all subgraphs (may host nested clusters).
        for k, v in _cluster_membership(sg).items():
            out.setdefault(k, set()).update(v)
    return out


def render_c(dot_path: Path, out_svg: Path) -> str:
    subprocess.run(
        [DOT_C, "-Tsvg", str(dot_path), "-o", str(out_svg)],
        check=True, capture_output=True, text=True)
    return out_svg.read_text(encoding="utf-8", errors="replace")


def render_py(dot_path: Path, out_svg: Path) -> str:
    subprocess.run(
        [sys.executable, "gvcli.py", "-Tsvg", str(dot_path),
         "-o", str(out_svg)],
        check=True, cwd=str(REPO), capture_output=True, text=True,
        env={**os.environ, "PYTHONHASHSEED": "0"})
    return out_svg.read_text(encoding="utf-8", errors="replace")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dot_path")
    ap.add_argument("--svg-out", default=None,
                    help="Prefix for keeping SVGs (defaults to /tmp)")
    args = ap.parse_args()

    dot_path = Path(args.dot_path).resolve()
    prefix = args.svg_out or "/tmp/_cvspy"
    c_svg_path = Path(f"{prefix}_c.svg")
    p_svg_path = Path(f"{prefix}_py.svg")

    g = read_dot_file(str(dot_path))
    membership = _cluster_membership(g)

    c_svg = render_c(dot_path, c_svg_path)
    p_svg = render_py(dot_path, p_svg_path)

    c_clusters, c_edges = parse_c_svg(c_svg)
    p_clusters, p_edges = parse_c_svg(p_svg)
    c_cross = count_c_crossings(c_svg, membership)
    p_cross = count_c_crossings(p_svg, membership)

    print(f"=== C vs Py crossings ({dot_path.name}) ===")
    print(f"  {'measure':<22}  {'C':>6}  {'Py':>6}  {'Δ (Py-C)':>10}")
    print(f"  {'─'*22}  {'─'*6}  {'─'*6}  {'─'*10}")
    print(f"  {'edges (parsed)':<22}  "
          f"{len(c_edges):>6}  {len(p_edges):>6}  "
          f"{len(p_edges)-len(c_edges):>+10}")
    print(f"  {'clusters (parsed)':<22}  "
          f"{len(c_clusters):>6}  {len(p_clusters):>6}  "
          f"{len(p_clusters)-len(c_clusters):>+10}")
    print(f"  {'cluster_crossings':<22}  "
          f"{c_cross:>6}  {p_cross:>6}  {p_cross-c_cross:>+10}")
    print(f"  C SVG:  {c_svg_path}")
    print(f"  Py SVG: {p_svg_path}")


if __name__ == "__main__":
    main()
