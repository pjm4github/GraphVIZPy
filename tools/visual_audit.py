"""Compare Python layout vs. C dot.exe across ``test_data/`` using the
edge-crosses-non-member-cluster metric.

For each ``.dot`` file the script:
  1. Runs the Python layout engine in-process and counts edges whose
     routed polyline crosses a non-member cluster bbox.
  2. Runs ``dot.exe -Tsvg``, parses the SVG, and applies the same
     bezier-sample / bbox-cross metric to the C output.
  3. Writes a per-graph markdown row, plus a ranked summary of graphs
     where Python is worse than C (regression signal).

Usage::

    PYTHONPATH=. .venv/Scripts/python.exe tools/visual_audit.py
    PYTHONPATH=. .venv/Scripts/python.exe tools/visual_audit.py --limit 20
    PYTHONPATH=. .venv/Scripts/python.exe tools/visual_audit.py \\
        --files test_data/1332.dot test_data/aa1332.dot

Writes ``audit_report.md`` in repo root by default.
"""
from __future__ import annotations

import argparse
import multiprocessing
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

DOT_EXE = Path(
    r"C:\Users\pmora\OneDrive\Documents\Git\GitHub\graphviz"
    r"\cmake-build-debug-mingw\cmd\dot\dot.exe"
)
TEST_DIR = REPO_ROOT / "test_data"
REPORT_PATH = REPO_ROOT / "audit_report.md"
PER_FILE_TIMEOUT = 60.0   # seconds — per side


# ═══════════════════════════════════════════════════════════════════
#  SVG parsing — cluster bboxes + edge paths from C dot.exe output.
# ═══════════════════════════════════════════════════════════════════

_CLUSTER_BLOCK = re.compile(
    r'<g[^>]*class="cluster"[^>]*>(.*?)</g>', re.DOTALL,
)
_EDGE_BLOCK = re.compile(
    r'<g[^>]*class="edge"[^>]*>(.*?)</g>', re.DOTALL,
)
_TITLE = re.compile(r'<title>([^<]*)</title>')
_POLYGON_POINTS = re.compile(r'<polygon[^/>]*\bpoints="([^"]+)"')
_PATH_D = re.compile(r'<path[^/>]*\bd="([^"]+)"')
_NUM_PAIR = re.compile(r'(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)')


def _html_unescape(s: str) -> str:
    return s.replace("&gt;", ">").replace("&lt;", "<").replace("&amp;", "&")


def _bbox_from_polygon(points_attr: str) -> tuple[float, float, float, float] | None:
    """Extract (x1, y1, x2, y2) from the 5-point rectangle written by dot.exe."""
    pts = _NUM_PAIR.findall(points_attr)
    if not pts:
        return None
    xs = [float(x) for x, _ in pts]
    ys = [float(y) for _, y in pts]
    return (min(xs), min(ys), max(xs), max(ys))


def _points_from_path_d(d_attr: str) -> list[tuple[float, float]]:
    """Extract all (x, y) pairs from an SVG path ``d`` attribute.

    dot.exe emits ``M x,y C x,y x,y x,y C …`` — every number pair is an
    absolute control point.  For our crossing metric the Bezier vs.
    polyline distinction is handled by the downstream sampler; here we
    just return the raw sequence.
    """
    return [(float(x), float(y)) for x, y in _NUM_PAIR.findall(d_attr)]


def parse_c_svg(svg: str) -> tuple[dict[str, tuple[float, float, float, float]],
                                    list[tuple[str, str, list[tuple[float, float]], bool]]]:
    """Extract (cluster_name → bbox) map and edge list from a C dot SVG.

    Returns ``(clusters, edges)`` where each edge is
    ``(tail_name, head_name, control_points, is_bezier)``.  ``is_bezier``
    is inferred from the SVG path command letters: presence of ``C``
    (cubic curveto) → bezier control-point list; otherwise interpret
    the points as a polyline (ortho / line output).
    """
    clusters: dict[str, tuple[float, float, float, float]] = {}
    for m in _CLUSTER_BLOCK.finditer(svg):
        block = m.group(1)
        title_m = _TITLE.search(block)
        poly_m = _POLYGON_POINTS.search(block)
        if not title_m or not poly_m:
            continue
        name = _html_unescape(title_m.group(1)).strip()
        bb = _bbox_from_polygon(poly_m.group(1))
        if bb is not None:
            clusters[name] = bb

    edges: list[tuple[str, str, list[tuple[float, float]], bool]] = []
    for m in _EDGE_BLOCK.finditer(svg):
        block = m.group(1)
        title_m = _TITLE.search(block)
        path_m = _PATH_D.search(block)
        if not title_m or not path_m:
            continue
        title = _html_unescape(title_m.group(1)).strip()
        # C writes directed arrows as "a->b", undirected as "a--b".
        sep = "->" if "->" in title else "--"
        if sep not in title:
            continue
        t, h = title.split(sep, 1)
        # Strip ":port" suffixes — we only need node identity.
        t = t.split(":", 1)[0].strip()
        h = h.split(":", 1)[0].strip()
        d_attr = path_m.group(1)
        pts = _points_from_path_d(d_attr)
        if len(pts) >= 2:
            # Any uppercase/lowercase C is a cubic bezier command.
            is_bezier = "C" in d_attr or "c" in d_attr
            edges.append((t, h, pts, is_bezier))
    return clusters, edges


# ═══════════════════════════════════════════════════════════════════
#  Crossing metric.
# ═══════════════════════════════════════════════════════════════════

def _sample_bezier(pts: list[tuple[float, float]],
                   is_bezier: bool,
                   samples_per_seg: int = 12) -> list[tuple[float, float]]:
    """Densify *pts* to a polyline for bbox-overlap tests.

    *is_bezier* is the authoritative choice — the audit parses the
    SVG path to set it correctly.  When ``False`` we treat points as
    polyline anchors (the right thing for ortho / line output).
    """
    n = len(pts)
    if n < 2:
        return list(pts)
    if not is_bezier:
        return list(pts)
    out = [pts[0]]
    for base in range(0, n - 1, 3):
        p0, c1, c2, p3 = pts[base:base + 4]
        for k in range(1, samples_per_seg + 1):
            t = k / samples_per_seg
            s = 1 - t
            out.append((
                s*s*s*p0[0] + 3*s*s*t*c1[0] + 3*s*t*t*c2[0] + t*t*t*p3[0],
                s*s*s*p0[1] + 3*s*s*t*c1[1] + 3*s*t*t*c2[1] + t*t*t*p3[1],
            ))
    return out


def _segments_cross_bbox(pts, bb, is_bezier: bool) -> bool:
    x1, y1, x2, y2 = bb
    sampled = _sample_bezier(pts, is_bezier=is_bezier)
    for (ax, ay), (bx, by) in zip(sampled, sampled[1:]):
        if max(ax, bx) < x1 or min(ax, bx) > x2:
            continue
        if max(ay, by) < y1 or min(ay, by) > y2:
            continue
        return True
    return False


def count_c_crossings(svg: str,
                      cluster_membership: dict[str, set[str]]) -> int:
    """Count edges in *svg* whose path crosses a non-member cluster bbox."""
    clusters, edges = parse_c_svg(svg)
    count = 0
    for tail, head, pts, is_bezier in edges:
        for cname, bb in clusters.items():
            members = cluster_membership.get(cname, set())
            if tail in members or head in members:
                continue
            if _segments_cross_bbox(pts, bb, is_bezier=is_bezier):
                count += 1
                break
    return count


# ═══════════════════════════════════════════════════════════════════
#  Audit runner.
# ═══════════════════════════════════════════════════════════════════

@dataclass
class Row:
    filename: str
    py_nodes: int = 0
    py_edges: int = 0
    py_crossings: int = 0
    c_edges: int = 0
    c_crossings: int = 0
    delta: int = 0
    status: str = "ok"
    note: str = ""


def _python_audit_worker(dot_path_str: str, out: dict) -> None:
    """Body of the Python audit — runs in a subprocess so a hang is
    catchable.  Writes metrics to *out* (a ``multiprocessing.Manager.dict``).
    """
    try:
        from gvpy.engines.layout.dot.dot_layout import DotGraphInfo
        from gvpy.grammar.gv_reader import read_dot_file
        sys.path.insert(0, str(REPO_ROOT / "tools"))
        from count_cluster_crossings import count_crossings  # noqa: E402

        graph = read_dot_file(dot_path_str)
        layout = DotGraphInfo(graph)
        layout.layout()

        out["membership"] = {cl.name: list(cl.nodes) for cl in layout._clusters}
        out["nodes"] = len([ln for ln in layout.lnodes.values() if not ln.virtual])
        out["edges"] = len([le for le in layout.ledges if not le.virtual])
        py_cross = count_crossings(dot_path_str, use_channel=False)
        out["crossings"] = len(py_cross)
        out["ok"] = True
    except Exception as ex:
        out["ok"] = False
        out["err"] = f"{type(ex).__name__}: {str(ex)[:120]}"


def _python_audit(dot_path: Path) -> dict:
    """Run Python layout in a subprocess bounded by PER_FILE_TIMEOUT."""
    mgr = multiprocessing.Manager()
    out = mgr.dict({"ok": False, "err": ""})
    p = multiprocessing.Process(target=_python_audit_worker,
                                 args=(str(dot_path), out))
    p.start()
    p.join(timeout=PER_FILE_TIMEOUT)
    if p.is_alive():
        p.terminate()
        p.join(5)
        if p.is_alive():
            p.kill()
        raise TimeoutError(f"Python layout exceeded {PER_FILE_TIMEOUT}s")
    if not out.get("ok"):
        raise RuntimeError(out.get("err", "unknown python failure"))
    return {
        "membership": {k: set(v) for k, v in out["membership"].items()},
        "nodes": out["nodes"],
        "edges": out["edges"],
        "crossings": out["crossings"],
    }


def _c_audit(dot_path: Path, membership: dict[str, set[str]]) -> dict:
    """Run dot.exe -Tsvg, return (edges, crossings)."""
    proc = subprocess.run(
        [str(DOT_EXE), "-Tsvg", str(dot_path)],
        capture_output=True, timeout=PER_FILE_TIMEOUT,
    )
    svg = proc.stdout.decode("utf-8", "replace")
    # dot.exe frequently returns rc=1 with warnings but still writes a
    # valid SVG.  Treat as failure only when stdout is missing the SVG
    # header (i.e. genuinely no output).
    if "<svg" not in svg:
        raise RuntimeError(
            f"dot.exe rc={proc.returncode}, no SVG in stdout: "
            f"{proc.stderr.decode('utf-8', 'replace')[:200]}"
        )
    _, edges = parse_c_svg(svg)
    return {
        "edges": len(edges),
        "crossings": count_c_crossings(svg, membership),
    }


def audit_file(dot_path: Path) -> Row:
    row = Row(filename=dot_path.name)
    # Python side.
    try:
        py = _python_audit(dot_path)
    except TimeoutError:
        row.status = "PY_TIMEOUT"
        return row
    except Exception as ex:
        row.status = "PY_FAIL"
        row.note = f"{type(ex).__name__}: {str(ex)[:90]}"
        return row
    row.py_nodes = py["nodes"]
    row.py_edges = py["edges"]
    row.py_crossings = py["crossings"]

    # C side.
    try:
        c = _c_audit(dot_path, py["membership"])
    except subprocess.TimeoutExpired:
        row.status = "C_TIMEOUT"
        return row
    except Exception as ex:
        row.status = "C_FAIL"
        row.note = f"{type(ex).__name__}: {str(ex)[:90]}"
        return row
    row.c_edges = c["edges"]
    row.c_crossings = c["crossings"]
    row.delta = row.py_crossings - row.c_crossings
    return row


def _emit_report(rows: list[Row], out: Path) -> None:
    ok = [r for r in rows if r.status == "ok"]
    fails = [r for r in rows if r.status != "ok"]
    regressions = sorted([r for r in ok if r.delta > 0],
                         key=lambda r: -r.delta)
    clean = [r for r in ok if r.py_crossings == 0 and r.c_crossings == 0]
    py_total = sum(r.py_crossings for r in ok)
    c_total = sum(r.c_crossings for r in ok)

    lines = [
        "# Visual Audit — Python vs. C dot.exe",
        "",
        f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "Metric: **edges whose routed spline crosses a non-member "
        "cluster bbox** (sampled bezier → bbox intersection).  "
        "A relative signal, not a visual-quality absolute.",
        "",
        "## Summary",
        "",
        f"- Graphs audited: **{len(rows)}** "
        f"({len(ok)} ok, {len(fails)} errored/timeout)",
        f"- Graphs clean on both sides (0 crossings): **{len(clean)}**",
        f"- Python regression cases (py > c): **{len(regressions)}**",
        f"- Total Python crossings: **{py_total}**",
        f"- Total C crossings: **{c_total}**",
        f"- Net delta (py − c): **{py_total - c_total:+d}**",
        "",
        "## Top regression graphs (py > c)",
        "",
        "| File | Py nodes | Py edges | Py cross | C cross | Δ |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for r in regressions[:20]:
        lines.append(
            f"| {r.filename} | {r.py_nodes} | {r.py_edges} | "
            f"{r.py_crossings} | {r.c_crossings} | {r.delta:+d} |"
        )
    if not regressions:
        lines.append("| _(none — Python matches or beats C everywhere)_ | | | | | |")

    lines += [
        "",
        "## Failed / timed out",
        "",
        "| File | Status | Note |",
        "|---|---|---|",
    ]
    for r in fails:
        lines.append(f"| {r.filename} | {r.status} | {r.note} |")
    if not fails:
        lines.append("| _(none)_ | | |")

    lines += [
        "",
        "## Full results",
        "",
        "| File | Status | Py nodes | Py edges | Py cross | C edges | C cross | Δ |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for r in sorted(rows, key=lambda r: r.filename):
        delta_str = f"{r.delta:+d}" if r.status == "ok" else "–"
        lines.append(
            f"| {r.filename} | {r.status} | {r.py_nodes} | {r.py_edges} | "
            f"{r.py_crossings} | {r.c_edges} | {r.c_crossings} | {delta_str} |"
        )
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--files", nargs="*", type=Path,
                    help="Specific .dot files to audit (default: all in test_data/)")
    ap.add_argument("--limit", type=int, default=None,
                    help="Stop after N files (useful for a quick run)")
    ap.add_argument("--out", type=Path, default=REPORT_PATH)
    args = ap.parse_args()

    files: list[Path]
    if args.files:
        files = sorted(args.files)
    else:
        files = sorted(TEST_DIR.glob("*.dot"))
    if args.limit:
        files = files[: args.limit]

    if not DOT_EXE.exists():
        print(f"error: dot.exe not found at {DOT_EXE}", file=sys.stderr)
        return 1

    rows: list[Row] = []
    for i, f in enumerate(files, 1):
        t0 = time.time()
        row = audit_file(f)
        dt = time.time() - t0
        flag = (f"py{row.py_crossings}/c{row.c_crossings}"
                if row.status == "ok" else row.status)
        print(f"[{i}/{len(files)}] {f.name:32s} {flag:14s} {dt:5.1f}s")
        rows.append(row)

    _emit_report(rows, args.out)
    print(f"\nReport -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
