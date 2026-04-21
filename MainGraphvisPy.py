# Version 1.7.12

import sys
import os
import json
import uuid
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QGraphicsView, QGraphicsScene,
    QGraphicsRectItem, QGraphicsEllipseItem, QGraphicsPolygonItem, QGraphicsLineItem,
    QDialog, QVBoxLayout, QFormLayout, QPushButton, QComboBox, QCheckBox, QSpinBox,
    QToolBar, QFileDialog, QMessageBox, QColorDialog, QToolButton, QWidgetAction,
    QDialogButtonBox, QMenu, QGraphicsItemGroup
)
from PyQt6.QtCore import Qt, QPointF, QRectF, QLineF, QEvent
from PyQt6.QtGui import QPen, QBrush, QCursor, QPainter, QPixmap, QIcon, QPolygonF, QColor, QPaintEvent, QAction, QActionGroup


def gen_uuid():
    return uuid.uuid4().hex[:8]


# --- SnapFilter ---
# This filters will intercept mouse release events for items and snap them to grid.
from PyQt6.QtWidgets import QGraphicsObject


class SnapFilter(QGraphicsObject):
    def __init__(self, parentScene):
        super().__init__()
        self._scene = parentScene

    def boundingRect(self):
        return QRectF()  # Not used.

    def paint(self, painter, option, widget):
        pass  # No drawing.

    def sceneEventFilter(self, watched, event):
        if event.type() == QEvent.Type.GraphicsSceneMouseRelease:
            # Snap the watched item if it is a NodeItem or IOConnectorItem.
            if isinstance(watched, (NodeItem, IOConnectorItem)):
                pos = watched.pos()
                snap = self._scene.snap_size
                snapped_pos = QPointF(round(pos.x() / snap) * snap, round(pos.y() / snap) * snap)
                watched.setPos(snapped_pos)
        return False


# --- GraphicsView ---
class GraphicsView(QGraphicsView):
    def __init__(self, scene, parent=None):
        super().__init__(scene, parent)
        self.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

    def wheelEvent(self, event):
        if event.angleDelta().y() > 0:
            zoomFactor = 1.2
        else:
            zoomFactor = 1 / 1.2
        self.scale(zoomFactor, zoomFactor)
        selected_items = self.scene().selectedItems()
        if selected_items:
            self.centerOn(selected_items[0].sceneBoundingRect().center())


# --- ConnectorItem ---
class ConnectorItem(QGraphicsEllipseItem):
    def __init__(self, rect, parent=None, color=Qt.GlobalColor.red):
        super().__init__(rect, parent)
        self.setBrush(QBrush(color))
        self.edges = []
        # Snapping will be handled by the event filters.
        self.setFlags(QGraphicsEllipseItem.GraphicsItemFlag.ItemIsMovable |
                      QGraphicsEllipseItem.GraphicsItemFlag.ItemIsSelectable |
                      QGraphicsEllipseItem.GraphicsItemFlag.ItemSendsScenePositionChanges)
        self.my_id = None

    def add_edge(self, edge):
        self.edges.append(edge)

    def itemChange(self, change, value):
        if change == QGraphicsEllipseItem.GraphicsItemChange.ItemScenePositionHasChanged:
            for edge in self.edges:
                edge.updatePosition()
        return super().itemChange(change, value)


# --- IOConnectorItem ---
class IOConnectorItem(QGraphicsPolygonItem):
    def __init__(self, parent=None, color=Qt.GlobalColor.magenta):
        polygon = QPolygonF([QPointF(0, -8), QPointF(8, 0), QPointF(0, 8), QPointF(-8, 0)])
        super().__init__(polygon, parent)
        self.setBrush(QBrush(color))
        self.setPen(QPen(Qt.GlobalColor.black, 2))
        self.edges = []
        self.setFlags(QGraphicsPolygonItem.GraphicsItemFlag.ItemIsMovable |
                      QGraphicsPolygonItem.GraphicsItemFlag.ItemIsSelectable |
                      QGraphicsPolygonItem.GraphicsItemFlag.ItemSendsScenePositionChanges)
        self.my_id = None

    def add_edge(self, edge):
        self.edges.append(edge)

    def itemChange(self, change, value):
        if change == QGraphicsPolygonItem.GraphicsItemChange.ItemScenePositionHasChanged:
            for edge in self.edges:
                edge.updatePosition()
        return super().itemChange(change, value)


# --- NodeItem ---
class NodeItem(QGraphicsRectItem):
    def __init__(self, rect, parent=None):
        super().__init__(rect, parent)
        self.setFlags(QGraphicsRectItem.GraphicsItemFlag.ItemIsMovable |
                      QGraphicsRectItem.GraphicsItemFlag.ItemIsSelectable)
        self.connectors = []
        self.my_id = None

    def add_connector(self, pos):
        color = self.scene().input_connector_color if self.scene() else Qt.GlobalColor.red
        radius = 5
        connector = ConnectorItem(QRectF(-radius, -radius, radius * 2, radius * 2), self, color=color)
        connector.setPos(pos)
        self.connectors.append(connector)
        # Install the snap filters on the connector.
        self.scene().snap_filter.installSceneEventFilter(connector)
        return connector

    def add_origin_connector(self, pos):
        color = self.scene().output_connector_color if self.scene() else Qt.GlobalColor.blue
        radius = 5
        connector = ConnectorItem(QRectF(-radius, -radius, radius * 2, radius * 2), self, color=color)
        connector.setPos(pos)
        self.connectors.append(connector)
        self.scene().snap_filter.installSceneEventFilter(connector)
        return connector

    def mouseDoubleClickEvent(self, event):
        self.connectorWindow = ConnectorWindow(self)
        self.connectorWindow.show()
        event.accept()


# --- EdgeItem ---
class EdgeItem(QGraphicsLineItem):
    def __init__(self, start, end, start_connector=None, end_connector=None, parent=None):
        super().__init__(parent)
        self.start_connector = start_connector
        self.end_connector = end_connector
        self.fallback_start = start
        self.fallback_end = end
        self.setFlags(QGraphicsLineItem.GraphicsItemFlag.ItemIsSelectable)
        self.setPen(QPen(Qt.GlobalColor.black, 2))
        self.updatePosition()
        if self.start_connector is not None:
            self.start_connector.add_edge(self)
        if self.end_connector is not None:
            self.end_connector.add_edge(self)
        self.my_id = None

    def updatePosition(self):
        if self.start_connector is not None:
            start_point = self.start_connector.scenePos()
        else:
            start_point = self.fallback_start
        if self.end_connector is not None:
            end_point = self.end_connector.scenePos()
        else:
            end_point = self.fallback_end
        self.setLine(start_point.x(), start_point.y(), end_point.x(), end_point.y())


# --- GraphicsScene ---
class GraphicsScene(QGraphicsScene):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.mode = "draw_node"  # "draw_node", "draw_edge", "select"
        self.temp_line = None
        self.edge_start = None
        self.edge_origin_node = None
        self.new_node = None
        self.io_start_connector = None
        self.default_node_fill_color = QColor(Qt.GlobalColor.green)
        self.default_node_outline_color = QColor(Qt.GlobalColor.black)
        self.default_node_outline_width = 2
        self.default_edge_type = "Straight"
        self.input_connector_color = QColor(Qt.GlobalColor.red)
        self.output_connector_color = QColor(Qt.GlobalColor.blue)
        self.snap_enabled = True
        self.snap_size = 10
        # Create a SnapFilter instance.
        self.snap_filter = SnapFilter(self)
        if os.path.exists("GVP_settings.json"):
            try:
                with open("GVP_settings.json", "r") as f:
                    prefs = json.load(f)
                self.default_node_fill_color = QColor(prefs.get("default_node_color", "#00ff00"))
                self.default_node_outline_color = QColor(prefs.get("default_node_outline_color", "#000000"))
                self.default_node_outline_width = prefs.get("default_node_outline_width", 2)
                self.default_edge_type = prefs.get("default_edge_type", "Straight")
                self.input_connector_color = QColor(prefs.get("input_connector_color", "#ff0000"))
                self.output_connector_color = QColor(prefs.get("output_connector_color", "#0000ff"))
                self.snap_enabled = prefs.get("snap_enabled", True)
                self.snap_size = prefs.get("snap_size", 10)
            except Exception as e:
                QMessageBox.warning(None, "Load Preferences", f"Error loading preferences: {str(e)}")

    # We no longer override addItem; instead, we explicitly install the snap filters in NodeItem.add_connector

    def drawBackground(self, painter, rect):
        if self.snap_enabled:
            snap = self.snap_size
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor(200, 200, 200)))
            x = int(rect.left() // snap) * snap
            while x < rect.right():
                y = int(rect.top() // snap) * snap
                while y < rect.bottom():
                    painter.drawEllipse(QPointF(x, y), 1.5, 1.5)
                    y += snap
                x += snap

    def set_mode(self, mode):
        self.mode = mode
        if mode == "draw_node":
            new_cursor = QCursor(Qt.CursorShape.CrossCursor)
        elif mode == "draw_edge":
            new_cursor = QCursor(Qt.CursorShape.PointingHandCursor)
        elif mode == "select":
            new_cursor = QCursor(Qt.CursorShape.ArrowCursor)
        else:
            new_cursor = QCursor(Qt.CursorShape.ArrowCursor)
        for view in self.views():
            view.setCursor(new_cursor)
            if mode == "select":
                view.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
            else:
                view.setDragMode(QGraphicsView.DragMode.NoDrag)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Backspace or event.key() == Qt.Key.Key_Delete:
            for item in self.selectedItems():
                self.removeItem(item)
        else:
            super().keyPressEvent(event)

    def mousePressEvent(self, event):
        if self.mode == "draw_node":
            if event.button() == Qt.MouseButton.LeftButton:
                size = 60
                pos = event.scenePos()
                rect = QRectF(-size / 2, -size / 2, size, size)
                node = NodeItem(rect)
                node.setBrush(QBrush(self.default_node_fill_color))
                node.setPen(QPen(self.default_node_outline_color, self.default_node_outline_width))
                node.setPos(pos)
                if not node.my_id:
                    node.my_id = gen_uuid()
                self.addItem(node)
                self.new_node = node
        elif self.mode == "draw_edge":
            if event.button() == Qt.MouseButton.LeftButton:
                self.edge_start = event.scenePos()
                self.edge_origin_node = None
                for item in self.items(self.edge_start):
                    if isinstance(item, NodeItem):
                        self.edge_origin_node = item
                        break
                if self.edge_origin_node is None:
                    self.io_start_connector = IOConnectorItem(color=QColor(Qt.GlobalColor.darkCyan))
                    self.io_start_connector.setPos(self.edge_start)
                    if not self.io_start_connector.my_id:
                        self.io_start_connector.my_id = gen_uuid()
                    self.addItem(self.io_start_connector)
                else:
                    self.io_start_connector = None
                self.temp_line = QGraphicsLineItem(self.edge_start.x(), self.edge_start.y(),
                                                   self.edge_start.x(), self.edge_start.y())
                self.temp_line.setPen(QPen(Qt.GlobalColor.blue, 2, Qt.PenStyle.DashLine))
                self.addItem(self.temp_line)
        elif self.mode == "select":
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.mode == "draw_node" and self.new_node is not None:
            pos = event.scenePos()
            if self.snap_enabled:
                snap = self.snap_size
                pos = QPointF(round(pos.x() / snap) * snap, round(pos.y() / snap) * snap)
            self.new_node.setPos(pos)
            return
        elif self.mode == "draw_edge" and self.temp_line is not None:
            new_end = event.scenePos()
            self.temp_line.setLine(self.edge_start.x(), self.edge_start.y(), new_end.x(), new_end.y())
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.mode == "draw_node" and self.new_node is not None:
            pos = event.scenePos()
            if self.snap_enabled:
                snap = self.snap_size
                pos = QPointF(round(pos.x() / snap) * snap, round(pos.y() / snap) * snap)
            self.new_node.setPos(pos)
            self.new_node = None
            return
        elif self.mode == "draw_edge" and self.temp_line is not None:
            end_pos = event.scenePos()
            if self.edge_origin_node is not None:
                if not self.edge_origin_node.contains(self.edge_origin_node.mapFromScene(end_pos)):
                    drawn_line = QLineF(self.edge_start, end_pos)
                    polygon = self.edge_origin_node.mapToScene(self.edge_origin_node.rect())
                    intersections = []
                    num_points = polygon.count()
                    for i in range(num_points):
                        p1 = polygon[i]
                        p2 = polygon[(i + 1) % num_points]
                        edge_line = QLineF(p1, p2)
                        result, intersect_point = drawn_line.intersects(edge_line)
                        if result == QLineF.IntersectionType.BoundedIntersection:
                            distance = QLineF(self.edge_start, intersect_point).length()
                            intersections.append((distance, intersect_point))
                    if intersections:
                        intersections.sort(key=lambda x: x[0])
                        intersection_point = intersections[0][1]
                        local_point = self.edge_origin_node.mapFromScene(intersection_point)
                        start_connector = self.edge_origin_node.add_origin_connector(local_point)
                        new_start = intersection_point
                    else:
                        new_start = self.edge_start
                        start_connector = None
                else:
                    new_start = self.edge_start
                    start_connector = None
            else:
                new_start = self.io_start_connector.scenePos()
                start_connector = self.io_start_connector

            end_connector = None
            target_node = None
            for item in self.items(end_pos):
                if isinstance(item, NodeItem):
                    target_node = item
                    break
            if target_node is not None:
                drawn_line_end = QLineF(new_start, end_pos)
                polygon = target_node.mapToScene(target_node.rect())
                intersections = []
                num_points = polygon.count()
                for i in range(num_points):
                    p1 = polygon[i]
                    p2 = polygon[(i + 1) % num_points]
                    edge_line = QLineF(p1, p2)
                    result, intersect_point = drawn_line_end.intersects(edge_line)
                    if result == QLineF.IntersectionType.BoundedIntersection:
                        distance = QLineF(new_start, intersect_point).length()
                        intersections.append((distance, intersect_point))
                if intersections:
                    intersections.sort(key=lambda x: x[0])
                    intersection_point = intersections[0][1]
                    local_point = target_node.mapFromScene(intersection_point)
                    end_connector = target_node.add_connector(local_point)
                    new_end = intersection_point
                else:
                    new_end = end_pos
            else:
                io_connector = IOConnectorItem()
                io_connector.setPos(end_pos)
                if not io_connector.my_id:
                    io_connector.my_id = gen_uuid()
                self.addItem(io_connector)
                end_connector = io_connector
                new_end = end_pos

            edge = EdgeItem(new_start, new_end, start_connector, end_connector)
            if not edge.my_id:
                edge.my_id = gen_uuid()
            self.addItem(edge)
            self.removeItem(self.temp_line)
            self.temp_line = None
            self.edge_start = None
            self.edge_origin_node = None
            self.io_start_connector = None
        elif self.mode == "select":
            super().mouseReleaseEvent(event)
        else:
            super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        super().mouseDoubleClickEvent(event)

    def saveScene(self):
        filename, _ = QFileDialog.getSaveFileName(None, "Save Scene", "", "JSON Files (*.json)")
        if not filename:
            return
        data = {"nodes": [], "io_connectors": [], "edges": []}
        for item in self.items():
            if isinstance(item, NodeItem) and item.parentItem() is None:
                if not item.my_id:
                    item.my_id = gen_uuid()
                node_data = {
                    "id": item.my_id,
                    "pos": [item.pos().x(), item.pos().y()],
                    "size": [item.rect().width(), item.rect().height()],
                    "color": item.brush().color().name(),
                    "connectors": []
                }
                for connector in item.connectors:
                    if not connector.my_id:
                        connector.my_id = gen_uuid()
                    cpos = connector.pos()
                    conn_data = {
                        "id": connector.my_id,
                        "pos": [cpos.x(), cpos.y()],
                        "color": connector.brush().color().name(),
                        "type": "origin" if connector.brush().color() == QColor(Qt.GlobalColor.blue) else "connector"
                    }
                    node_data["connectors"].append(conn_data)
                data["nodes"].append(node_data)
        for item in self.items():
            if isinstance(item, IOConnectorItem) and item.parentItem() is None:
                if not item.my_id:
                    item.my_id = gen_uuid()
                io_data = {
                    "id": item.my_id,
                    "pos": [item.pos().x(), item.pos().y()],
                    "color": item.brush().color().name(),
                    "type": "io"
                }
                data["io_connectors"].append(io_data)
        for item in self.items():
            if isinstance(item, EdgeItem):
                if not item.my_id:
                    item.my_id = gen_uuid()
                edge_data = {
                    "id": item.my_id,
                    "fallback_start": [item.fallback_start.x(), item.fallback_start.y()],
                    "fallback_end": [item.fallback_end.x(), item.fallback_end.y()],
                    "start_connector": item.start_connector.my_id if item.start_connector else None,
                    "end_connector": item.end_connector.my_id if item.end_connector else None
                }
                data["edges"].append(edge_data)
        try:
            with open(filename, "w") as f:
                json.dump(data, f, indent=4)
            QMessageBox.information(None, "Save Scene", "Scene saved successfully.")
        except Exception as e:
            QMessageBox.warning(None, "Save Scene", f"Error saving scene: {str(e)}")

    def loadScene(self):
        filename, _ = QFileDialog.getOpenFileName(None, "Load Scene", "", "JSON Files (*.json)")
        if not filename:
            return
        try:
            with open(filename, "r") as f:
                data = json.load(f)
        except Exception as e:
            QMessageBox.warning(None, "Load Scene", f"Error loading scene: {str(e)}")
            return
        temp_snap = self.snap_enabled
        self.snap_enabled = False
        self.clear()
        node_mapping = {}
        connector_mapping = {}
        io_connector_mapping = {}
        for ndata in data.get("nodes", []):
            pos = QPointF(*ndata["pos"])
            size = ndata["size"]
            rect = QRectF(-size[0] / 2, -size[1] / 2, size[0], size[1])
            node = NodeItem(rect)
            node.setBrush(QBrush(QColor(ndata.get("color", "#00ff00"))))
            node.setPos(pos)
            node.my_id = ndata["id"]
            self.addItem(node)
            node_mapping[node.my_id] = node
            for cdata in ndata.get("connectors", []):
                cpos = QPointF(*cdata["pos"])
                color = QColor(cdata["color"])
                radius = 5
                connector = ConnectorItem(QRectF(-radius, -radius, radius * 2, radius * 2), node, color=color)
                connector.setPos(cpos)
                connector.my_id = cdata["id"]
                node.connectors.append(connector)
                connector_mapping[connector.my_id] = connector
        for iodata in data.get("io_connectors", []):
            pos = QPointF(*iodata["pos"])
            io_connector = IOConnectorItem(color=QColor(iodata["color"]))
            io_connector.setPos(pos)
            io_connector.my_id = iodata["id"]
            self.addItem(io_connector)
            io_connector_mapping[io_connector.my_id] = io_connector
        for edata in data.get("edges", []):
            fs = edata["fallback_start"]
            fe = edata["fallback_end"]
            fallback_start = QPointF(fs[0], fs[1])
            fallback_end = QPointF(fe[0], fe[1])
            start_conn_id = edata.get("start_connector")
            end_conn_id = edata.get("end_connector")
            start_connector = None
            end_connector = None
            if start_conn_id is not None:
                start_connector = connector_mapping.get(start_conn_id)
                if start_connector is None:
                    start_connector = io_connector_mapping.get(start_conn_id)
            if end_conn_id is not None:
                end_connector = connector_mapping.get(end_conn_id)
                if end_connector is None:
                    end_connector = io_connector_mapping.get(end_conn_id)
            edge = EdgeItem(fallback_start, fallback_end, start_connector, end_connector)
            edge.my_id = edata["id"]
            self.addItem(edge)
        self.snap_enabled = temp_snap
        QMessageBox.information(None, "Load Scene", "Scene loaded successfully.")


# --- NodeAppearanceDialog ---
class NodeAppearanceDialog(QDialog):
    def __init__(self, scene, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Node Appearance")
        self.scene = scene
        layout = QFormLayout(self)
        self.fillColorButton = QPushButton()
        self.fillColorButton.setStyleSheet("background-color: " + self.scene.default_node_fill_color.name())
        self.fillColorButton.clicked.connect(self.chooseFillColor)
        layout.addRow("Fill Color:", self.fillColorButton)
        self.outlineColorButton = QPushButton()
        self.outlineColorButton.setStyleSheet("background-color: " + self.scene.default_node_outline_color.name())
        self.outlineColorButton.clicked.connect(self.chooseOutlineColor)
        layout.addRow("Edge Color:", self.outlineColorButton)
        self.outlineWidthSpin = QSpinBox()
        self.outlineWidthSpin.setMinimum(1)
        self.outlineWidthSpin.setMaximum(20)
        self.outlineWidthSpin.setValue(self.scene.default_node_outline_width)
        layout.addRow("Outline Width:", self.outlineWidthSpin)
        self.buttonBox = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttonBox.accepted.connect(self.accept)
        self.buttonBox.rejected.connect(self.reject)
        layout.addRow(self.buttonBox)

    def chooseFillColor(self):
        color = QColorDialog.getColor(self.scene.default_node_fill_color, self, "Choose Fill Color")
        if color.isValid():
            self.scene.default_node_fill_color = color
            self.fillColorButton.setStyleSheet("background-color: " + color.name())

    def chooseOutlineColor(self):
        color = QColorDialog.getColor(self.scene.default_node_outline_color, self, "Choose Edge Color")
        if color.isValid():
            self.scene.default_node_outline_color = color
            self.outlineColorButton.setStyleSheet("background-color: " + color.name())


# --- PreferencesDialog ---
class PreferencesDialog(QDialog):
    def __init__(self, scene, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Preferences")
        self.scene = scene
        self.temp_node_fill_color = self.scene.default_node_fill_color
        self.temp_node_outline_color = self.scene.default_node_outline_color
        self.temp_node_outline_width = self.scene.default_node_outline_width
        self.temp_edge_type = self.scene.default_edge_type
        self.temp_input_connector_color = self.scene.input_connector_color
        self.temp_output_connector_color = self.scene.output_connector_color
        self.temp_snap_enabled = self.scene.snap_enabled
        self.temp_snap_size = self.scene.snap_size

        layout = QFormLayout(self)
        self.nodeColorButton = QPushButton()
        self.nodeColorButton.setStyleSheet("background-color: " + self.temp_node_fill_color.name())
        self.nodeColorButton.clicked.connect(self.chooseNodeColor)
        layout.addRow("Default Node Fill Color:", self.nodeColorButton)
        self.nodeEdgeColorButton = QPushButton()
        self.nodeEdgeColorButton.setStyleSheet("background-color: " + self.temp_node_outline_color.name())
        self.nodeEdgeColorButton.clicked.connect(self.chooseNodeEdgeColor)
        layout.addRow("Default Node Edge Color:", self.nodeEdgeColorButton)
        self.outlineWidthSpin = QSpinBox()
        self.outlineWidthSpin.setMinimum(1)
        self.outlineWidthSpin.setMaximum(20)
        self.outlineWidthSpin.setValue(self.temp_node_outline_width)
        layout.addRow("Default Node Outline Width:", self.outlineWidthSpin)
        self.edgeTypeCombo = QComboBox()
        self.edgeTypeCombo.addItems(["Straight", "Curved", "Rectilinear"])
        self.edgeTypeCombo.setCurrentText(self.temp_edge_type)
        layout.addRow("Default Edge Type:", self.edgeTypeCombo)
        self.inputConnectorButton = QPushButton()
        self.inputConnectorButton.setStyleSheet("background-color: " + self.temp_input_connector_color.name())
        self.inputConnectorButton.clicked.connect(self.chooseInputConnectorColor)
        layout.addRow("Input Connector Color:", self.inputConnectorButton)
        self.outputConnectorButton = QPushButton()
        self.outputConnectorButton.setStyleSheet("background-color: " + self.temp_output_connector_color.name())
        self.outputConnectorButton.clicked.connect(self.chooseOutputConnectorColor)
        layout.addRow("Output Connector Color:", self.outputConnectorButton)
        self.snapCheckBox = QCheckBox("Enable Snap")
        self.snapCheckBox.setChecked(self.temp_snap_enabled)
        layout.addRow("Snap Setting:", self.snapCheckBox)
        self.snapSizeSpin = QSpinBox()
        self.snapSizeSpin.setMinimum(1)
        self.snapSizeSpin.setMaximum(100)
        self.snapSizeSpin.setValue(self.temp_snap_size)
        layout.addRow("Snap Size:", self.snapSizeSpin)
        self.buttonBox = QDialogButtonBox()
        saveButton = self.buttonBox.addButton("Save", QDialogButtonBox.ButtonRole.ActionRole)
        okButton = self.buttonBox.addButton(QDialogButtonBox.StandardButton.Ok)
        cancelButton = self.buttonBox.addButton(QDialogButtonBox.StandardButton.Cancel)
        saveButton.clicked.connect(self.saveToFile)
        okButton.clicked.connect(self.accept)
        cancelButton.clicked.connect(self.reject)
        layout.addRow(self.buttonBox)

    def chooseNodeColor(self):
        color = QColorDialog.getColor(self.temp_node_fill_color, self, "Choose Default Node Fill Color")
        if color.isValid():
            self.temp_node_fill_color = color
            self.nodeColorButton.setStyleSheet("background-color: " + color.name())

    def chooseNodeEdgeColor(self):
        color = QColorDialog.getColor(self.temp_node_outline_color, self, "Choose Default Node Edge Color")
        if color.isValid():
            self.temp_node_outline_color = color
            self.nodeEdgeColorButton.setStyleSheet("background-color: " + color.name())

    def chooseInputConnectorColor(self):
        color = QColorDialog.getColor(self.temp_input_connector_color, self, "Choose Input Connector Color")
        if color.isValid():
            self.temp_input_connector_color = color
            self.inputConnectorButton.setStyleSheet("background-color: " + color.name())

    def chooseOutputConnectorColor(self):
        color = QColorDialog.getColor(self.temp_output_connector_color, self, "Choose Output Connector Color")
        if color.isValid():
            self.temp_output_connector_color = color
            self.outputConnectorButton.setStyleSheet("background-color: " + color.name())

    def accept(self):
        self.temp_node_outline_width = self.outlineWidthSpin.value()
        self.temp_edge_type = self.edgeTypeCombo.currentText()
        self.temp_snap_enabled = self.snapCheckBox.isChecked()
        self.temp_snap_size = self.snapSizeSpin.value()
        self.scene.default_node_fill_color = self.temp_node_fill_color
        self.scene.default_node_outline_color = self.temp_node_outline_color
        self.scene.default_node_outline_width = self.temp_node_outline_width
        self.scene.default_edge_type = self.temp_edge_type
        self.scene.input_connector_color = self.temp_input_connector_color
        self.scene.output_connector_color = self.temp_output_connector_color
        self.scene.snap_enabled = self.temp_snap_enabled
        self.scene.snap_size = self.temp_snap_size
        super().accept()

    def saveToFile(self):
        self.temp_node_outline_width = self.outlineWidthSpin.value()
        self.temp_edge_type = self.edgeTypeCombo.currentText()
        self.temp_snap_enabled = self.snapCheckBox.isChecked()
        self.temp_snap_size = self.snapSizeSpin.value()
        self.scene.default_node_fill_color = self.temp_node_fill_color
        self.scene.default_node_outline_color = self.temp_node_outline_color
        self.scene.default_node_outline_width = self.temp_node_outline_width
        self.scene.default_edge_type = self.temp_edge_type
        self.scene.input_connector_color = self.temp_input_connector_color
        self.scene.output_connector_color = self.temp_output_connector_color
        self.scene.snap_enabled = self.temp_snap_enabled
        self.scene.snap_size = self.temp_snap_size
        prefs = {
            "default_node_color": self.scene.default_node_fill_color.name(),
            "default_node_outline_color": self.scene.default_node_outline_color.name(),
            "default_node_outline_width": self.scene.default_node_outline_width,
            "default_edge_type": self.scene.default_edge_type,
            "input_connector_color": self.scene.input_connector_color.name(),
            "output_connector_color": self.scene.output_connector_color.name(),
            "snap_enabled": self.scene.snap_enabled,
            "snap_size": self.scene.snap_size
        }
        try:
            with open("GVP_settings.json", "w") as f:
                json.dump(prefs, f, indent=4)
            QMessageBox.information(self, "Preferences", "Preferences saved to GVP_settings.json")
        except Exception as e:
            QMessageBox.warning(self, "Preferences", f"Error saving preferences: {str(e)}")


# --- ConnectorWindow ---
class ConnectorWindow(QDialog):
    def __init__(self, node, parent=None):
        super().__init__(parent)
        self.node = node
        self.setWindowTitle("Connector Window")
        self.resize(300, 300)
        layout = QVBoxLayout(self)
        self.view = QGraphicsView()
        layout.addWidget(self.view)
        self.scene = QGraphicsScene()
        self.view.setScene(self.scene)
        self.populate_scene()

    def populate_scene(self):
        node_rect = self.node.rect()
        background = QGraphicsRectItem(node_rect)
        background.setPen(QPen(Qt.GlobalColor.black, 1))
        self.scene.addItem(background)
        for connector in self.node.connectors:
            new_connector = QGraphicsEllipseItem(connector.rect())
            new_connector.setBrush(connector.brush())
            new_connector.setPos(connector.pos())
            self.scene.addItem(new_connector)

    def mouseDoubleClickEvent(self, event):
        pos = event.pos()
        scene_pos = self.view.mapToScene(pos)
        if not self.scene.items(scene_pos):
            self.close()
        super().mouseDoubleClickEvent(event)


# --- MainWindow ---
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("GraphVisPy Layout")
        self.resize(800, 600)
        self.scene = GraphicsScene()
        self.view = GraphicsView(self.scene)
        self.setCentralWidget(self.view)
        self.create_menu()
        self.create_toolbar()
        self.updateNodeToolIcon()

    def create_menu(self):
        fileMenu = self.menuBar().addMenu("File")
        loadAction = QAction("Load", self)
        loadAction.triggered.connect(self.scene.loadScene)
        saveAction = QAction("Save", self)
        saveAction.triggered.connect(self.scene.saveScene)
        fileMenu.addAction(loadAction)
        fileMenu.addAction(saveAction)

        settingsMenu = self.menuBar().addMenu("Settings")
        prefAction = QAction("Preferences", self)
        prefAction.triggered.connect(self.openPreferences)
        settingsMenu.addAction(prefAction)

    def openPreferences(self):
        dialog = PreferencesDialog(self.scene, self)
        if dialog.exec():
            self.updateNodeToolIcon()

    def openNodeAppearanceDialog(self):
        dialog = NodeAppearanceDialog(self.scene, self)
        if dialog.exec():
            self.updateNodeToolIcon()

    def updateNodeToolIcon(self):
        icon = self.buildNodeIcon()
        self.node_action.setIcon(icon)

    def buildNodeIcon(self):
        node_pixmap = QPixmap(32, 32)
        node_pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(node_pixmap)
        painter.setPen(QPen(self.scene.default_node_outline_color, self.scene.default_node_outline_width))
        painter.setBrush(QBrush(self.scene.default_node_fill_color))
        painter.drawRect(4, 4, 24, 24)
        painter.end()
        return QIcon(node_pixmap)

    def buildEdgeIcon(self):
        edge_pixmap = QPixmap(32, 32)
        edge_pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(edge_pixmap)
        painter.setPen(QPen(Qt.GlobalColor.black, 2))
        painter.drawLine(4, 28, 28, 4)
        painter.end()
        return QIcon(edge_pixmap)

    def buildSelectIcon(self):
        select_pixmap = QPixmap(32, 32)
        select_pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(select_pixmap)
        painter.setPen(QPen(Qt.GlobalColor.black, 2))
        arrow_points = [QPointF(8, 16), QPointF(24, 8), QPointF(24, 24)]
        painter.drawPolygon(QPolygonF(arrow_points))
        painter.end()
        return QIcon(select_pixmap)

    def create_toolbar(self):
        toolbar = QToolBar("Tools")
        self.addToolBar(Qt.ToolBarArea.LeftToolBarArea, toolbar)
        self.node_action = QAction(self.buildNodeIcon(), "Draw Node", self)
        self.node_action.setCheckable(True)
        self.node_action.triggered.connect(lambda: self.scene.set_mode("draw_node"))
        self.edge_action = QAction(self.buildEdgeIcon(), "Draw Edge", self)
        self.edge_action.setCheckable(True)
        self.edge_action.triggered.connect(lambda: self.scene.set_mode("draw_edge"))
        self.select_action = QAction(self.buildSelectIcon(), "Select", self)
        self.select_action.setCheckable(True)
        self.select_action.triggered.connect(lambda: self.scene.set_mode("select"))
        toolActionGroup = QActionGroup(self)
        toolActionGroup.setExclusive(True)
        toolActionGroup.addAction(self.node_action)
        toolActionGroup.addAction(self.edge_action)
        toolActionGroup.addAction(self.select_action)
        toolbar.addAction(self.node_action)
        toolbar.addAction(self.edge_action)
        toolbar.addAction(self.select_action)
        node_button = toolbar.widgetForAction(self.node_action)
        if node_button:
            node_button.installEventFilter(self)
        self.scene.set_mode("draw_node")

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.MouseButtonDblClick:
            self.openNodeAppearanceDialog()
            return True
        return super().eventFilter(obj, event)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
