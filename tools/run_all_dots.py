"""Run DOT files through the Python layout engine and/or C dot.exe.

Usage:
    PYTHONPATH=. .venv/Scripts/python.exe tools/run_all_dots.py

Writes a markdown table to ``test_run.md`` with 9 columns:

    | # | TODO | P Flag | File | P Date | P Time | P Result | C Time | C Result |

The **TODO** column controls what gets tested on each run:

    P       — run the Python layout engine only
    C       — run the C dot.exe only
    BOTH    — run both Python and C
    (other) — skip this file

Results are written incrementally.  The script re-reads test_run.md
before each file so you can edit TODO values in PyCharm mid-run.

Per-file timeout: 2 minutes (120 seconds).
"""
import multiprocessing
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

TIMEOUT_SEC = 120
REPO_ROOT = Path(__file__).resolve().parent.parent
MD_PATH = REPO_ROOT / "test_run.md"
TEST_DIR = REPO_ROOT / "test_data"
DOT_EXE = Path(
    r"C:\Users\pmora\OneDrive\Documents\Git\GitHub\graphviz"
    r"\cmake-build-debug-mingw\cmd\dot\dot.exe"
)


# ── Python worker (runs in a subprocess) ──────────────────────────

def _layout_file(fpath_str, result_dict):
    """Run Python layout on a single file."""
    import io
    real_stderr = sys.stderr
    sys.stderr = io.StringIO()
    try:
        from gvpy.grammar.gv_reader import read_dot
        from gvpy.engines.layout.dot.dot_layout import DotGraphInfo

        src = Path(fpath_str).read_text(encoding="utf-8", errors="replace")
        g = read_dot(src)
        layout = DotGraphInfo(g)
        result = layout.layout()
        n = len(result.get("nodes", []))
        e = len(result.get("edges", []))
        routed = sum(1 for ed in result.get("edges", []) if ed.get("points"))
        result_dict["ok"] = True
        result_dict["msg"] = f"{n} nodes, {e} edges, {routed} routed"
    except Exception as ex:
        msg = f"{type(ex).__name__}: {str(ex)[:120]}"
        result_dict["ok"] = False
        result_dict["msg"] = msg.encode("ascii", "replace").decode()
    finally:
        sys.stderr = real_stderr


def run_python(fpath, timeout=TIMEOUT_SEC):
    """Run Python layout with timeout.  Returns (status, msg, elapsed)."""
    mgr = multiprocessing.Manager()
    result_dict = mgr.dict({"ok": False, "msg": "unknown"})
    p = multiprocessing.Process(target=_layout_file,
                                args=(str(fpath), result_dict))
    t0 = time.time()
    p.start()
    p.join(timeout=timeout)
    dt = time.time() - t0

    if p.is_alive():
        p.kill()
        p.join(timeout=5)
        return "TIMEOUT", f"killed after {timeout}s", dt

    if result_dict.get("ok"):
        status = "SLOW" if dt > 10 else "OK"
        return status, result_dict["msg"], dt
    else:
        return "FAIL", result_dict.get("msg", "unknown"), dt


# ── C dot.exe runner ──────────────────────────────────────────────

def run_c_dot(fpath, timeout=TIMEOUT_SEC):
    """Run the reference C dot.exe on a file.  Returns (status, msg, elapsed)."""
    import json as _json

    if not DOT_EXE.exists():
        return "FAIL", f"dot.exe not found: {DOT_EXE}", 0.0

    t0 = time.time()
    try:
        result = subprocess.run(
            [str(DOT_EXE), "-Tjson", str(fpath)],
            capture_output=True,
            timeout=timeout,
        )
        dt = time.time() - t0
        # Try parsing JSON output regardless of returncode — C dot.exe
        # returns non-zero on warnings but still produces valid output.
        if result.stdout:
            try:
                json_text = result.stdout.decode("utf-8", errors="replace")
                data = _json.loads(json_text)
                objects = data.get("objects", [])
                edges = data.get("edges", [])
                # Filter out cluster subgraphs — only count real nodes
                n = sum(1 for o in objects if "nodes" not in o)
                e = len(edges)
                routed = sum(1 for ed in edges
                             if "_draw_" in ed or "pos" in ed)
                status = "SLOW" if dt > 10 else "OK"
                return status, f"{n} nodes, {e} edges, {routed} routed", dt
            except (_json.JSONDecodeError, KeyError, TypeError):
                pass
        # No usable output — report as FAIL with stderr
        stderr = result.stderr.decode("utf-8", errors="replace")
        msg = stderr.strip().replace("\n", "; ")[:120]
        if not msg:
            msg = f"exit code {result.returncode}"
        return "FAIL", msg, dt
    except subprocess.TimeoutExpired:
        dt = time.time() - t0
        return "TIMEOUT", f"killed after {timeout}s", dt
    except Exception as ex:
        dt = time.time() - t0
        msg = f"{type(ex).__name__}: {str(ex)[:100]}"
        return "FAIL", msg.encode("ascii", "replace").decode(), dt


# ── Markdown table I/O ────────────────────────────────────────────

# 9 columns: #, TODO, P Flag, File, P Date, P Time, P Result, C Time, C Result
TABLE_HEADER = (
    "| # | TODO | P Flag | File | P Date | P Time | P Result | C Time | C Result |\n"
    "|---|------|--------|------|--------|--------|----------|--------|----------|\n"
)

# Row tuple indices
R_TODO = 0
R_PFLAG = 1
R_PDATE = 2
R_PTIME = 3
R_PRESULT = 4
R_CTIME = 5
R_CRESULT = 6


def read_table_rows(md_path):
    """Read test_run.md.  Returns {filename: (todo, pflag, pdate, ptime, presult, ctime, cresult)}."""
    rows = {}
    if not md_path.exists():
        return rows
    for line in md_path.read_text(encoding="utf-8").splitlines():
        # Count pipes to decide format
        npipes = line.count("|")

        if npipes >= 10:
            # 9-col: | # | TODO | P Flag | File | P Date | P Time | P Result | C Time | C Result |
            m = re.match(
                r'\|\s*\d+\s*\|'
                r'\s*(.*?)\s*\|'   # TODO
                r'\s*(.*?)\s*\|'   # P Flag
                r'\s*(\S+)\s*\|'   # File
                r'\s*(.*?)\s*\|'   # P Date
                r'\s*(.*?)\s*\|'   # P Time
                r'\s*(.*?)\s*\|'   # P Result
                r'\s*(.*?)\s*\|'   # C Time
                r'\s*(.*?)\s*\|',  # C Result
                line,
            )
            if m:
                rows[m.group(3).strip()] = (
                    m.group(1).strip(),
                    m.group(2).strip(),
                    m.group(4).strip(),
                    m.group(5).strip(),
                    m.group(6).strip(),
                    m.group(7).strip(),
                    m.group(8).strip(),
                )
                continue

        if npipes >= 8:
            # 7-col: | # | TODO | Flag | File | Date | Time | Result |
            m = re.match(
                r'\|\s*\d+\s*\|'
                r'\s*(.*?)\s*\|'   # TODO
                r'\s*(.*?)\s*\|'   # Flag
                r'\s*(\S+)\s*\|'   # File
                r'\s*(.*?)\s*\|'   # Date
                r'\s*(.*?)\s*\|'   # Time
                r'\s*(.*?)\s*\|',  # Result
                line,
            )
            if m:
                rows[m.group(3).strip()] = (
                    m.group(1).strip(),
                    m.group(2).strip(),
                    m.group(4).strip(),
                    m.group(5).strip(),
                    m.group(6).strip(),
                    "",
                    "",
                )
    return rows


def create_table(md_path, files, old_rows):
    """Write test_run.md preserving all previous results.

    Rows with TODO in (P, C, BOTH) get their corresponding columns
    cleared so they'll be retested.  All other rows are preserved.
    """
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("# DOT file test run\n\n")
        f.write(f"Last run: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        f.write(TABLE_HEADER)
        for i, fp in enumerate(files):
            prev = old_rows.get(fp.name, ("", "", "", "", "", "", ""))
            todo = prev[R_TODO]
            pflag = prev[R_PFLAG]
            pdate = prev[R_PDATE]
            ptime = prev[R_PTIME]
            presult = prev[R_PRESULT]
            ctime = prev[R_CTIME]
            cresult = prev[R_CRESULT]

            tu = todo.upper()
            if tu in ("P", "BOTH"):
                pflag = ""
                pdate = ""
                ptime = ""
                presult = ""
            if tu in ("C", "BOTH"):
                ctime = ""
                cresult = ""

            f.write(f"| {i+1} | {todo} | {pflag} | {fp.name}"
                    f" | {pdate} | {ptime} | {presult}"
                    f" | {ctime} | {cresult} |\n")


def _sanitize_msg(msg: str) -> str:
    """Make a message safe for a single markdown table cell."""
    s = msg.replace("\r\n", "; ").replace("\n", "; ").replace("\r", "; ")
    s = s.replace("|", "/")
    if len(s) > 120:
        s = s[:117] + "..."
    return s


def update_row_python(md_path, filename, todo, pflag, pdate, ptime, presult):
    """Update the Python columns of a single row."""
    presult = _sanitize_msg(presult)
    text = md_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    new_lines = []
    for line in lines:
        m = re.match(
            r'(\|\s*\d+\s*\|)\s*.*?\s*\|\s*.*?\s*\|\s*'
            + re.escape(filename)
            + r'\s*\|\s*.*?\s*\|\s*.*?\s*\|\s*.*?\s*\|\s*(.*?\s*\|\s*.*?\s*\|)',
            line,
        )
        if m:
            num_col = m.group(1)
            c_cols = m.group(2)  # "ctime | cresult |"
            line = (f"{num_col} {todo} | {pflag} | {filename}"
                    f" | {pdate} | {ptime} | {presult}"
                    f" | {c_cols}")
        new_lines.append(line)
    md_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


def update_row_c(md_path, filename, todo, ctime, cresult):
    """Update the C columns of a single row, preserving Python columns."""
    cresult = _sanitize_msg(cresult)
    text = md_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    new_lines = []
    for line in lines:
        m = re.match(
            r'(\|\s*\d+\s*\|)\s*(.*?)\s*\|\s*(.*?)\s*\|\s*'
            + re.escape(filename)
            + r'\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|'
            + r'\s*.*?\s*\|\s*.*?\s*\|',
            line,
        )
        if m:
            num_col = m.group(1)
            cur_todo = m.group(2)
            pflag = m.group(3)
            pdate = m.group(4)
            ptime = m.group(5)
            presult = m.group(6)
            line = (f"{num_col} {todo} | {pflag} | {filename}"
                    f" | {pdate} | {ptime} | {presult}"
                    f" | {ctime} | {cresult} |")
        new_lines.append(line)
    md_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


# ── Main ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    multiprocessing.freeze_support()

    files = sorted(TEST_DIR.glob("*.dot")) + sorted(TEST_DIR.glob("*.gv"))
    total = len(files)

    old_rows = read_table_rows(MD_PATH)
    create_table(MD_PATH, files, old_rows)

    print(f"Running {total} DOT files, results in {MD_PATH.name}")
    print(f"Per-file timeout: {TIMEOUT_SEC}s")
    print(f"C dot.exe: {DOT_EXE}" + (" (found)" if DOT_EXE.exists() else " (NOT FOUND)"))
    print()

    counts_p = {"OK": 0, "FAIL": 0, "TIMEOUT": 0, "SLOW": 0}
    counts_c = {"OK": 0, "FAIL": 0, "TIMEOUT": 0, "SLOW": 0}
    skipped = 0
    t_all = time.time()
    today = datetime.now().strftime("%Y-%m-%d")

    for i, fpath in enumerate(files):
        rows = read_table_rows(MD_PATH)
        row = rows.get(fpath.name, ("", "", "", "", "", "", ""))
        todo = row[R_TODO].upper()

        if todo not in ("P", "C", "BOTH"):
            skipped += 1
            pflag = row[R_PFLAG]
            if pflag:
                counts_p[pflag] = counts_p.get(pflag, 0) + 1
            print(f"[{i+1:3d}/{total}] skip    {fpath.name}")
            continue

        run_p = todo in ("P", "BOTH")
        run_c = todo in ("C", "BOTH")

        # ── Python ──
        if run_p:
            update_row_python(MD_PATH, fpath.name, "----", "...", today, "", "running")
            pstatus, pmsg, pdt = run_python(fpath)
            ptime = f"{pdt:.2f}s"
            counts_p[pstatus] = counts_p.get(pstatus, 0) + 1
            update_row_python(MD_PATH, fpath.name, "----", pstatus, today, ptime, pmsg)
            p_report = f"P:{pstatus} {pdt:5.1f}s"
        else:
            p_report = ""

        # ── C dot.exe ──
        if run_c:
            cstatus, cmsg, cdt = run_c_dot(fpath)
            ctime = f"{cdt:.2f}s"
            counts_c[cstatus] = counts_c.get(cstatus, 0) + 1
            update_row_c(MD_PATH, fpath.name, "----", ctime, cmsg)
            c_report = f"C:{cstatus} {cdt:5.1f}s"
        else:
            c_report = ""

        report = "  ".join(filter(None, [p_report, c_report]))
        print(f"[{i+1:3d}/{total}] {fpath.name:40s} {report}")

    total_time = time.time() - t_all

    # Append summary
    with open(MD_PATH, "a", encoding="utf-8") as f:
        f.write(f"\n## Summary\n\n")
        f.write(f"- **Total files**: {total}\n")
        f.write(f"- **Tested**: {total - skipped}\n")
        f.write(f"- **Skipped**: {skipped}\n")
        if any(counts_p.values()):
            f.write(f"- **Python**: " + ", ".join(
                f"{k}: {v}" for k, v in counts_p.items() if v) + "\n")
        if any(counts_c.values()):
            f.write(f"- **C dot.exe**: " + ", ".join(
                f"{k}: {v}" for k, v in counts_c.items() if v) + "\n")
        f.write(f"- **Time**: {total_time:.1f}s\n")
        f.write(f"- **Finished**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

    print(f"\n{'='*70}")
    print(f"Total: {total}  Tested: {total - skipped}  Skipped: {skipped}")
    if any(counts_p.values()):
        print(f"Python: " + "  ".join(f"{k}: {v}" for k, v in counts_p.items() if v))
    if any(counts_c.values()):
        print(f"C dot:  " + "  ".join(f"{k}: {v}" for k, v in counts_c.items() if v))
    print(f"Time: {total_time:.1f}s")
