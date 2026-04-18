"""Targeted coverage tests for Phase 4 spline routing modules.

These tests exercise code paths in the new Phase A-G modules that
aren't hit by the main test_dot_layout.py suite — primarily
compass-port branches, non-default self-loop directions, flat-edge
corridor variants, curved-mode cycle bending, and pathplan
obstacle-avoidance primitives.
"""
import math
import pytest

from gvpy.engines.layout.dot.pathplan.pathgeom import Ppoint, Ppoly, Ppolyline, Pedge


# ═══════════════════════════════════════════════════════════════
#  self_edge.py — selfLeft / selfTop / selfBottom
# ═══════════════════════════════════════════════════════════════

class TestSelfEdgeVariants:

    @staticmethod
    def _layout(src):
        from gvpy.grammar.gv_reader import read_dot
        from gvpy.engines.layout.dot.dot_layout import DotGraphInfo
        g = read_dot(src)
        layout = DotGraphInfo(g)
        layout.layout()
        return layout

    def _self_edge(self, layout, name):
        for le in layout.ledges:
            if le.tail_name == name and le.head_name == name and not le.virtual:
                return le
        return None

    def test_self_loop_right_default(self):
        layout = self._layout("digraph { a -> a }")
        le = self._self_edge(layout, "a")
        assert le and le.route.points and len(le.route.points) == 7
        xs = [p[0] for p in le.route.points]
        assert max(xs) > layout.lnodes["a"].x + layout.lnodes["a"].width / 2

    def test_self_loop_left_port(self):
        layout = self._layout("digraph { a -> a [tailport=w, headport=w] }")
        le = self._self_edge(layout, "a")
        assert le and le.route.points and len(le.route.points) == 7
        xs = [p[0] for p in le.route.points]
        assert min(xs) < layout.lnodes["a"].x - layout.lnodes["a"].width / 2

    def test_self_loop_top_port(self):
        layout = self._layout("digraph { a -> a [tailport=n, headport=n] }")
        le = self._self_edge(layout, "a")
        assert le and le.route.points and len(le.route.points) == 7
        ys = [p[1] for p in le.route.points]
        assert min(ys) < layout.lnodes["a"].y - layout.lnodes["a"].height / 2

    def test_self_loop_bottom_port(self):
        layout = self._layout("digraph { a -> a [tailport=s, headport=s] }")
        le = self._self_edge(layout, "a")
        assert le and le.route.points and len(le.route.points) == 7
        ys = [p[1] for p in le.route.points]
        assert max(ys) > layout.lnodes["a"].y + layout.lnodes["a"].height / 2

    def test_self_loop_left_right_goes_top(self):
        layout = self._layout("digraph { a -> a [tailport=w, headport=e] }")
        le = self._self_edge(layout, "a")
        assert le and le.route.points and len(le.route.points) == 7

    def test_self_right_space(self):
        from gvpy.engines.layout.dot.self_edge import self_right_space
        from gvpy.engines.layout.dot.dot_layout import LayoutEdge
        le = LayoutEdge(edge=None, tail_name="a", head_name="a")
        assert self_right_space(le) > 0
        le2 = LayoutEdge(edge=None, tail_name="a", head_name="a",
                         tailport="w", headport="w")
        assert self_right_space(le2) == 0


# ═══════════════════════════════════════════════════════════════
#  straight_edge.py — curved mode, cycle bending, multi-edge
# ═══════════════════════════════════════════════════════════════

class TestStraightEdge:

    @staticmethod
    def _layout(src):
        from gvpy.grammar.gv_reader import read_dot
        from gvpy.engines.layout.dot.dot_layout import DotGraphInfo
        g = read_dot(src)
        layout = DotGraphInfo(g)
        layout.layout()
        return layout

    def test_curved_mode_bends(self):
        layout = self._layout('digraph { splines=curved; a -> b -> c -> a }')
        for le in layout.ledges:
            if not le.virtual and le.route.points:
                pts = le.route.points
                assert len(pts) == 4

    def test_bend_function(self):
        from gvpy.engines.layout.dot.straight_edge import bend
        spl = [Ppoint(0, 0), Ppoint(0, 0), Ppoint(100, 0), Ppoint(100, 0)]
        bend(spl, (50, 50))
        assert spl[1].y < 0  # bent away from centroid at y=50
        assert spl[1].x == spl[2].x

    def test_bend_zero_magnitude(self):
        from gvpy.engines.layout.dot.straight_edge import bend
        spl = [Ppoint(0, 0), Ppoint(0, 0), Ppoint(100, 0), Ppoint(100, 0)]
        bend(spl, (50, 0))  # centroid ON the midpoint
        assert spl[1].x == 0  # unchanged

    def test_get_centroid(self):
        from gvpy.engines.layout.dot.straight_edge import get_centroid
        layout = self._layout("digraph { a -> b }")
        cx, cy = get_centroid(layout)
        assert cx > 0 and cy > 0

    def test_cycle_detection(self):
        from gvpy.engines.layout.dot.straight_edge import (
            _find_all_cycles, _cycle_contains_edge,
            _find_shortest_cycle_with_edge, get_cycle_centroid,
        )
        # break_cycles removes back-edges, so test functions directly
        # by injecting a cycle into ledges temporarily.
        layout = self._layout("digraph { a -> b; b -> c }")
        # Manually add c->a to make a cycle visible to _find_all_cycles
        from gvpy.engines.layout.dot.dot_layout import LayoutEdge
        fake = LayoutEdge(edge=None, tail_name="c", head_name="a")
        layout.ledges.append(fake)
        cycles = _find_all_cycles(layout)
        assert len(cycles) >= 1
        layout.ledges.remove(fake)

        assert _cycle_contains_edge(["a", "b", "c"], "a", "b") is True
        assert _cycle_contains_edge(["a", "b", "c"], "x", "y") is False

        found = _find_shortest_cycle_with_edge(cycles, "a", "b")
        assert found is not None

        not_found = _find_shortest_cycle_with_edge([], "x", "y")
        assert not_found is None

        cx, cy = get_cycle_centroid(layout, layout.ledges[0])
        assert cx > 0

    def test_multi_edge_fan_out(self):
        from gvpy.engines.layout.dot.straight_edge import make_straight_edges
        from gvpy.engines.layout.dot.path import EDGETYPE_LINE
        layout = self._layout("digraph { splines=line; a -> b; a -> b }")
        edges = [le for le in layout.ledges
                 if le.tail_name == "a" and le.head_name == "b" and not le.virtual]
        if len(edges) >= 2:
            make_straight_edges(layout, edges, EDGETYPE_LINE)
            assert all(le.route.points for le in edges)


# ═══════════════════════════════════════════════════════════════
#  flat_edge.py — bottom arc, labeled, non-adjacent top arc
# ═══════════════════════════════════════════════════════════════

class TestFlatEdgeCoverage:

    @staticmethod
    def _layout(src):
        from gvpy.grammar.gv_reader import read_dot
        from gvpy.engines.layout.dot.dot_layout import DotGraphInfo
        g = read_dot(src)
        layout = DotGraphInfo(g)
        layout.layout()
        return layout

    def test_non_adjacent_flat_arcs_above(self):
        layout = self._layout("""
            digraph { { rank=same; a; b; c; } a -> c [tailport=n, headport=n] }
        """)
        for le in layout.ledges:
            if le.tail_name == "a" and le.head_name == "c" and not le.virtual:
                pts = le.route.points
                assert pts and len(pts) >= 4
                a_y = layout.lnodes["a"].y
                min_y = min(p[1] for p in pts)
                assert min_y < a_y

    def test_south_port_flat_arcs_below(self):
        layout = self._layout("""
            digraph { { rank=same; a; b; c; } a -> c [tailport=s, headport=s] }
        """)
        for le in layout.ledges:
            if le.tail_name == "a" and le.head_name == "c" and not le.virtual:
                pts = le.route.points
                assert pts and len(pts) >= 4
                a_y = layout.lnodes["a"].y
                max_y = max(p[1] for p in pts)
                assert max_y > a_y

    def test_adjacent_simple_flat(self):
        layout = self._layout("digraph { { rank=same; a; b; } a -> b }")
        for le in layout.ledges:
            if le.tail_name == "a" and le.head_name == "b" and not le.virtual:
                assert le.route.points and len(le.route.points) == 4

    def test_compass_to_side(self):
        from gvpy.engines.layout.dot.flat_edge import _compass_to_side
        from gvpy.engines.layout.dot.path import TOP, BOTTOM
        assert _compass_to_side("n") == TOP
        assert _compass_to_side("s") == BOTTOM
        assert _compass_to_side("sw") == BOTTOM
        assert _compass_to_side("ne") == TOP
        assert _compass_to_side("e") == 0
        assert _compass_to_side("") == 0


# ═══════════════════════════════════════════════════════════════
#  path.py — beginpath/endpath compass-port branches
# ═══════════════════════════════════════════════════════════════

class TestPathEndpoints:

    def test_beginpath_top_port(self):
        from gvpy.engines.layout.dot.path import (
            Path, PathEnd, Box, REGULAREDGE, TOP, beginpath,
        )
        P = Path()
        endp = PathEnd(nb=Box(20, 0, 80, 50))
        clip = beginpath(P, REGULAREDGE, endp, merge=False,
                         node_x=50, node_y=25,
                         node_lw=30, node_rw=30, node_ht2=25,
                         port_p=(10, -25), port_side=TOP,
                         is_normal=True, ranksep=40)
        assert clip is True
        assert endp.boxn == 2
        assert endp.sidemask == TOP

    def test_beginpath_left_port(self):
        from gvpy.engines.layout.dot.path import (
            Path, PathEnd, Box, REGULAREDGE, LEFT, beginpath,
        )
        P = Path()
        endp = PathEnd(nb=Box(20, 0, 80, 50))
        clip = beginpath(P, REGULAREDGE, endp, merge=False,
                         node_x=50, node_y=25,
                         node_lw=30, node_rw=30, node_ht2=25,
                         port_p=(-30, 0), port_side=LEFT,
                         is_normal=True, ranksep=40)
        assert clip is True
        assert endp.sidemask == LEFT

    def test_beginpath_right_port(self):
        from gvpy.engines.layout.dot.path import (
            Path, PathEnd, Box, REGULAREDGE, RIGHT, beginpath,
        )
        P = Path()
        endp = PathEnd(nb=Box(20, 0, 80, 50))
        clip = beginpath(P, REGULAREDGE, endp, merge=False,
                         node_x=50, node_y=25,
                         node_lw=30, node_rw=30, node_ht2=25,
                         port_p=(30, 0), port_side=RIGHT,
                         is_normal=True, ranksep=40)
        assert clip is True
        assert endp.sidemask == RIGHT

    def test_beginpath_bottom_port(self):
        from gvpy.engines.layout.dot.path import (
            Path, PathEnd, Box, REGULAREDGE, BOTTOM, beginpath,
        )
        P = Path()
        endp = PathEnd(nb=Box(20, 0, 80, 50))
        clip = beginpath(P, REGULAREDGE, endp, merge=False,
                         node_x=50, node_y=25,
                         node_lw=30, node_rw=30, node_ht2=25,
                         port_p=(0, 25), port_side=BOTTOM,
                         is_normal=True, ranksep=40)
        assert clip is True
        assert endp.sidemask == BOTTOM

    def test_endpath_top_port(self):
        from gvpy.engines.layout.dot.path import (
            Path, PathEnd, Box, REGULAREDGE, TOP, endpath,
        )
        P = Path()
        endp = PathEnd(nb=Box(20, 50, 80, 100))
        clip = endpath(P, REGULAREDGE, endp, merge=False,
                       node_x=50, node_y=75,
                       node_lw=30, node_rw=30, node_ht2=25,
                       port_p=(0, -25), port_side=TOP,
                       is_normal=True, ranksep=40)
        assert clip is True
        assert endp.sidemask == TOP

    def test_endpath_bottom_port(self):
        from gvpy.engines.layout.dot.path import (
            Path, PathEnd, Box, REGULAREDGE, BOTTOM, endpath,
        )
        P = Path()
        endp = PathEnd(nb=Box(20, 50, 80, 100))
        clip = endpath(P, REGULAREDGE, endp, merge=False,
                       node_x=50, node_y=75,
                       node_lw=30, node_rw=30, node_ht2=25,
                       port_p=(-10, 25), port_side=BOTTOM,
                       is_normal=True, ranksep=40)
        assert clip is True
        assert endp.sidemask == BOTTOM

    def test_endpath_left_port(self):
        from gvpy.engines.layout.dot.path import (
            Path, PathEnd, Box, REGULAREDGE, LEFT, endpath,
        )
        P = Path()
        endp = PathEnd(nb=Box(20, 50, 80, 100))
        clip = endpath(P, REGULAREDGE, endp, merge=False,
                       node_x=50, node_y=75,
                       node_lw=30, node_rw=30, node_ht2=25,
                       port_p=(-30, 0), port_side=LEFT,
                       is_normal=True, ranksep=40)
        assert clip is True
        assert endp.sidemask == LEFT

    def test_endpath_right_port(self):
        from gvpy.engines.layout.dot.path import (
            Path, PathEnd, Box, REGULAREDGE, RIGHT, endpath,
        )
        P = Path()
        endp = PathEnd(nb=Box(20, 50, 80, 100))
        clip = endpath(P, REGULAREDGE, endp, merge=False,
                       node_x=50, node_y=75,
                       node_lw=30, node_rw=30, node_ht2=25,
                       port_p=(30, 0), port_side=RIGHT,
                       is_normal=True, ranksep=40)
        assert clip is True
        assert endp.sidemask == RIGHT

    def test_beginpath_flatedge_top(self):
        from gvpy.engines.layout.dot.path import (
            Path, PathEnd, Box, FLATEDGE, TOP, beginpath,
        )
        P = Path()
        endp = PathEnd(nb=Box(20, 0, 80, 50), sidemask=TOP)
        clip = beginpath(P, FLATEDGE, endp, merge=False,
                         node_x=50, node_y=25,
                         node_lw=30, node_rw=30, node_ht2=25,
                         port_p=(0, -25), port_side=TOP)
        assert clip is True

    def test_beginpath_flatedge_bottom(self):
        from gvpy.engines.layout.dot.path import (
            Path, PathEnd, Box, FLATEDGE, BOTTOM, TOP, beginpath,
        )
        P = Path()
        endp = PathEnd(nb=Box(20, 0, 80, 50), sidemask=TOP)
        clip = beginpath(P, FLATEDGE, endp, merge=False,
                         node_x=50, node_y=25,
                         node_lw=30, node_rw=30, node_ht2=25,
                         port_p=(0, 25), port_side=BOTTOM)
        assert clip is True
        assert endp.boxn >= 1

    def test_beginpath_flatedge_left(self):
        from gvpy.engines.layout.dot.path import (
            Path, PathEnd, Box, FLATEDGE, LEFT, TOP, beginpath,
        )
        P = Path()
        endp = PathEnd(nb=Box(20, 0, 80, 50), sidemask=TOP)
        clip = beginpath(P, FLATEDGE, endp, merge=False,
                         node_x=50, node_y=25,
                         node_lw=30, node_rw=30, node_ht2=25,
                         port_p=(-30, 0), port_side=LEFT)
        assert clip is True

    def test_beginpath_flatedge_right(self):
        from gvpy.engines.layout.dot.path import (
            Path, PathEnd, Box, FLATEDGE, RIGHT, TOP, beginpath,
        )
        P = Path()
        endp = PathEnd(nb=Box(20, 0, 80, 50), sidemask=TOP)
        clip = beginpath(P, FLATEDGE, endp, merge=False,
                         node_x=50, node_y=25,
                         node_lw=30, node_rw=30, node_ht2=25,
                         port_p=(30, 0), port_side=RIGHT)
        assert clip is True

    def test_beginpath_merge(self):
        from gvpy.engines.layout.dot.path import (
            Path, PathEnd, Box, REGULAREDGE, beginpath,
        )
        P = Path()
        endp = PathEnd(nb=Box(20, 0, 80, 50))
        beginpath(P, REGULAREDGE, endp, merge=True,
                  node_x=50, node_y=25,
                  node_lw=30, node_rw=30, node_ht2=25)
        assert P.start.constrained is True
        assert P.start.theta == pytest.approx(-math.pi / 2, abs=0.01)

    def test_endpath_merge(self):
        from gvpy.engines.layout.dot.path import (
            Path, PathEnd, Box, REGULAREDGE, endpath,
        )
        P = Path()
        endp = PathEnd(nb=Box(20, 50, 80, 100))
        endpath(P, REGULAREDGE, endp, merge=True,
                node_x=50, node_y=75,
                node_lw=30, node_rw=30, node_ht2=25)
        assert P.end.constrained is True


# ═══════════════════════════════════════════════════════════════
#  clip.py — box_inside, ellipse edge cases
# ═══════════════════════════════════════════════════════════════

class TestClipCoverage:

    def test_box_inside(self):
        from gvpy.engines.layout.dot.clip import box_inside
        fn = box_inside(50, 30)
        assert fn(Ppoint(0, 0)) is True
        assert fn(Ppoint(50, 30)) is True
        assert fn(Ppoint(51, 0)) is False
        assert fn(Ppoint(0, 31)) is False

    def test_ellipse_degenerate(self):
        from gvpy.engines.layout.dot.clip import ellipse_inside
        fn = ellipse_inside(0, 30)
        assert fn(Ppoint(0, 0)) is False

    def test_make_inside_fn_box_shapes(self):
        from gvpy.engines.layout.dot.clip import make_inside_fn
        for shape in ("box", "rect", "rectangle", "record", "Mrecord", "plain"):
            fn = make_inside_fn(shape, 50, 30)
            assert fn(Ppoint(0, 0)) is True
            assert fn(Ppoint(51, 0)) is False

    def test_conc_slope(self):
        from gvpy.engines.layout.dot.clip import conc_slope
        s = conc_slope(100, 200, [80, 120], [300, 300], [80, 120], [100, 100])
        assert -math.pi < s < math.pi
        s_empty = conc_slope(100, 200, [], [], [], [])
        assert s_empty == pytest.approx(-math.pi / 2)

    def test_clip_and_install_no_clip(self):
        from gvpy.engines.layout.dot.clip import clip_and_install
        ps = [Ppoint(0, 0), Ppoint(33, 0), Ppoint(66, 0), Ppoint(100, 0)]
        result = clip_and_install(
            ps, tail_x=0, tail_y=0, tail_hw=10, tail_hh=10,
            tail_clip=False,
            head_x=100, head_y=0, head_hw=10, head_hh=10,
            head_clip=False)
        assert abs(result[0].x) < 0.01
        assert abs(result[-1].x - 100) < 0.01

    def test_clip_short_spline(self):
        from gvpy.engines.layout.dot.clip import clip_and_install
        ps = [Ppoint(0, 0), Ppoint(1, 0)]
        result = clip_and_install(
            ps, tail_x=0, tail_y=0, tail_hw=10, tail_hh=10,
            head_x=100, head_y=0, head_hw=10, head_hh=10)
        assert len(result) == 2


# ═══════════════════════════════════════════════════════════════
#  routespl.py — simple_spline_route, checkpath edge cases
# ═══════════════════════════════════════════════════════════════

class TestRoutesplCoverage:

    def test_simple_spline_route(self):
        from gvpy.engines.layout.dot.routespl import simple_spline_route
        poly = Ppoly(ps=[
            Ppoint(0, 0), Ppoint(100, 0),
            Ppoint(100, 100), Ppoint(0, 100),
        ])
        result = simple_spline_route((50, 5), (50, 95), poly)
        assert result is not None and len(result) >= 4

    def test_simple_spline_route_polyline(self):
        from gvpy.engines.layout.dot.routespl import simple_spline_route
        poly = Ppoly(ps=[
            Ppoint(0, 0), Ppoint(100, 0),
            Ppoint(100, 100), Ppoint(0, 100),
        ])
        result = simple_spline_route((50, 5), (50, 95), poly, polyline=True)
        assert result is not None

    def test_checkpath_empty(self):
        from gvpy.engines.layout.dot.routespl import checkpath
        from gvpy.engines.layout.dot.path import Path, PathEnd, Box
        pp = Path(start=PathEnd(np=(50, 25)), end=PathEnd(np=(50, 75)))
        status, boxes = checkpath([], pp)
        assert status == 1

    def test_checkpath_inverted_box(self):
        from gvpy.engines.layout.dot.routespl import checkpath
        from gvpy.engines.layout.dot.path import Path, PathEnd, Box
        pp = Path(start=PathEnd(np=(50, 25)), end=PathEnd(np=(50, 75)))
        status, boxes = checkpath([Box(80, 0, 20, 50)], pp)  # LL.x > UR.x
        assert status == 1

    def test_routepolylines(self):
        from gvpy.engines.layout.dot.routespl import routepolylines
        from gvpy.engines.layout.dot.path import Path, PathEnd, Box
        boxes = [Box(0, 0, 100, 50), Box(0, 50, 100, 100)]
        pp = Path(boxes=list(boxes), nbox=2,
                  start=PathEnd(np=(50, 10)),
                  end=PathEnd(np=(50, 90)))
        result = routepolylines(pp)
        assert result is not None


# ═══════════════════════════════════════════════════════════════
#  pathplan — visibility, cvt, shortestpth, inpoly, util
# ═══════════════════════════════════════════════════════════════

class TestPathplanCoverage:

    def test_ppolybarriers(self):
        from gvpy.engines.layout.dot.pathplan.util import Ppolybarriers
        poly = Ppoly(ps=[
            Ppoint(0, 0), Ppoint(100, 0),
            Ppoint(100, 100), Ppoint(0, 100),
        ])
        bars = Ppolybarriers([poly])
        assert len(bars) == 4
        assert all(isinstance(b, Pedge) for b in bars)

    def test_in_poly(self):
        from gvpy.engines.layout.dot.pathplan.inpoly import in_poly
        # CW vertex order for screen coords (y-down)
        poly = Ppoly(ps=[Ppoint(0, 0), Ppoint(0, 100),
                         Ppoint(100, 100), Ppoint(100, 0)])
        assert in_poly(poly, Ppoint(50, 50)) is True
        assert in_poly(poly, Ppoint(200, 200)) is False

    def test_visibility_basic(self):
        from gvpy.engines.layout.dot.pathplan.visibility import (
            visibility, area2, wind,
        )
        assert area2(Ppoint(0, 0), Ppoint(1, 0), Ppoint(0, 1)) != 0
        w = wind(Ppoint(0, 0), Ppoint(1, 0), Ppoint(0, 1))
        assert w in (1, 2)  # ISCW or ISCCW

    def test_pobsopen_pobspath(self):
        from gvpy.engines.layout.dot.pathplan.cvt import Pobsopen, Pobspath
        from gvpy.engines.layout.dot.pathplan.vispath import POLYID_NONE
        # CW polygon (pathplan convention) as obstacle in the middle
        polys = [
            Ppoly(ps=[Ppoint(40, 40), Ppoint(40, 60),
                       Ppoint(60, 60), Ppoint(60, 40)]),
        ]
        config = Pobsopen(polys)
        assert config is not None
        p0 = Ppoint(10, 50)
        p1 = Ppoint(90, 50)
        path = Pobspath(config, p0, POLYID_NONE, p1, POLYID_NONE)
        assert path.pn >= 2

    def test_shortestpth_dijkstra(self):
        from gvpy.engines.layout.dot.pathplan.shortestpth import shortestPath
        # 4-node graph: 0-1 (w=1), 1-2 (w=1), 0-2 (w=5), 2-3 (w=1)
        adj = [[0, 1, 5, 0],
               [1, 0, 1, 0],
               [5, 1, 0, 1],
               [0, 0, 1, 0]]
        dad = shortestPath(0, 2, 4, adj)
        # Shortest path 0->1->2: dad[2]==1, dad[1]==0
        assert dad[2] == 1
        assert dad[1] == 0

    def test_triang_basic(self):
        from gvpy.engines.layout.dot.pathplan.triang import Ptriangulate
        # Ptriangulate expects CCW vertices.  In screen coords (y-down),
        # CCW is: (0,0) → (0,100) → (100,100) → (100,0).
        poly = Ppoly(ps=[
            Ppoint(0, 0), Ppoint(0, 100),
            Ppoint(100, 100), Ppoint(100, 0),
        ])
        tris = []
        def callback(vc, tri):
            tris.append(tri)
        Ptriangulate(poly, callback)
        assert len(tris) == 2
