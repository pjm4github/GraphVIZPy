"""
Interactive layout wizard — test any layout engine with a live preview.

Three-pane GUI: DOT source editor, SVG preview, and parameter controls.
Launched via ``python dot.py --ui`` or ``python gvcli.py --ui``.
"""
from __future__ import annotations

import sys
import logging
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QSplitter, QPlainTextEdit,
    QVBoxLayout, QHBoxLayout, QFormLayout, QScrollArea, QLabel,
    QPushButton, QLineEdit, QComboBox, QCheckBox, QDoubleSpinBox,
    QFileDialog, QStatusBar, QGroupBox, QSpinBox, QTabWidget,
)
from PyQt6.QtCore import Qt, QByteArray
from PyQt6.QtGui import QAction, QFont, QKeySequence
from PyQt6.QtSvgWidgets import QSvgWidget

from gvpy.grammar.gv_reader import read_gv, GVParseError
from gvpy.engines import get_engine, list_engines
from gvpy.engines.layout_features import (
    _ATTR_TABLE, get_description, is_supported,
)
from gvpy.render.svg_renderer import render_svg

logging.disable(logging.WARNING)

_DEFAULT_DOT = """\
digraph G {
    rankdir=TB;
    a -> b -> c;
    a -> c;
}
"""

# Attributes with known combo-box values
_COMBO_VALUES: dict[str, list[str]] = {
    "rankdir":      ["(default)", "TB", "BT", "LR", "RL"],
    "splines":      ["(default)", "true", "curved", "ortho", "polyline", "line", "none"],
    "ordering":     ["(default)", "out", "in"],
    "ratio":        ["(default)", "compress", "fill", "auto"],
    "clusterrank":  ["(default)", "local", "global", "none"],
    "outputorder":  ["(default)", "breadthfirst", "nodesfirst", "edgesfirst"],
    "mode":         ["(default)", "major", "KK", "sgd", "hier", "ipsep"],
    "model":        ["(default)", "shortpath", "circuit", "subset", "mds"],
    "overlap":      ["(default)", "true", "false", "scale", "compress", "prism", "voronoi"],
    "smoothing":    ["(default)", "none", "avg_dist", "graph_dist", "power_dist", "rng", "spring", "triangle"],
    "quadtree":     ["(default)", "normal", "fast", "none"],
    "packmode":     ["(default)", "node", "clust", "graph", "array"],
    "pagedir":      ["(default)", "BL", "BR", "TL", "TR", "LB", "LT", "RB", "RT"],
    "dir":          ["(default)", "forward", "back", "both", "none"],
    "shape":        ["(default)", "ellipse", "box", "circle", "diamond",
                     "plaintext", "point", "record", "Mrecord",
                     "triangle", "pentagon", "hexagon", "octagon",
                     "doublecircle", "doubleoctagon", "house", "invhouse",
                     "cylinder", "note", "tab", "folder", "component"],
    "style":        ["(default)", "solid", "filled", "rounded", "dashed", "dotted",
                     "bold", "invis", "striped", "wedged"],
    "arrowhead":    ["(default)", "normal", "inv", "dot", "odot",
                     "none", "vee", "crow", "tee",
                     "diamond", "odiamond", "box", "obox"],
    "arrowtail":    ["(default)", "normal", "inv", "dot", "odot",
                     "none", "vee", "crow", "tee",
                     "diamond", "odiamond", "box", "obox"],
    "labelloc":     ["(default)", "t", "c", "b"],
    "labeljust":    ["(default)", "l", "c", "r"],
    "imagepos":     ["(default)", "mc", "tl", "tc", "tr", "ml", "mr", "bl", "bc", "br"],
    "TBbalance":    ["(default)", "min", "max", "none"],
    "fontname":     ["(default)", "Times-Roman", "Helvetica", "Courier",
                     "Arial", "sans-serif", "serif", "monospace"],
}

# Attributes to skip in the wizard (write-only or internal)
_SKIP_ATTRS = {
    "bb", "lp", "xlp", "head_lp", "tail_lp", "lheight", "lwidth",
    "rects", "vertices", "pos", "xdotversion", "_background",
    "fontpath", "imagepath", "fontnames", "charset", "linelength",
    "truecolor", "page", "viewport", "layerlistsep", "layers",
    "layerselect", "layersep", "layout", "samplepoints", "shapefile",
    "sortv", "layer",
}

# Order within each scope — common attrs first
_GRAPH_ORDER = [
    "rankdir", "splines", "nodesep", "ranksep", "mindist", "K",
    "mode", "model", "overlap", "ordering", "ratio", "size",
    "label", "labelloc", "labeljust", "bgcolor", "fontname", "fontsize", "fontcolor",
    "concentrate", "compound", "newrank", "clusterrank", "normalize", "center",
    "pack", "packmode", "pad", "dpi", "rotate", "landscape", "outputorder",
    "maxiter", "epsilon", "start", "Damping", "defaultdist", "dim",
    "forcelabels", "sep", "esep", "quantum", "mclimit", "remincross",
    "nslimit", "nslimit1", "searchsize", "TBbalance", "notranslate",
    "beautify", "smoothing", "quadtree", "repulsiveforce", "label_scheme",
    "levels", "levelsgap", "oneblock", "rotation", "inputscale",
    "diredgeconstraints", "overlap_scaling", "overlap_shrink", "voro_margin",
    "scale",
]

_NODE_ORDER = [
    "shape", "label", "xlabel", "fontname", "fontsize", "fontcolor",
    "color", "fillcolor", "style", "penwidth", "width", "height",
    "fixedsize", "group", "pin", "labelloc", "image", "imagepos", "imagescale",
    "orientation", "sides", "distortion", "skew", "regular", "peripheries",
    "margin", "nojustify", "gradientangle", "colorscheme",
    "K", "area", "root", "ordering", "z",
    "tooltip", "URL", "href", "target", "id", "class", "comment",
]

_EDGE_ORDER = [
    "label", "xlabel", "headlabel", "taillabel",
    "color", "fontcolor", "fontname", "fontsize", "style", "penwidth",
    "arrowhead", "arrowtail", "arrowsize", "dir",
    "weight", "len", "minlen", "constraint",
    "headport", "tailport", "headclip", "tailclip",
    "samehead", "sametail", "lhead", "ltail",
    "labelfontname", "labelfontsize", "labelfontcolor",
    "labelangle", "labeldistance", "labelfloat",
    "decorate", "nojustify", "fillcolor", "colorscheme",
    "tooltip", "URL", "href", "target", "id", "class", "comment",
    "edgeURL", "edgehref", "edgetarget", "edgetooltip",
    "headURL", "headhref", "headtarget", "headtooltip",
    "labelURL", "labelhref", "labeltarget", "labeltooltip",
    "tailURL", "tailhref", "tailtarget", "tailtooltip",
]


class _AspectSvgWidget(QSvgWidget):
    """QSvgWidget that scales SVG to fit the widget while preserving aspect ratio."""

    def sizeHint(self):
        """Return parent size so the widget fills available space."""
        from PyQt6.QtCore import QSize
        parent = self.parentWidget()
        if parent:
            return parent.size()
        return QSize(400, 400)

    def paintEvent(self, event):
        from PyQt6.QtSvg import QSvgRenderer
        from PyQt6.QtGui import QPainter
        from PyQt6.QtCore import QRectF
        renderer = self.renderer()
        if renderer is None or not renderer.isValid():
            return
        painter = QPainter(self)
        # Fill background
        painter.fillRect(self.rect(), painter.background())

        vbox = renderer.viewBox()
        if vbox.isEmpty():
            renderer.render(painter)
        else:
            svg_w, svg_h = float(vbox.width()), float(vbox.height())
            wid_w, wid_h = float(self.width()), float(self.height())
            if svg_w <= 0 or svg_h <= 0:
                renderer.render(painter)
                painter.end()
                return
            # Scale to fit widget, centered
            scale = min(wid_w / svg_w, wid_h / svg_h)
            rw, rh = svg_w * scale, svg_h * scale
            rx = (wid_w - rw) / 2.0
            ry = (wid_h - rh) / 2.0
            renderer.render(painter, QRectF(rx, ry, rw, rh))
        painter.end()


def _make_widget(attr_name: str, attr_type: str, default: str) -> QWidget:
    """Create the appropriate widget for an attribute based on its type."""
    # Check for combo values first
    if attr_name in _COMBO_VALUES:
        w = QComboBox()
        w.setEditable(attr_name == "fontname")
        w.addItems(_COMBO_VALUES[attr_name])
        w.setMaximumHeight(24)
        return w

    if attr_type == "bool":
        w = QCheckBox()
        if default.lower() in ("true", "1"):
            w.setChecked(True)
        return w

    if attr_type in ("double", "addDouble"):
        w = QDoubleSpinBox()
        w.setRange(-1000, 10000)
        w.setSingleStep(0.1)
        w.setDecimals(3)
        w.setSpecialValueText("(default)")
        w.setMaximumHeight(22)
        try:
            v = float(default) if default and default not in ("", "0") else 0
            w.setValue(v if v != 0 else w.minimum())
        except ValueError:
            pass
        return w

    if attr_type == "int":
        w = QSpinBox()
        w.setRange(-1000, 100000)
        w.setSpecialValueText("(default)")
        w.setMaximumHeight(22)
        try:
            if default:
                w.setValue(int(default))
            else:
                # No default → start at minimum so the widget shows "(default)"
                # and _get_widget_value returns None (no command-line flag).
                w.setValue(w.minimum())
        except ValueError:
            pass
        return w

    # Default: line edit
    w = QLineEdit()
    if default:
        w.setPlaceholderText(default)
    w.setMaximumHeight(22)
    return w


def _get_widget_value(widget: QWidget, default: str = "") -> str | None:
    """Get the current value from a widget, or None if at default.

    Returns None when the widget value matches the attribute's default,
    so the command line only shows non-default overrides.
    """
    if isinstance(widget, QComboBox):
        text = widget.currentText()
        if text == "(default)":
            return None
        # Check if the selected value matches the actual default
        if text.lower() == default.lower():
            return None
        return text
    elif isinstance(widget, QCheckBox):
        checked = widget.isChecked()
        default_checked = default.lower() in ("true", "1")
        if checked == default_checked:
            return None
        return "true" if checked else "false"
    elif isinstance(widget, QDoubleSpinBox):
        if widget.value() == widget.minimum():
            return None
        # Compare to default
        try:
            if default and abs(widget.value() - float(default)) < 0.001:
                return None
        except ValueError:
            pass
        return str(widget.value())
    elif isinstance(widget, QSpinBox):
        if widget.value() == widget.minimum():
            return None
        try:
            if default and widget.value() == int(default):
                return None
        except ValueError:
            pass
        return str(widget.value())
    elif isinstance(widget, QLineEdit):
        text = widget.text().strip()
        if not text or text == default:
            return None
        return text
    return None


class LayoutWizard(QMainWindow):
    """Interactive layout wizard with editor, preview, and controls."""

    def __init__(self, initial_file: str | None = None,
                 engine: str = "dot"):
        super().__init__()
        self._engine_name = engine
        self.setWindowTitle(f"GraphvizPy — Layout Wizard [{engine}]")
        self.resize(1400, 800)
        self._current_file: str | None = None
        self._last_svg: str = ""
        self._last_output: str = ""

        # Build attribute lookup: {(scope, name): (type, default, engines, desc)}
        self._attr_info: dict[tuple[str, str], tuple[str, str, set, str]] = {}
        for scope, name, atype, default, engines, desc in _ATTR_TABLE:
            self._attr_info[(scope, name)] = (atype, default, engines, desc)

        # Widget registry: [(scope, attr_name, widget, default_value)]
        self._feature_widgets: list[tuple[str, str, QWidget, str]] = []

        self._build_menu()
        self._build_ui()
        self._update_feature_visibility()
        self._update_command()

        if initial_file:
            self._editor.setPlainText(
                Path(initial_file).read_text(encoding="utf-8"))
            self._current_file = initial_file
            self.setWindowTitle(
                f"GraphvizPy — Layout Wizard [{engine}] — {Path(initial_file).name}")
        else:
            self._editor.setPlainText(_DEFAULT_DOT)

        # Defer initial layout to after the window is shown
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(0, self._run_layout)

    def _build_menu(self):
        menu = self.menuBar()
        file_menu = menu.addMenu("File")

        open_act = QAction("Open...", self)
        open_act.setShortcut(QKeySequence.StandardKey.Open)
        open_act.triggered.connect(self._on_open)
        file_menu.addAction(open_act)

        save_act = QAction("Save Source...", self)
        save_act.setShortcut(QKeySequence.StandardKey.Save)
        save_act.triggered.connect(self._on_save_source)
        file_menu.addAction(save_act)

        export_act = QAction("Export SVG...", self)
        export_act.setShortcut(QKeySequence("Ctrl+Shift+S"))
        export_act.triggered.connect(self._on_export_svg)
        file_menu.addAction(export_act)

        file_menu.addSeparator()
        exit_act = QAction("Exit", self)
        exit_act.setShortcut(QKeySequence("Ctrl+Q"))
        exit_act.triggered.connect(self.close)
        file_menu.addAction(exit_act)

        view_menu = menu.addMenu("View")
        run_act = QAction("Run Layout", self)
        run_act.setShortcut(QKeySequence("Ctrl+Return"))
        run_act.triggered.connect(self._run_layout)
        view_menu.addAction(run_act)

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(4, 4, 4, 4)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: DOT source editor
        self._editor = QPlainTextEdit()
        self._editor.setFont(QFont("Consolas", 11))
        self._editor.setPlaceholderText("Enter DOT source here...")
        self._editor.setTabStopDistance(28)
        splitter.addWidget(self._editor)

        # Center: SVG preview
        self._svg_widget = _AspectSvgWidget()
        self._svg_widget.setMinimumWidth(200)
        self._svg_widget.setStyleSheet("background-color: white;")
        splitter.addWidget(self._svg_widget)

        # Right: parameter tabs
        param_scroll = QScrollArea()
        param_scroll.setWidgetResizable(True)
        param_scroll.setMinimumWidth(250)
        param_scroll.setMaximumWidth(360)

        param_container = QWidget()
        param_vlayout = QVBoxLayout(param_container)
        param_vlayout.setContentsMargins(2, 2, 2, 2)
        param_vlayout.setSpacing(2)

        # Engine selector at top
        engine_row = QHBoxLayout()
        engine_row.addWidget(QLabel("Engine:"))
        self._engine_combo = QComboBox()
        engines_info = list_engines()
        for name, info in sorted(engines_info.items()):
            lbl = name if info["status"] == "implemented" else f"{name} (stub)"
            self._engine_combo.addItem(lbl, name)
        for i in range(self._engine_combo.count()):
            if self._engine_combo.itemData(i) == self._engine_name:
                self._engine_combo.setCurrentIndex(i)
                break
        self._engine_combo.currentIndexChanged.connect(self._on_engine_changed)
        engine_row.addWidget(self._engine_combo, stretch=1)
        param_vlayout.addLayout(engine_row)

        # Output Options panel
        out_group = QGroupBox("Output Options")
        out_layout = QFormLayout()
        out_layout.setContentsMargins(4, 6, 4, 4)
        out_layout.setSpacing(3)

        self._out_format = QComboBox()
        self._out_format.addItems(["svg", "json", "dot", "json0", "gxl"])
        self._out_format.setToolTip("Output format (-T)")
        self._out_format.setMaximumHeight(24)
        out_layout.addRow("-T format:", self._out_format)

        self._out_file = QLineEdit()
        self._out_file.setPlaceholderText("(preview only)")
        self._out_file.setToolTip("Write output to file (-o). Leave empty for preview only.")
        self._out_file.setMaximumHeight(22)
        out_layout.addRow("-o file:", self._out_file)

        self._out_auto = QCheckBox()
        self._out_auto.setToolTip("Auto-name output: input.FORMAT (-O)")
        out_layout.addRow("-O auto:", self._out_auto)

        self._out_verbose = QCheckBox()
        self._out_verbose.setToolTip("Print layout summary to stderr (-v)")
        out_layout.addRow("-v verbose:", self._out_verbose)

        self._out_no_layout = QCheckBox()
        self._out_no_layout.setToolTip("Skip layout, use existing pos attributes (-n)")
        out_layout.addRow("-n no layout:", self._out_no_layout)

        self._out_scale = QDoubleSpinBox()
        self._out_scale.setRange(0, 100)
        self._out_scale.setSingleStep(0.5)
        self._out_scale.setValue(0)
        self._out_scale.setSpecialValueText("(none)")
        self._out_scale.setToolTip("Scale output coordinates (-s)")
        self._out_scale.setMaximumHeight(22)
        out_layout.addRow("-s scale:", self._out_scale)

        self._out_invert_y = QCheckBox()
        self._out_invert_y.setToolTip("Invert Y axis (-y)")
        out_layout.addRow("-y invert Y:", self._out_invert_y)

        self._out_bundle = QCheckBox()
        self._out_bundle.setToolTip("Apply mingle edge bundling after layout (--bundle)")
        out_layout.addRow("--bundle:", self._out_bundle)

        self._out_max_svg = QSpinBox()
        self._out_max_svg.setRange(0, 100000)
        self._out_max_svg.setSingleStep(100)
        self._out_max_svg.setValue(5000)
        self._out_max_svg.setSpecialValueText("(unlimited)")
        self._out_max_svg.setToolTip(
            "Max SVG size in KB for preview. Larger files skip preview "
            "to avoid hanging. 0 = unlimited.")
        self._out_max_svg.setMaximumHeight(22)
        out_layout.addRow("Max SVG KB:", self._out_max_svg)

        out_group.setLayout(out_layout)
        param_vlayout.addWidget(out_group)

        # Connect output option changes
        self._out_format.currentTextChanged.connect(self._update_command)
        self._out_file.textChanged.connect(self._update_command)
        self._out_auto.stateChanged.connect(self._update_command)
        self._out_verbose.stateChanged.connect(self._update_command)
        self._out_no_layout.stateChanged.connect(self._update_command)
        self._out_scale.valueChanged.connect(self._update_command)
        self._out_invert_y.stateChanged.connect(self._update_command)
        self._out_bundle.stateChanged.connect(self._update_command)

        # Tabbed attribute panels
        tabs = QTabWidget()
        tabs.setTabPosition(QTabWidget.TabPosition.North)
        tabs.setStyleSheet("""
            QTabBar::tab {
                padding: 6px 16px;
                margin-right: 2px;
                border: 1px solid #999;
                border-bottom: none;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
                background: #e0e0e0;
                color: #555;
            }
            QTabBar::tab:selected {
                background: #ffffff;
                color: #000;
                font-weight: bold;
                border-bottom: 2px solid #3374b8;
            }
            QTabBar::tab:hover:!selected {
                background: #d0d8e0;
            }
            QTabWidget::pane {
                border: 1px solid #999;
                border-top: none;
            }
        """)

        tabs.addTab(self._build_attr_panel("graph", _GRAPH_ORDER), "Graph")
        tabs.addTab(self._build_attr_panel("node", _NODE_ORDER), "Node")
        tabs.addTab(self._build_attr_panel("edge", _EDGE_ORDER), "Edge")
        param_vlayout.addWidget(tabs, stretch=1)

        param_scroll.setWidget(param_container)
        splitter.addWidget(param_scroll)

        splitter.setSizes([380, 500, 320])
        main_layout.addWidget(splitter, stretch=1)

        # Bottom bar — editable command line with Reset and Run
        bottom = QHBoxLayout()
        bottom.addWidget(QLabel("Cmd:"))
        self._cmd_line = QLineEdit()
        self._cmd_line.setFont(QFont("Consolas", 9))
        self._cmd_line.setToolTip(
            "Editable command line. Edit directly then press Enter to sync.\n"
            "Press Run (Ctrl+Enter) to execute.\n"
            "Press Reset to rebuild from control panel settings.")
        self._cmd_line.returnPressed.connect(self._parse_command_to_controls)
        self._cmd_line.editingFinished.connect(self._parse_command_to_controls)
        self._updating_from_cmd = False  # prevent recursive updates
        bottom.addWidget(self._cmd_line, stretch=1)
        reset_btn = QPushButton("Reset")
        reset_btn.setToolTip("Rebuild command line from control panel settings")
        reset_btn.clicked.connect(self._rebuild_command)
        bottom.addWidget(reset_btn)
        run_btn = QPushButton("Run")
        run_btn.setDefault(True)
        run_btn.clicked.connect(self._run_layout)
        bottom.addWidget(run_btn)
        main_layout.addLayout(bottom)

        self.setStatusBar(QStatusBar())

    def _build_attr_panel(self, scope: str, order: list[str]) -> QScrollArea:
        """Build a scrollable form panel for attributes of a given scope."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        widget = QWidget()
        form = QFormLayout(widget)
        form.setContentsMargins(6, 6, 6, 6)
        form.setSpacing(4)
        form.setVerticalSpacing(4)
        form.setHorizontalSpacing(8)

        # Collect all attrs for this scope from the table
        scope_attrs: dict[str, tuple[str, str, set, str]] = {}
        for (s, name), (atype, default, engines, desc) in self._attr_info.items():
            if s == scope and name not in _SKIP_ATTRS:
                scope_attrs[name] = (atype, default, engines, desc)

        # Alphabetical order
        all_names = sorted(scope_attrs.keys(), key=str.lower)

        for attr_name in all_names:
            atype, default, engines, desc = scope_attrs[attr_name]
            w = _make_widget(attr_name, atype, default)

            # Connect change signal
            if isinstance(w, QComboBox):
                w.currentTextChanged.connect(self._update_command)
            elif isinstance(w, QCheckBox):
                w.stateChanged.connect(self._update_command)
            elif isinstance(w, (QDoubleSpinBox, QSpinBox)):
                w.valueChanged.connect(self._update_command)
            elif isinstance(w, QLineEdit):
                w.textChanged.connect(self._update_command)

            form.addRow(f"{attr_name}:", w)
            self._feature_widgets.append((scope, attr_name, w, default))

        scroll.setWidget(widget)
        return scroll

    # ── Engine selector ─────────────────────────

    def _on_engine_changed(self, index):
        self._engine_name = self._engine_combo.itemData(index)
        self.setWindowTitle(f"GraphvizPy — Layout Wizard [{self._engine_name}]")
        self._update_feature_visibility()
        self._update_command()

    def _update_feature_visibility(self):
        """Enable/disable controls and set tooltips per engine.

        Disabled attributes are dimmed but still show their tooltip
        so the user knows what the attribute does and why it's unavailable.
        """
        for scope, attr_name, widget, _default in self._feature_widgets:
            supported = is_supported(self._engine_name, scope, attr_name)
            widget.setEnabled(supported)

            desc = get_description(self._engine_name, scope, attr_name)
            if supported:
                tooltip = desc or attr_name
            else:
                # Show description + reason even when disabled
                base = desc or attr_name
                tooltip = f"{base}\n(not available for {self._engine_name} engine)"

            widget.setToolTip(tooltip)

            # Dim the label text for unsupported attributes
            parent = widget.parentWidget()
            if parent:
                layout = parent.layout()
                if layout and hasattr(layout, 'labelForField'):
                    label = layout.labelForField(widget)
                    if label:
                        label.setToolTip(tooltip)
                        if supported:
                            label.setEnabled(True)
                            label.setStyleSheet("")
                        else:
                            label.setEnabled(False)
                            label.setStyleSheet("color: #aaaaaa;")

    # ── Command line builder ─────────────────────

    def _build_overrides(self) -> tuple[list[str], list[str], list[str]]:
        """Build -G, -N, -E flags from all parameter controls."""
        g_flags, n_flags, e_flags = [], [], []

        for scope, attr_name, widget, default in self._feature_widgets:
            if not widget.isEnabled():
                continue
            val = _get_widget_value(widget, default)
            if val is None:
                continue

            # Map scope to flag prefix
            if scope == "graph":
                g_flags.append(f"-G{attr_name}={val}")
            elif scope == "node":
                n_flags.append(f"-N{attr_name}={val}")
            elif scope == "edge":
                e_flags.append(f"-E{attr_name}={val}")

        return g_flags, n_flags, e_flags

    def _rebuild_command(self):
        """Rebuild the entire command line from control panel settings."""
        if self._updating_from_cmd:
            return
        fname = self._current_file or "input.gv"
        g_flags, n_flags, e_flags = self._build_overrides()

        parts = ["python", "gvcli.py"]

        # Engine
        if self._engine_name != "dot":
            parts.append(f"-K{self._engine_name}")

        parts.append(fname)

        # Output format
        fmt = self._out_format.currentText()
        parts.append(f"-T{fmt}")

        # Output file
        out_file = self._out_file.text().strip()
        if out_file:
            parts.append(f"-o {out_file}")

        # Output flags
        if self._out_auto.isChecked():
            parts.append("-O")
        if self._out_verbose.isChecked():
            parts.append("-v")
        if self._out_no_layout.isChecked():
            parts.append("-n")
        scale = self._out_scale.value()
        if scale > 0:
            parts.append(f"-s {scale}")
        if self._out_invert_y.isChecked():
            parts.append("-y")
        if self._out_bundle.isChecked():
            parts.append("--bundle")

        parts.extend(g_flags + n_flags + e_flags)
        self._cmd_line.setText(" ".join(parts))

    def _update_command(self):
        """Rebuild command line when a control panel widget changes."""
        if self._updating_from_cmd:
            return
        self._rebuild_command()

    def _parse_command_to_controls(self):
        """Parse the edited command line back into control panel widgets.

        Called when the user presses Enter or leaves the cmd line field.
        Widgets that change flash briefly to draw attention.
        """
        text = self._cmd_line.text().strip()
        if not text:
            return

        self._updating_from_cmd = True
        try:
            self._do_parse_cmd(text)
        finally:
            self._updating_from_cmd = False

    def _do_parse_cmd(self, text: str):
        """Parse command text and sync controls."""
        import shlex
        try:
            tokens = shlex.split(text)
        except ValueError:
            tokens = text.split()

        # Extract known flags
        cmd_flags: dict[str, str] = {}
        cmd_bool: set[str] = set()
        i = 0
        while i < len(tokens):
            tok = tokens[i]
            if tok.startswith("-T") and len(tok) > 2:
                cmd_flags["T"] = tok[2:]
            elif tok.startswith("-K") and len(tok) > 2:
                cmd_flags["K"] = tok[2:]
            elif tok.startswith("-o") and len(tok) > 2:
                cmd_flags["o"] = tok[2:]
            elif tok == "-o" and i + 1 < len(tokens):
                i += 1
                cmd_flags["o"] = tokens[i]
            elif tok.startswith("-s") and len(tok) > 2:
                cmd_flags["s"] = tok[2:]
            elif tok == "-s" and i + 1 < len(tokens):
                i += 1
                cmd_flags["s"] = tokens[i]
            elif tok == "-O":
                cmd_bool.add("O")
            elif tok == "-v":
                cmd_bool.add("v")
            elif tok == "-n":
                cmd_bool.add("n")
            elif tok == "-y":
                cmd_bool.add("y")
            elif tok == "--bundle":
                cmd_bool.add("bundle")
            elif tok.startswith("-G") and "=" in tok:
                k, v = tok[2:].split("=", 1)
                cmd_flags[f"G:{k}"] = v
            elif tok.startswith("-N") and "=" in tok:
                k, v = tok[2:].split("=", 1)
                cmd_flags[f"N:{k}"] = v
            elif tok.startswith("-E") and "=" in tok:
                k, v = tok[2:].split("=", 1)
                cmd_flags[f"E:{k}"] = v
            i += 1

        changed_widgets: list[QWidget] = []

        # Sync output format
        fmt = cmd_flags.get("T", "svg")
        if self._out_format.currentText() != fmt:
            idx = self._out_format.findText(fmt)
            if idx >= 0:
                self._out_format.setCurrentIndex(idx)
                changed_widgets.append(self._out_format)

        # Sync engine
        eng = cmd_flags.get("K", "dot")
        if eng != self._engine_name:
            for i in range(self._engine_combo.count()):
                if self._engine_combo.itemData(i) == eng:
                    self._engine_combo.setCurrentIndex(i)
                    changed_widgets.append(self._engine_combo)
                    break

        # Sync output file
        ofile = cmd_flags.get("o", "")
        if self._out_file.text().strip() != ofile:
            self._out_file.setText(ofile)
            changed_widgets.append(self._out_file)

        # Sync checkboxes
        for flag, widget in [("O", self._out_auto), ("v", self._out_verbose),
                              ("n", self._out_no_layout), ("y", self._out_invert_y),
                              ("bundle", self._out_bundle)]:
            new_val = flag in cmd_bool
            if widget.isChecked() != new_val:
                widget.setChecked(new_val)
                changed_widgets.append(widget)

        # Sync scale
        try:
            new_scale = float(cmd_flags.get("s", "0"))
        except ValueError:
            new_scale = 0.0
        if abs(self._out_scale.value() - new_scale) > 0.001:
            self._out_scale.setValue(new_scale)
            changed_widgets.append(self._out_scale)

        # Sync -G/-N/-E attribute widgets
        scope_map = {"G": "graph", "N": "node", "E": "edge"}
        for key, val in cmd_flags.items():
            if ":" not in key:
                continue
            prefix, attr_name = key.split(":", 1)
            scope = scope_map.get(prefix)
            if not scope:
                continue
            for s, a, widget, default in self._feature_widgets:
                if s == scope and a == attr_name:
                    if self._set_widget_value(widget, val, default):
                        changed_widgets.append(widget)
                    break

        # Flash changed widgets
        if changed_widgets:
            self._flash_widgets(changed_widgets)

    @staticmethod
    def _set_widget_value(widget: QWidget, val: str, default: str) -> bool:
        """Set a widget's value from a string. Returns True if changed."""
        if isinstance(widget, QComboBox):
            old = widget.currentText()
            idx = widget.findText(val)
            if idx >= 0 and widget.currentIndex() != idx:
                widget.setCurrentIndex(idx)
                return True
            elif widget.isEditable() and old != val:
                widget.setCurrentText(val)
                return True
        elif isinstance(widget, QCheckBox):
            new_checked = val.lower() in ("true", "1", "yes")
            if widget.isChecked() != new_checked:
                widget.setChecked(new_checked)
                return True
        elif isinstance(widget, QDoubleSpinBox):
            try:
                new_val = float(val)
                if abs(widget.value() - new_val) > 0.001:
                    widget.setValue(new_val)
                    return True
            except ValueError:
                pass
        elif isinstance(widget, QSpinBox):
            try:
                new_val = int(val)
                if widget.value() != new_val:
                    widget.setValue(new_val)
                    return True
            except ValueError:
                pass
        elif isinstance(widget, QLineEdit):
            if widget.text() != val:
                widget.setText(val)
                return True
        return False

    def _flash_widgets(self, widgets: list[QWidget]):
        """Briefly flash widgets yellow to draw attention to changes."""
        from PyQt6.QtCore import QTimer

        for w in widgets:
            w.setStyleSheet("background-color: #ffffaa;")

        def _clear():
            for w in widgets:
                try:
                    w.setStyleSheet("")
                except RuntimeError:
                    pass  # widget may have been deleted

        QTimer.singleShot(1200, _clear)

    # ── Layout execution ─────────────────────────

    def _run_layout(self):
        source = self._editor.toPlainText().strip()
        if not source:
            self.statusBar().showMessage("No DOT source to layout.")
            return

        # Show wait cursor while running layout
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self._do_run_layout(source)
        finally:
            QApplication.restoreOverrideCursor()

    def _status(self, msg: str, pct: int = -1):
        """Update status bar with message and optional progress percentage."""
        if pct >= 0:
            self.statusBar().showMessage(f"[{pct}%] {msg}")
        else:
            self.statusBar().showMessage(msg)
        QApplication.processEvents()  # force UI repaint

    def _do_run_layout(self, source: str):
        import time
        t0 = time.time()

        self._status(f"[{self._engine_name}] Parsing DOT source...", 0)

        try:
            graph = read_gv(source)
        except GVParseError as e:
            self._status(f"Parse error: {e}")
            return
        except Exception as e:
            self._status(f"Error: {e}")
            return

        nn = len(graph.nodes)
        ne = len(graph.edges)
        self._status(f"[{self._engine_name}] Parsed: {nn} nodes, {ne} edges. "
                     f"Applying overrides...", 5)

        g_flags, n_flags, e_flags = self._build_overrides()

        for flag in g_flags:
            spec = flag[2:]
            if "=" in spec:
                k, v = spec.split("=", 1)
                graph.set_graph_attr(k, v)

        for flag in n_flags:
            spec = flag[2:]
            if "=" in spec:
                k, v = spec.split("=", 1)
                for node in graph.nodes.values():
                    if k not in node.attributes:
                        node.agset(k, v)

        for flag in e_flags:
            spec = flag[2:]
            if "=" in spec:
                k, v = spec.split("=", 1)
                for edge in graph.edges.values():
                    if k not in edge.attributes:
                        edge.agset(k, v)

        # Skip layout if -n is checked
        if self._out_no_layout.isChecked():
            self._status("No-layout mode: skipping layout.")
            return

        self._status(f"[{self._engine_name}] Running layout engine "
                     f"({nn} nodes, {ne} edges)...", 10)

        try:
            EngineClass = get_engine(self._engine_name)
            engine = EngineClass(graph)
            result = engine.layout()
        except NotImplementedError as e:
            self._status(f"Engine '{self._engine_name}' not implemented: {e}")
            return
        except Exception as e:
            self._status(f"Layout error: {e}")
            return

        t_layout = time.time() - t0
        self._status(f"[{self._engine_name}] Layout complete ({t_layout:.1f}s). "
                     f"Post-processing...", 60)

        # Edge bundling
        if self._out_bundle.isChecked():
            self._status(f"[{self._engine_name}] Bundling edges...", 65)
            from gvpy.tools.mingle import MingleBundler
            result = MingleBundler.bundle_result(result)

        # Scale
        scale = self._out_scale.value()
        if scale > 0 and scale != 1.0:
            from gvcli import _apply_scale
            _apply_scale(result, scale)

        # Invert Y
        if self._out_invert_y.isChecked():
            from gvcli import _apply_invert_y
            _apply_invert_y(result)

        self._status(f"[{self._engine_name}] Rendering output...", 75)

        # Render to selected format
        fmt = self._out_format.currentText()
        import json
        if fmt == "svg":
            output_text = render_svg(result)
        elif fmt == "dot":
            from gvpy.grammar.gv_writer import write_gv
            output_text = write_gv(graph)
        elif fmt == "json0":
            from gvpy.render.json_io import write_json0
            output_text = write_json0(graph)
        elif fmt == "gxl":
            from gvpy.render.gxl_io import write_gxl
            output_text = write_gxl(graph)
        else:
            output_text = json.dumps(result, indent=2)

        self._last_svg = output_text if fmt == "svg" else ""
        self._last_output = output_text

        # Write to file if -o is set
        out_file = self._out_file.text().strip()
        if out_file:
            self._status(f"[{self._engine_name}] Writing to {out_file}...", 85)
            from pathlib import Path
            Path(out_file).write_text(output_text, encoding="utf-8")

        # Auto-name if -O
        if self._out_auto.isChecked() and self._current_file:
            from pathlib import Path
            ext = {"svg": ".svg", "json": ".json", "dot": ".gv",
                   "json0": ".json", "gxl": ".gxl"}.get(fmt, f".{fmt}")
            auto_path = Path(self._current_file).with_suffix(ext)
            auto_path.write_text(output_text, encoding="utf-8")
            self._status(f"[{self._engine_name}] Written to {auto_path}", 90)

        # SVG preview
        n = len(result["nodes"])
        e = len(result["edges"])
        c = len(result.get("clusters", []))
        t_total = time.time() - t0

        if fmt == "svg":
            svg_kb = len(output_text) // 1024
            max_kb = self._out_max_svg.value()
            if max_kb > 0 and svg_kb > max_kb:
                self._status(
                    f"[{self._engine_name}] Done ({t_total:.1f}s) — "
                    f"{n} nodes, {e} edges — SVG too large ({svg_kb} KB > "
                    f"{max_kb} KB limit), preview skipped."
                    f"{' Written to ' + out_file if out_file else ''}")
                return

            self._status(f"[{self._engine_name}] Loading SVG preview "
                         f"({svg_kb} KB)...", 95)
            svg_bytes = QByteArray(output_text.encode("utf-8"))
            self._svg_widget.load(svg_bytes)
            self._svg_widget.updateGeometry()
            self._svg_widget.repaint()

            self._status(
                f"[{self._engine_name}] Done ({t_total:.1f}s) — "
                f"{n} nodes, {e} edges, {c} clusters — {svg_kb} KB SVG"
                f"{' → ' + out_file if out_file else ''}", 100)
        else:
            self._status(
                f"[{self._engine_name}] Done ({t_total:.1f}s) — "
                f"{n} nodes, {e} edges — format: {fmt}"
                f"{' → ' + out_file if out_file else ''}", 100)

    # ── File operations ──────────────────────────

    def _on_open(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open DOT File", "",
            "DOT Files (*.gv *.dot);;All Files (*)",
        )
        if path:
            self._load_file(Path(path))

    def _load_file(self, path: Path):
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = path.read_text(encoding="latin-1")
        self._editor.setPlainText(text)
        self._current_file = str(path)

        # Honor layout= attribute in the DOT source
        self._detect_layout_engine(text)

        self.setWindowTitle(
            f"GraphvizPy — Layout Wizard [{self._engine_name}] — {path.name}")
        self._update_command()
        self._run_layout()

    def _detect_layout_engine(self, dot_text: str):
        """Scan DOT source for a layout= graph attribute and switch the
        engine combo to match.  Only changes the engine if the attribute
        is found and valid; otherwise the current selection is kept."""
        import re
        m = re.search(r'\blayout\s*=\s*"?(\w+)"?', dot_text)
        if not m:
            return
        engine = m.group(1).lower()
        valid = {"dot", "neato", "fdp", "sfdp", "circo", "twopi",
                 "osage", "patchwork"}
        if engine not in valid:
            return
        for i in range(self._engine_combo.count()):
            if self._engine_combo.itemData(i) == engine:
                self._engine_combo.setCurrentIndex(i)
                break

    def _on_save_source(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save DOT Source", "",
            "DOT Files (*.gv *.dot);;All Files (*)",
        )
        if path:
            Path(path).write_text(self._editor.toPlainText(), encoding="utf-8")
            self._current_file = path
            self.setWindowTitle(
                f"GraphvizPy — Layout Wizard [{self._engine_name}] — {Path(path).name}")
            self._update_command()
            self.statusBar().showMessage(f"Saved to {path}")

    def _on_export_svg(self):
        if not self._last_svg:
            self.statusBar().showMessage("No SVG to export. Run layout first.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export SVG", "",
            "SVG Files (*.svg);;All Files (*)",
        )
        if path:
            Path(path).write_text(self._last_svg, encoding="utf-8")
            self.statusBar().showMessage(f"SVG exported to {path}")


def launch_wizard(initial_file: str | None = None, engine: str = "dot"):
    """Launch the layout wizard GUI."""
    app = QApplication.instance() or QApplication(sys.argv)
    wizard = LayoutWizard(initial_file, engine=engine)
    wizard.show()
    sys.exit(app.exec())
