"""Back-compat re-export of the spline clipping pipeline.

The canonical implementation now lives in :mod:`common.clip` and
:mod:`common.splines` (``bezier_point`` — the de Casteljau
evaluator).  This module keeps every previously-imported symbol
available so existing call sites continue to resolve.

Phase C of the splines port.

See: /lib/common/splines.c @ 65
"""
from gvpy.engines.layout.common.clip import (  # noqa: F401
    MILLIPOINT,
    _approx_eq,
    bezier_clip,
    clip_and_install,
    conc_slope,
    shape_clip,
    shape_clip0,
)
from gvpy.engines.layout.common.shapes import (  # noqa: F401
    InsideFn,
    box_inside,
    ellipse_inside,
    make_inside_fn,
)
from gvpy.engines.layout.common.splines import bezier_point  # noqa: F401
