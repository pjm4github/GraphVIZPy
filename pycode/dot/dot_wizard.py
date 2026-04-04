"""
Interactive wizard for the dot layout engine.

Three-pane GUI: DOT source editor, SVG preview, and parameter controls.
Launched via ``python dot.py --ui``.
"""
from __future__ import annotations

import sys
import logging
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QSplitter, QPlainTextEdit,
    QVBoxLayout, QHBoxLayout, QFormLayout, QScrollArea, QLabel,
    QPushButton, QLineEdit, QComboBox, QCheckBox, QDoubleSpinBox,
    QFileDialog, QMessageBox, QStatusBar, QGroupBox, QSpinBox,
)
from PyQt6.QtCore import Qt, QByteArray
from PyQt6.QtGui import QAction, QFont, QKeySequence
from PyQt6.QtSvgWidgets import QSvgWidget

from pycode.dot.dot_reader import read_dot, DOTParseError
from pycode.dot.dot_layout import DotLayout
from pycode.dot.svg_renderer import render_svg

logging.disable(logging.WARNING)

_DEFAULT_DOT = """\
digraph G {
    rankdir=TB;
    a -> b -> c;
    a -> c;
}
"""


class _AspectSvgWidget(QSvgWidget):
    """QSvgWidget that preserves aspect ratio when rendering."""

    def paintEvent(self, event):
        from PyQt6.QtSvg import QSvgRenderer
        from PyQt6.QtGui import QPainter
        renderer = self.renderer()
        if renderer is None or not renderer.isValid():
            return
        painter = QPainter(self)
        vbox = renderer.viewBox()
        if vbox.isEmpty():
            renderer.render(painter)
        else:
            # Compute centered, aspect-preserving rect
            svg_w, svg_h = vbox.width(), vbox.height()
            wid_w, wid_h = self.width(), self.height()
            if svg_w <= 0 or svg_h <= 0:
                renderer.render(painter)
                return
            scale = min(wid_w / svg_w, wid_h / svg_h)
            rw, rh = svg_w * scale, svg_h * scale
            rx = (wid_w - rw) / 2
            ry = (wid_h - rh) / 2
            from PyQt6.QtCore import QRectF
            renderer.render(painter, QRectF(rx, ry, rw, rh))
        painter.end()


class DotWizard(QMainWindow):
    """Interactive dot layout wizard with editor, preview, and controls."""

    def __init__(self, initial_file: str | None = None):
        super().__init__()
        self.setWindowTitle("GraphvizPy — Dot Layout Wizard")
        self.resize(1300, 750)
        self._current_file: str | None = None
        self._last_svg: str = ""

        self._build_menu()
        self._build_ui()
        self._update_command()

        if initial_file:
            self._load_file(Path(initial_file))
        else:
            self._editor.setPlainText(_DEFAULT_DOT)
            self._run_layout()

    # ── Menu bar ─────────────────────────────────

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

    # ── UI construction ──────────────────────────

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(4, 4, 4, 4)

        # Three-pane splitter
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: DOT source editor
        self._editor = QPlainTextEdit()
        self._editor.setFont(QFont("Consolas", 11))
        self._editor.setPlaceholderText("Enter DOT source here...")
        self._editor.setTabStopDistance(28)
        splitter.addWidget(self._editor)

        # Center: SVG preview (aspect-preserving)
        self._svg_widget = _AspectSvgWidget()
        self._svg_widget.setMinimumWidth(200)
        self._svg_widget.setStyleSheet("background-color: white;")
        splitter.addWidget(self._svg_widget)

        # Right: parameter panel
        param_scroll = QScrollArea()
        param_scroll.setWidgetResizable(True)
        param_scroll.setMinimumWidth(220)
        param_scroll.setMaximumWidth(320)
        param_widget = QWidget()
        param_outer = QVBoxLayout(param_widget)
        param_outer.setContentsMargins(4, 4, 4, 4)

        # -- Graph parameters --
        graph_group = QGroupBox("Graph")
        graph_layout = QFormLayout()
        graph_layout.setContentsMargins(4, 8, 4, 4)

        self._rankdir = QComboBox()
        self._rankdir.addItems(["TB", "BT", "LR", "RL"])
        graph_layout.addRow("rankdir:", self._rankdir)

        self._splines = QComboBox()
        self._splines.addItems(["curved", "ortho", "polyline", "line"])
        graph_layout.addRow("splines:", self._splines)

        self._ordering = QComboBox()
        self._ordering.addItems(["(none)", "out", "in"])
        graph_layout.addRow("ordering:", self._ordering)

        self._ratio = QComboBox()
        self._ratio.addItems(["(none)", "compress", "fill", "auto"])
        graph_layout.addRow("ratio:", self._ratio)

        self._ranksep = QDoubleSpinBox()
        self._ranksep.setRange(0.1, 5.0)
        self._ranksep.setSingleStep(0.1)
        self._ranksep.setValue(0.5)
        graph_layout.addRow("ranksep:", self._ranksep)

        self._nodesep = QDoubleSpinBox()
        self._nodesep.setRange(0.1, 5.0)
        self._nodesep.setSingleStep(0.05)
        self._nodesep.setValue(0.25)
        graph_layout.addRow("nodesep:", self._nodesep)

        self._size = QLineEdit()
        self._size.setPlaceholderText("e.g. 8,10")
        graph_layout.addRow("size:", self._size)

        self._concentrate = QCheckBox()
        graph_layout.addRow("concentrate:", self._concentrate)

        self._compound = QCheckBox()
        graph_layout.addRow("compound:", self._compound)

        self._normalize = QCheckBox()
        graph_layout.addRow("normalize:", self._normalize)

        self._newrank = QCheckBox()
        graph_layout.addRow("newrank:", self._newrank)

        graph_group.setLayout(graph_layout)
        param_outer.addWidget(graph_group)

        # -- Node defaults --
        node_group = QGroupBox("Node Defaults")
        node_layout = QFormLayout()
        node_layout.setContentsMargins(4, 8, 4, 4)

        self._node_shape = QComboBox()
        self._node_shape.addItems([
            "(default)", "ellipse", "box", "circle", "diamond",
            "plaintext", "point", "record", "Mrecord",
            "triangle", "pentagon", "hexagon", "octagon",
            "doublecircle", "doubleoctagon", "house", "invhouse",
        ])
        node_layout.addRow("shape:", self._node_shape)

        self._node_fontsize = QSpinBox()
        self._node_fontsize.setRange(6, 72)
        self._node_fontsize.setValue(14)
        node_layout.addRow("fontsize:", self._node_fontsize)

        self._node_fontname = QComboBox()
        self._node_fontname.setEditable(True)
        self._node_fontname.addItems([
            "(default)", "Times-Roman", "Helvetica", "Courier",
            "Arial", "sans-serif", "serif", "monospace",
        ])
        node_layout.addRow("fontname:", self._node_fontname)

        self._node_style = QComboBox()
        self._node_style.addItems([
            "(none)", "filled", "rounded", "dashed", "dotted", "bold", "invis",
        ])
        node_layout.addRow("style:", self._node_style)

        self._node_color = QLineEdit()
        self._node_color.setPlaceholderText("e.g. red, #FF0000")
        node_layout.addRow("color:", self._node_color)

        self._node_fillcolor = QLineEdit()
        self._node_fillcolor.setPlaceholderText("e.g. lightblue")
        node_layout.addRow("fillcolor:", self._node_fillcolor)

        self._node_width = QDoubleSpinBox()
        self._node_width.setRange(0, 10.0)
        self._node_width.setSingleStep(0.25)
        self._node_width.setValue(0)
        self._node_width.setSpecialValueText("(auto)")
        node_layout.addRow("width:", self._node_width)

        self._node_height = QDoubleSpinBox()
        self._node_height.setRange(0, 10.0)
        self._node_height.setSingleStep(0.25)
        self._node_height.setValue(0)
        self._node_height.setSpecialValueText("(auto)")
        node_layout.addRow("height:", self._node_height)

        node_group.setLayout(node_layout)
        param_outer.addWidget(node_group)

        # -- Edge defaults --
        edge_group = QGroupBox("Edge Defaults")
        edge_layout = QFormLayout()
        edge_layout.setContentsMargins(4, 8, 4, 4)

        self._edge_style = QComboBox()
        self._edge_style.addItems([
            "(none)", "solid", "dashed", "dotted", "bold", "invis",
        ])
        edge_layout.addRow("style:", self._edge_style)

        self._edge_color = QLineEdit()
        self._edge_color.setPlaceholderText("e.g. blue, #0000FF")
        edge_layout.addRow("color:", self._edge_color)

        self._edge_arrowhead = QComboBox()
        self._edge_arrowhead.addItems([
            "(default)", "normal", "inv", "dot", "odot",
            "none", "vee", "crow", "tee",
            "diamond", "odiamond", "box", "obox",
        ])
        edge_layout.addRow("arrowhead:", self._edge_arrowhead)

        self._edge_arrowtail = QComboBox()
        self._edge_arrowtail.addItems([
            "(default)", "normal", "inv", "dot", "odot",
            "none", "vee", "crow", "tee",
            "diamond", "odiamond", "box", "obox",
        ])
        edge_layout.addRow("arrowtail:", self._edge_arrowtail)

        self._edge_dir = QComboBox()
        self._edge_dir.addItems(["(default)", "forward", "back", "both", "none"])
        edge_layout.addRow("dir:", self._edge_dir)

        self._edge_penwidth = QDoubleSpinBox()
        self._edge_penwidth.setRange(0, 10.0)
        self._edge_penwidth.setSingleStep(0.5)
        self._edge_penwidth.setValue(0)
        self._edge_penwidth.setSpecialValueText("(default)")
        edge_layout.addRow("penwidth:", self._edge_penwidth)

        self._edge_fontsize = QSpinBox()
        self._edge_fontsize.setRange(0, 72)
        self._edge_fontsize.setValue(0)
        self._edge_fontsize.setSpecialValueText("(default)")
        edge_layout.addRow("fontsize:", self._edge_fontsize)

        self._edge_minlen = QSpinBox()
        self._edge_minlen.setRange(0, 10)
        self._edge_minlen.setValue(0)
        self._edge_minlen.setSpecialValueText("(default)")
        edge_layout.addRow("minlen:", self._edge_minlen)

        self._edge_weight = QSpinBox()
        self._edge_weight.setRange(0, 100)
        self._edge_weight.setValue(0)
        self._edge_weight.setSpecialValueText("(default)")
        edge_layout.addRow("weight:", self._edge_weight)

        edge_group.setLayout(edge_layout)
        param_outer.addWidget(edge_group)

        param_outer.addStretch(1)
        param_scroll.setWidget(param_widget)
        splitter.addWidget(param_scroll)

        # Set initial splitter proportions (35/40/25)
        splitter.setSizes([420, 480, 300])
        main_layout.addWidget(splitter, stretch=1)

        # Bottom bar: command line + Run button
        bottom = QHBoxLayout()
        bottom.addWidget(QLabel("Command:"))
        self._cmd_line = QLineEdit()
        self._cmd_line.setReadOnly(True)
        self._cmd_line.setFont(QFont("Consolas", 10))
        bottom.addWidget(self._cmd_line, stretch=1)

        run_btn = QPushButton("Run")
        run_btn.setDefault(True)
        run_btn.clicked.connect(self._run_layout)
        bottom.addWidget(run_btn)

        main_layout.addLayout(bottom)

        # Status bar
        self.setStatusBar(QStatusBar())

        # Connect all parameter changes to command update
        for w in (self._rankdir, self._splines, self._ordering, self._ratio,
                  self._node_shape, self._node_fontname, self._node_style,
                  self._edge_style, self._edge_arrowhead, self._edge_arrowtail,
                  self._edge_dir):
            w.currentTextChanged.connect(self._update_command)
        for w in (self._ranksep, self._nodesep, self._node_width, self._node_height,
                  self._edge_penwidth):
            w.valueChanged.connect(self._update_command)
        for w in (self._node_fontsize, self._edge_fontsize, self._edge_minlen,
                  self._edge_weight):
            w.valueChanged.connect(self._update_command)
        for w in (self._size, self._node_color, self._node_fillcolor, self._edge_color):
            w.textChanged.connect(self._update_command)
        for w in (self._concentrate, self._compound, self._normalize, self._newrank):
            w.stateChanged.connect(self._update_command)

    # ── Command line builder ─────────────────────

    def _build_overrides(self) -> tuple[list[str], list[str], list[str]]:
        """Build -G, -N, -E flags from parameter controls.

        Returns (graph_flags, node_flags, edge_flags).
        """
        g_flags: list[str] = []
        n_flags: list[str] = []
        e_flags: list[str] = []

        # Graph
        rd = self._rankdir.currentText()
        if rd != "TB":
            g_flags.append(f"-Grankdir={rd}")
        sp = self._splines.currentText()
        if sp != "curved":
            g_flags.append(f"-Gsplines={sp}")
        od = self._ordering.currentText()
        if od != "(none)":
            g_flags.append(f"-Gordering={od}")
        rt = self._ratio.currentText()
        if rt != "(none)":
            g_flags.append(f"-Gratio={rt}")
        rs = self._ranksep.value()
        if abs(rs - 0.5) > 0.01:
            g_flags.append(f"-Granksep={rs}")
        ns = self._nodesep.value()
        if abs(ns - 0.25) > 0.01:
            g_flags.append(f"-Gnodesep={ns}")
        sz = self._size.text().strip()
        if sz:
            g_flags.append(f"-Gsize={sz}")
        if self._concentrate.isChecked():
            g_flags.append("-Gconcentrate=true")
        if self._compound.isChecked():
            g_flags.append("-Gcompound=true")
        if self._normalize.isChecked():
            g_flags.append("-Gnormalize=true")
        if self._newrank.isChecked():
            g_flags.append("-Gnewrank=true")

        # Node defaults
        ns_val = self._node_shape.currentText()
        if ns_val != "(default)":
            n_flags.append(f"-Nshape={ns_val}")
        nfs = self._node_fontsize.value()
        if nfs != 14:
            n_flags.append(f"-Nfontsize={nfs}")
        nfn = self._node_fontname.currentText()
        if nfn != "(default)":
            n_flags.append(f"-Nfontname={nfn}")
        nst = self._node_style.currentText()
        if nst != "(none)":
            n_flags.append(f"-Nstyle={nst}")
        nc = self._node_color.text().strip()
        if nc:
            n_flags.append(f"-Ncolor={nc}")
        nfc = self._node_fillcolor.text().strip()
        if nfc:
            n_flags.append(f"-Nfillcolor={nfc}")
        nw = self._node_width.value()
        if nw > 0:
            n_flags.append(f"-Nwidth={nw}")
        nh = self._node_height.value()
        if nh > 0:
            n_flags.append(f"-Nheight={nh}")

        # Edge defaults
        est = self._edge_style.currentText()
        if est != "(none)":
            e_flags.append(f"-Estyle={est}")
        ec = self._edge_color.text().strip()
        if ec:
            e_flags.append(f"-Ecolor={ec}")
        eah = self._edge_arrowhead.currentText()
        if eah != "(default)":
            e_flags.append(f"-Earrowhead={eah}")
        eat = self._edge_arrowtail.currentText()
        if eat != "(default)":
            e_flags.append(f"-Earrowtail={eat}")
        ed = self._edge_dir.currentText()
        if ed != "(default)":
            e_flags.append(f"-Edir={ed}")
        epw = self._edge_penwidth.value()
        if epw > 0:
            e_flags.append(f"-Epenwidth={epw}")
        efs = self._edge_fontsize.value()
        if efs > 0:
            e_flags.append(f"-Efontsize={efs}")
        eml = self._edge_minlen.value()
        if eml > 0:
            e_flags.append(f"-Eminlen={eml}")
        ewt = self._edge_weight.value()
        if ewt > 0:
            e_flags.append(f"-Eweight={ewt}")

        return g_flags, n_flags, e_flags

    def _update_command(self):
        fname = self._current_file or "input.gv"
        g_flags, n_flags, e_flags = self._build_overrides()
        parts = ["python", "dot.py", fname, "-Tsvg"] + g_flags + n_flags + e_flags
        self._cmd_line.setText(" ".join(parts))

    # ── Layout execution ─────────────────────────

    def _run_layout(self):
        source = self._editor.toPlainText().strip()
        if not source:
            self.statusBar().showMessage("No DOT source to layout.")
            return

        try:
            graph = read_dot(source)
        except DOTParseError as e:
            self.statusBar().showMessage(f"Parse error: {e}")
            return
        except Exception as e:
            self.statusBar().showMessage(f"Error: {e}")
            return

        g_flags, n_flags, e_flags = self._build_overrides()

        # Apply -G overrides
        for flag in g_flags:
            spec = flag[2:]  # strip "-G"
            if "=" in spec:
                k, v = spec.split("=", 1)
                graph.set_graph_attr(k, v)

        # Apply -N defaults to all nodes
        for flag in n_flags:
            spec = flag[2:]  # strip "-N"
            if "=" in spec:
                k, v = spec.split("=", 1)
                for node in graph.nodes.values():
                    if k not in node.attributes:
                        node.agset(k, v)

        # Apply -E defaults to all edges
        for flag in e_flags:
            spec = flag[2:]  # strip "-E"
            if "=" in spec:
                k, v = spec.split("=", 1)
                for edge in graph.edges.values():
                    if k not in edge.attributes:
                        edge.agset(k, v)

        try:
            result = DotLayout(graph).layout()
        except Exception as e:
            self.statusBar().showMessage(f"Layout error: {e}")
            return

        svg_text = render_svg(result)
        self._last_svg = svg_text

        svg_bytes = QByteArray(svg_text.encode("utf-8"))
        self._svg_widget.load(svg_bytes)
        self._svg_widget.update()

        n = len(result["nodes"])
        e = len(result["edges"])
        c = len(result.get("clusters", []))
        self.statusBar().showMessage(f"Layout complete: {n} nodes, {e} edges, {c} clusters")

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
        self.setWindowTitle(f"GraphvizPy — {path.name}")
        self._update_command()
        self._run_layout()

    def _on_save_source(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save DOT Source", "",
            "DOT Files (*.gv *.dot);;All Files (*)",
        )
        if path:
            Path(path).write_text(self._editor.toPlainText(), encoding="utf-8")
            self._current_file = path
            self.setWindowTitle(f"GraphvizPy — {Path(path).name}")
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


def launch_wizard(initial_file: str | None = None):
    """Launch the dot wizard GUI. Called from dot.py --ui."""
    app = QApplication.instance() or QApplication(sys.argv)
    wizard = DotWizard(initial_file)
    wizard.show()
    sys.exit(app.exec())
