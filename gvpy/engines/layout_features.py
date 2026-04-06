"""
Layout feature table — defines which attributes each engine supports.

Auto-generated from the complete Graphviz attribute reference table.
Used by the wizard to enable/disable controls per engine, and by the
CLI to validate attribute flags.

Each entry: ``(scope, attr_name, type, default, engines, description)``
where ``engines`` is a set of engine names that support the attribute.
"""
from __future__ import annotations

# ── Complete attribute table ─────────────────────
#
# Each tuple: (scope, name, type, default, {engines}, description)
# scope: "graph", "node", "edge", "subgraph"
# engines: subset of {"dot","neato","fdp","sfdp","circo","twopi","osage","patchwork"}

_ALL = {"dot", "neato", "fdp", "sfdp", "circo", "twopi", "osage", "patchwork"}

_ATTR_TABLE: list[tuple[str, str, str, str, set[str], str]] = [
    # ── Graph attributes ─────────────────────────
    ("graph", "_background",    "xdot",       "",           _ALL, "xdot background drawn behind the graph"),
    ("graph", "bb",             "rect",       "",           _ALL, "Bounding box of drawing in points (write-only)"),
    ("graph", "beautify",       "bool",       "false",      {"sfdp"}, "Draw leaf nodes uniformly in circle around root"),
    ("graph", "bgcolor",        "color",      "",           _ALL, "Canvas background color"),
    ("graph", "center",         "bool",       "false",      _ALL, "Center drawing in output canvas"),
    ("graph", "charset",        "string",     "UTF-8",      _ALL, "Character encoding for string input"),
    ("graph", "class",          "string",     "",           _ALL, "CSS classnames for SVG element"),
    ("graph", "clusterrank",    "clusterMode","local",      {"dot"}, "Cluster handling: local / global / none"),
    ("graph", "colorscheme",    "string",     "",           _ALL, "Color scheme namespace for interpreting color names"),
    ("graph", "comment",        "string",     "",           _ALL, "Comment inserted into output"),
    ("graph", "compound",       "bool",       "false",      {"dot"}, "Allow edges between clusters (requires lhead/ltail)"),
    ("graph", "concentrate",    "bool",       "false",      _ALL, "Merge parallel edges"),
    ("graph", "Damping",        "double",     "0.99",       {"neato"}, "Damping factor on force motions each iteration"),
    ("graph", "defaultdist",    "double",     "1+avg*sqrt(|V|)", {"neato"}, "Distance between disconnected components"),
    ("graph", "dim",            "int",        "2",          {"neato","fdp","sfdp"}, "Dimensions used for layout computation"),
    ("graph", "dimen",          "int",        "2",          {"neato","fdp","sfdp"}, "Dimensions used for rendering"),
    ("graph", "diredgeconstraints","bool",     "false",      {"neato"}, "Constrain most edges to point downwards"),
    ("graph", "dpi",            "double",     "96",         _ALL, "Pixels per inch for bitmap/SVG output"),
    ("graph", "epsilon",        "double",     "0.0001*|V|", {"neato"}, "Convergence threshold for energy minimization"),
    ("graph", "esep",           "addDouble",  "3",          {"neato","fdp","sfdp","circo","twopi","osage"}, "Margin around polygons for spline edge routing"),
    ("graph", "fontcolor",      "color",      "black",      _ALL, "Default text color"),
    ("graph", "fontname",       "string",     "Times-Roman",_ALL, "Default font face"),
    ("graph", "fontnames",      "string",     "",           _ALL, "Font name representation in SVG output"),
    ("graph", "fontpath",       "string",     "",           _ALL, "Directories to search for bitmap fonts"),
    ("graph", "fontsize",       "double",     "14",         _ALL, "Default font size in points"),
    ("graph", "forcelabels",    "bool",       "true",       _ALL, "Force placement of all xlabels even if overlapping"),
    ("graph", "gradientangle",  "int",        "0",          _ALL, "Gradient fill angle in degrees"),
    ("graph", "href",           "escString",  "",           _ALL, "URL synonym (SVG/map/PS)"),
    ("graph", "id",             "escString",  "",           _ALL, "Identifier for SVG/map output"),
    ("graph", "imagepath",      "string",     "",           _ALL, "Directories to search for image files"),
    ("graph", "inputscale",     "double",     "",           {"neato","fdp"}, "Scale applied to input pos values"),
    ("graph", "K",              "double",     "0.3",        {"fdp","sfdp"}, "Spring constant / ideal edge length proxy"),
    ("graph", "label",          "lblString",  "",           _ALL, "Graph label text"),
    ("graph", "label_scheme",   "int",        "0",          {"sfdp"}, "Treat |edgelabel|* nodes as edge labels"),
    ("graph", "labeljust",      "string",     "c",          _ALL, "Justification of graph & cluster labels"),
    ("graph", "labelloc",       "string",     "b",          _ALL, "Vertical placement of graph/cluster label"),
    ("graph", "landscape",      "bool",       "false",      _ALL, "Render in landscape orientation"),
    ("graph", "layerlistsep",   "string",     ",",          _ALL, "Separator chars for layerRange splitting"),
    ("graph", "layers",         "layerList",  "",           _ALL, "Ordered list of layer names"),
    ("graph", "layerselect",    "layerRange", "",           _ALL, "Layers to emit"),
    ("graph", "layersep",       "string",     ":\t ",       _ALL, "Separator chars for layers attribute"),
    ("graph", "layout",         "string",     "",           _ALL, "Which layout engine to use"),
    ("graph", "levels",         "int",        "INT_MAX",    {"sfdp"}, "Number of levels in multilevel coarsening"),
    ("graph", "levelsgap",      "double",     "0",          {"neato"}, "Strictness of neato level constraints"),
    ("graph", "lheight",        "double",     "",           _ALL, "Height of graph/cluster label in inches (write-only)"),
    ("graph", "linelength",     "int",        "128",        _ALL, "Max chars before line overflow in text output"),
    ("graph", "lp",             "point",      "",           _ALL, "Label center position (write-only)"),
    ("graph", "lwidth",         "double",     "",           _ALL, "Width of graph/cluster label in inches (write-only)"),
    ("graph", "margin",         "double",     "",           _ALL, "X and Y canvas margins in inches"),
    ("graph", "maxiter",        "int",        "",           {"neato","fdp"}, "Maximum layout solver iterations"),
    ("graph", "mclimit",        "double",     "1",          {"dot"}, "Scale factor for mincross edge crossing iterations"),
    ("graph", "mindist",        "double",     "1",          {"circo"}, "Minimum separation between all nodes"),
    ("graph", "mode",           "string",     "major",      {"neato"}, "Optimization algorithm: KK / major / sgd / hier"),
    ("graph", "model",          "string",     "shortpath",  {"neato"}, "Distance matrix computation method"),
    ("graph", "newrank",        "bool",       "false",      {"dot"}, "Use single global ranking ignoring clusters"),
    ("graph", "nodesep",        "double",     "0.25",       {"dot"}, "Min horizontal space between nodes in same rank"),
    ("graph", "nojustify",      "bool",       "false",      _ALL, "Multiline text justification mode"),
    ("graph", "normalize",      "bool",       "false",      {"neato","fdp","sfdp","circo","twopi"}, "Normalize coordinates of final layout"),
    ("graph", "notranslate",    "bool",       "false",      {"neato"}, "Suppress automatic translation to origin"),
    ("graph", "nslimit",        "double",     "",           {"dot"}, "Max network simplex iterations for ranking phase"),
    ("graph", "nslimit1",       "double",     "",           {"dot"}, "Max network simplex iterations for position phase"),
    ("graph", "oneblock",       "bool",       "false",      {"circo"}, "Draw all components on one circle"),
    ("graph", "ordering",       "string",     "",           {"dot"}, "Constrain left-to-right edge ordering"),
    ("graph", "orientation",    "string",     "",           _ALL, "Graph orientation angle or landscape string"),
    ("graph", "outputorder",    "outputMode", "breadthfirst", _ALL, "Draw order: breadthfirst / nodesfirst / edgesfirst"),
    ("graph", "overlap",        "bool/string","true",       {"neato","fdp","sfdp","circo","twopi"}, "Node overlap removal strategy"),
    ("graph", "overlap_scaling","double",     "-4",         {"neato","fdp","sfdp","circo","twopi"}, "Scale factor for overlap reduction"),
    ("graph", "overlap_shrink", "bool",       "true",       {"neato","fdp","sfdp","circo","twopi"}, "Compression pass after overlap removal"),
    ("graph", "pack",           "bool/int",   "false",      _ALL, "Pack disconnected components separately"),
    ("graph", "packmode",       "packMode",   "node",       _ALL, "How to pack components: node/clust/graph/array"),
    ("graph", "pad",            "double",     "0.0555",     _ALL, "Extend drawing area beyond minimum (inches)"),
    ("graph", "page",           "double",     "",           _ALL, "Output page width and height in inches"),
    ("graph", "pagedir",        "pagedir",    "BL",         _ALL, "Order in which pages are emitted"),
    ("graph", "quadtree",       "quadType",   "normal",     {"sfdp"}, "Barnes-Hut quadtree approximation mode"),
    ("graph", "quantum",        "double",     "0",          _ALL, "Round node label dims to multiples of quantum"),
    ("graph", "rankdir",        "rankdir",    "TB",         {"dot"}, "Layout direction: TB / LR / BT / RL"),
    ("graph", "ranksep",        "double",     "0.5",        {"dot","twopi"}, "Separation between ranks / radial circles"),
    ("graph", "ratio",          "string",     "",           _ALL, "Aspect ratio of the drawing"),
    ("graph", "remincross",     "bool",       "true",       {"dot"}, "Run crossing minimization a second time"),
    ("graph", "repulsiveforce", "double",     "1",          {"sfdp"}, "Strength of repulsive force in FR model"),
    ("graph", "resolution",     "double",     "96",         _ALL, "Synonym for dpi — pixels per inch for output"),
    ("graph", "root",           "string",     "",           {"circo","twopi"}, "Center node for radial/circular layout"),
    ("graph", "rotate",         "int",        "0",          _ALL, "Rotate 90 deg for landscape (use landscape instead)"),
    ("graph", "rotation",       "double",     "0",          {"sfdp"}, "Counter-clockwise rotation of final layout (degrees)"),
    ("graph", "scale",          "double",     "",           {"neato","twopi"}, "Scale layout after initial placement"),
    ("graph", "searchsize",     "int",        "30",         {"dot"}, "Max negative-cut edges checked in network simplex"),
    ("graph", "sep",            "addDouble",  "4",          {"neato","fdp","sfdp","circo","twopi","osage"}, "Node margin for overlap removal routing"),
    ("graph", "showboxes",      "int",        "0",          {"dot"}, "Print debug guide boxes (non-zero enables)"),
    ("graph", "size",           "double",     "",           _ALL, "Maximum drawing width and height in inches"),
    ("graph", "smoothing",      "smoothType", "none",       {"sfdp"}, "Post-processing smoothing pass type"),
    ("graph", "sortv",          "int",        "0",          _ALL, "Sort order for packmode packing"),
    ("graph", "splines",        "string",     "",           _ALL, "Edge routing: none/line/polyline/curved/ortho/spline"),
    ("graph", "start",          "startType",  "",           {"neato","fdp","sfdp"}, "Initial node placement seed or method"),
    ("graph", "style",          "style",      "",           _ALL, "Style for graph/cluster border"),
    ("graph", "stylesheet",     "string",     "",           _ALL, "URL of XML stylesheet for SVG output"),
    ("graph", "target",         "escString",  "",           _ALL, "Browser window for URL links (SVG/map)"),
    ("graph", "TBbalance",      "string",     "min",        {"dot"}, "Rank placement for floating nodes: min/max/none"),
    ("graph", "tooltip",        "escString",  "",           _ALL, "Mouse hover tooltip (SVG/cmap)"),
    ("graph", "truecolor",      "bool",       "",           _ALL, "Use truecolor bitmap rendering"),
    ("graph", "URL",            "escString",  "",           _ALL, "Hyperlink for the graph (SVG/map/PS)"),
    ("graph", "viewport",       "viewPort",   "",           _ALL, "Clipping window on final drawing"),
    ("graph", "voro_margin",    "double",     "0.05",       {"neato","fdp","sfdp","circo","twopi"}, "Voronoi margin tuning"),
    ("graph", "xdotversion",    "string",     "",           _ALL, "xdot output format version"),

    # ── Node attributes ──────────────────────────
    ("node", "area",            "double",     "1",          {"patchwork"}, "Preferred area for node in squarified treemap"),
    ("node", "class",           "string",     "",           _ALL, "CSS classnames for SVG element"),
    ("node", "color",           "color",      "black",      _ALL, "Node border/outline color"),
    ("node", "colorscheme",     "string",     "",           _ALL, "Color scheme namespace for color names"),
    ("node", "comment",         "string",     "",           _ALL, "Comment inserted into output"),
    ("node", "distortion",      "double",     "0",          _ALL, "Distortion factor for shape=polygon"),
    ("node", "fillcolor",       "color",      "lightgrey",  _ALL, "Node fill color"),
    ("node", "fixedsize",       "bool/string","false",      _ALL, "Use width/height exactly rather than fitting label"),
    ("node", "fontcolor",       "color",      "black",      _ALL, "Node label text color"),
    ("node", "fontname",        "string",     "Times-Roman",_ALL, "Node label font face"),
    ("node", "fontsize",        "double",     "14",         _ALL, "Node label font size in points"),
    ("node", "gradientangle",   "int",        "0",          _ALL, "Gradient fill angle for node"),
    ("node", "group",           "string",     "",           {"dot"}, "Group name for keeping nodes near each other"),
    ("node", "height",          "double",     "0.5",        _ALL, "Node height in inches"),
    ("node", "href",            "escString",  "",           _ALL, "URL synonym (SVG/map/PS)"),
    ("node", "id",              "escString",  "",           _ALL, "SVG/map identifier"),
    ("node", "image",           "string",     "",           _ALL, "Image file to display inside node"),
    ("node", "imagepos",        "string",     "mc",         _ALL, "Image position within node"),
    ("node", "imagescale",      "bool/string","false",      _ALL, "How image fills the node"),
    ("node", "K",               "double",     "0.3",        {"fdp","sfdp"}, "Per-node spring constant override"),
    ("node", "label",           "lblString",  "\\N",        _ALL, "Node label text"),
    ("node", "labelloc",        "string",     "c",          _ALL, "Vertical label placement within node"),
    ("node", "layer",           "layerRange", "",           _ALL, "Layer membership"),
    ("node", "margin",          "double",     "",           _ALL, "Margin between label and node boundary"),
    ("node", "nojustify",       "bool",       "false",      _ALL, "Multiline label justification mode"),
    ("node", "ordering",        "string",     "",           {"dot"}, "Per-node left-to-right edge ordering constraint"),
    ("node", "orientation",     "double",     "0",          _ALL, "Node shape rotation angle in degrees"),
    ("node", "penwidth",        "double",     "1",          _ALL, "Width of node border pen in points"),
    ("node", "peripheries",     "int",        "",           _ALL, "Number of border rings around node"),
    ("node", "pin",             "bool",       "false",      {"neato","fdp"}, "Lock node at its input pos coordinate"),
    ("node", "pos",             "point",      "",           {"neato","fdp"}, "Input/output node position coordinate"),
    ("node", "rects",           "rect",       "",           _ALL, "Record field rectangles (write-only)"),
    ("node", "regular",         "bool",       "false",      _ALL, "Force polygon to be regular (equal sides/angles)"),
    ("node", "root",            "bool",       "false",      {"circo","twopi"}, "Mark this node as the layout root"),
    ("node", "samplepoints",    "int",        "",           _ALL, "Points used to approximate circle/ellipse"),
    ("node", "shape",           "shape",      "ellipse",    _ALL, "Node shape"),
    ("node", "shapefile",       "string",     "",           _ALL, "External file for custom node shape content"),
    ("node", "showboxes",       "int",        "0",          {"dot"}, "Debug guide boxes for node (non-zero)"),
    ("node", "sides",           "int",        "4",          _ALL, "Side count for shape=polygon"),
    ("node", "skew",            "double",     "0",          _ALL, "Skew factor for shape=polygon"),
    ("node", "sortv",           "int",        "0",          _ALL, "Sort value for pack ordering"),
    ("node", "style",           "style",      "",           _ALL, "Node style: filled/dashed/dotted/rounded etc."),
    ("node", "target",          "escString",  "",           _ALL, "Browser window for URL (SVG/map)"),
    ("node", "tooltip",         "escString",  "",           _ALL, "Mouse hover tooltip (SVG/cmap)"),
    ("node", "URL",             "escString",  "",           _ALL, "Hyperlink for node (SVG/map/PS)"),
    ("node", "vertices",        "pointList",  "",           _ALL, "Custom polygon vertex list (write-only)"),
    ("node", "width",           "double",     "0.75",       _ALL, "Node width in inches"),
    ("node", "xlabel",          "lblString",  "",           _ALL, "External label placed outside node boundary"),
    ("node", "xlp",             "point",      "",           _ALL, "External label position (write-only)"),
    ("node", "z",               "double",     "0",          {"neato","fdp"}, "Z-coordinate for 3D/VRML output"),

    # ── Edge attributes ──────────────────────────
    ("edge", "arrowhead",       "arrowType",  "normal",     _ALL, "Arrowhead shape at head node"),
    ("edge", "arrowsize",       "double",     "1",          _ALL, "Arrowhead scale multiplier"),
    ("edge", "arrowtail",       "arrowType",  "normal",     _ALL, "Arrowhead shape at tail node"),
    ("edge", "class",           "string",     "",           _ALL, "CSS classnames for SVG element"),
    ("edge", "color",           "color",      "black",      _ALL, "Edge line color"),
    ("edge", "colorscheme",     "string",     "",           _ALL, "Color scheme namespace"),
    ("edge", "comment",         "string",     "",           _ALL, "Comment inserted into output"),
    ("edge", "constraint",      "bool",       "true",       {"dot"}, "Whether edge participates in rank assignment"),
    ("edge", "decorate",        "bool",       "false",      _ALL, "Draw line connecting edge label to edge"),
    ("edge", "dir",             "dirType",    "forward",    _ALL, "Arrow direction: forward/back/both/none"),
    ("edge", "edgehref",        "escString",  "",           _ALL, "Synonym for edgeURL (SVG/map)"),
    ("edge", "edgetarget",      "escString",  "",           _ALL, "Browser window for edgeURL (SVG/map)"),
    ("edge", "edgetooltip",     "escString",  "",           _ALL, "Tooltip on non-label part of edge (SVG/cmap)"),
    ("edge", "edgeURL",         "escString",  "",           _ALL, "URL for non-label part of edge (SVG/map)"),
    ("edge", "fillcolor",       "color",      "black",      _ALL, "Fill color for edge arrowheads"),
    ("edge", "fontcolor",       "color",      "black",      _ALL, "Edge label text color"),
    ("edge", "fontname",        "string",     "Times-Roman",_ALL, "Edge label font face"),
    ("edge", "fontsize",        "double",     "14",         _ALL, "Edge label font size in points"),
    ("edge", "head_lp",         "point",      "",           _ALL, "Head label center position (write-only)"),
    ("edge", "headclip",        "bool",       "true",       _ALL, "Clip edge to head node boundary"),
    ("edge", "headhref",        "escString",  "",           _ALL, "URL for head of edge (SVG/map)"),
    ("edge", "headlabel",       "lblString",  "",           _ALL, "Label at head end of edge"),
    ("edge", "headport",        "portPos",    "center",     _ALL, "Compass port on head node"),
    ("edge", "headtarget",      "escString",  "",           _ALL, "Browser window for headURL (SVG/map)"),
    ("edge", "headtooltip",     "escString",  "",           _ALL, "Tooltip on head label (SVG/cmap)"),
    ("edge", "headURL",         "escString",  "",           _ALL, "URL for head label (SVG/map)"),
    ("edge", "href",            "escString",  "",           _ALL, "URL synonym (SVG/map/PS)"),
    ("edge", "id",              "escString",  "",           _ALL, "SVG/map identifier"),
    ("edge", "label",           "lblString",  "",           _ALL, "Edge label text"),
    ("edge", "labelangle",      "double",     "-25",        _ALL, "Polar angle for head/tail label positioning"),
    ("edge", "labeldistance",   "double",     "1",          _ALL, "Scale factor for head/tail label distance from node"),
    ("edge", "labelfloat",      "bool",       "false",      _ALL, "Allow label to float to reduce edge crossings"),
    ("edge", "labelfontcolor",  "color",      "black",      _ALL, "Head/tail label text color"),
    ("edge", "labelfontname",   "string",     "Times-Roman",_ALL, "Head/tail label font face"),
    ("edge", "labelfontsize",   "double",     "14",         _ALL, "Head/tail label font size in points"),
    ("edge", "labelhref",       "escString",  "",           _ALL, "URL for label (SVG/map)"),
    ("edge", "labeltarget",     "escString",  "",           _ALL, "Browser window for labelURL (SVG/map)"),
    ("edge", "labeltooltip",    "escString",  "",           _ALL, "Tooltip on label (SVG/cmap)"),
    ("edge", "labelURL",        "escString",  "",           _ALL, "URL for label (SVG/map)"),
    ("edge", "layer",           "layerRange", "",           _ALL, "Layer membership"),
    ("edge", "len",             "double",     "1.0",        {"neato","fdp"}, "Preferred edge length in inches"),
    ("edge", "lhead",           "string",     "",           {"dot"}, "Logical head cluster for edge termination"),
    ("edge", "lp",              "point",      "",           _ALL, "Label center position (write-only)"),
    ("edge", "ltail",           "string",     "",           {"dot"}, "Logical tail cluster for edge origination"),
    ("edge", "minlen",          "int",        "1",          {"dot"}, "Minimum rank difference between head and tail"),
    ("edge", "nojustify",       "bool",       "false",      _ALL, "Multiline label justification mode"),
    ("edge", "penwidth",        "double",     "1",          _ALL, "Pen width for edge line in points"),
    ("edge", "pos",             "splineType", "",           _ALL, "Spline control points (write-only in most engines)"),
    ("edge", "radius",          "double",     "0",          _ALL, "Radius of rounded corners on orthogonal edges"),
    ("edge", "samehead",        "string",     "",           {"dot"}, "Share head port with same-value edges"),
    ("edge", "sametail",        "string",     "",           {"dot"}, "Share tail port with same-value edges"),
    ("edge", "showboxes",       "int",        "0",          {"dot"}, "Debug guide boxes for edge routing"),
    ("edge", "style",           "style",      "",           _ALL, "Edge style: solid/dashed/dotted/bold/invis"),
    ("edge", "tail_lp",         "point",      "",           _ALL, "Tail label center position (write-only)"),
    ("edge", "tailclip",        "bool",       "true",       _ALL, "Clip edge to tail node boundary"),
    ("edge", "tailhref",        "escString",  "",           _ALL, "URL for tail of edge (SVG/map)"),
    ("edge", "taillabel",       "lblString",  "",           _ALL, "Label at tail end of edge"),
    ("edge", "tailport",        "portPos",    "center",     _ALL, "Compass port on tail node"),
    ("edge", "tailtarget",      "escString",  "",           _ALL, "Browser window for tailURL (SVG/map)"),
    ("edge", "tailtooltip",     "escString",  "",           _ALL, "Tooltip on tail label (SVG/cmap)"),
    ("edge", "tailURL",         "escString",  "",           _ALL, "URL for tail label (SVG/map)"),
    ("edge", "target",          "escString",  "",           _ALL, "Browser window for URL (SVG/map)"),
    ("edge", "tooltip",         "escString",  "",           _ALL, "Mouse hover tooltip (SVG/cmap)"),
    ("edge", "URL",             "escString",  "",           _ALL, "Hyperlink for edge (SVG/map/PS)"),
    ("edge", "weight",          "double",     "1",          {"dot","neato","fdp","sfdp"}, "Edge weight: rank in dot, spring strength in others"),
    ("edge", "xlabel",          "lblString",  "",           _ALL, "External label outside edge path"),
    ("edge", "xlp",             "point",      "",           _ALL, "External label position (write-only)"),

    # ── Subgraph attributes ──────────────────────
    ("subgraph", "rank",        "rankType",   "",           {"dot"}, "Rank constraint: same, min, max, source, sink"),
]

# ── Build per-engine feature dicts ───────────────

_ENGINE_NAMES = ["dot", "neato", "fdp", "sfdp", "circo", "twopi", "osage", "patchwork"]

# ENGINE_FEATURES[engine][scope] = {attr_name: description}
ENGINE_FEATURES: dict[str, dict[str, dict[str, str]]] = {
    e: {"graph": {}, "node": {}, "edge": {}, "subgraph": {}}
    for e in _ENGINE_NAMES
}

# ATTR_DEFAULTS[attr_name] = default_value_string
ATTR_DEFAULTS: dict[str, str] = {}

# ATTR_TYPES[attr_name] = type_string
ATTR_TYPES: dict[str, str] = {}

for scope, name, atype, default, engines, desc in _ATTR_TABLE:
    ATTR_DEFAULTS[name] = default
    ATTR_TYPES[name] = atype
    for engine in engines:
        if engine in ENGINE_FEATURES:
            ENGINE_FEATURES[engine][scope][name] = desc


# ── Public API ───────────────────────────────────


def get_features(engine_name: str) -> dict[str, dict[str, str]]:
    """Return the attribute feature table for a layout engine.

    Returns a dict with keys ``"graph"``, ``"node"``, ``"edge"``,
    ``"subgraph"``, each mapping attribute names to descriptions.
    """
    return ENGINE_FEATURES.get(engine_name, ENGINE_FEATURES["dot"])


def is_supported(engine_name: str, scope: str, attr_name: str) -> bool:
    """Check if an attribute is supported by a layout engine."""
    features = ENGINE_FEATURES.get(engine_name, {})
    return attr_name in features.get(scope, {})


def get_default(attr_name: str) -> str:
    """Return the default value string for an attribute."""
    return ATTR_DEFAULTS.get(attr_name, "")


def get_type(attr_name: str) -> str:
    """Return the type string for an attribute."""
    return ATTR_TYPES.get(attr_name, "string")


def get_description(engine_name: str, scope: str, attr_name: str) -> str:
    """Return the tooltip description for an attribute in a given engine."""
    features = ENGINE_FEATURES.get(engine_name, {})
    return features.get(scope, {}).get(attr_name, "")
