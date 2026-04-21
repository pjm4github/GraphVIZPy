"""Regression test: duplicate cluster names must not trigger infinite recursion.

Found via filters/visual_audit.py: test_data/1902.dot has two nested
subgraphs both literally named ``cluster``.  The dedup logic's
``tree_parent`` map set ``cluster → cluster`` (self-parent), which
made ``_desc_nodes`` recurse forever and raise RecursionError.

Fix in ``cluster.dedup_cluster_nodes`` — skip self-parent edges +
cycle guard inside ``_desc_nodes``.
"""
from gvpy.engines.layout.dot.dot_layout import DotGraphInfo
from gvpy.grammar.gv_reader import read_dot


def test_nested_duplicate_cluster_names_layout_cleanly():
    src = """digraph {
      subgraph cluster {
        subgraph cluster {
          a1 -> a2
        }
        b1
        b2 -> a1
      }
    }"""
    g = read_dot(src)
    layout = DotGraphInfo(g)
    # Must not raise RecursionError.
    result = layout.layout()
    assert len(result["nodes"]) >= 4  # a1, a2, b1, b2
    assert result["edges"]
