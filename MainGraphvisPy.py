import sys
import os
import json
import uuid
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QGraphicsView, QGraphicsScene,
    QGraphicsRectItem, QGraphicsEllipseItem, QGraphicsPolygonItem, QGraphicsLineItem,
    QDialog, QVBoxLayout, QFormLayout, QPushButton, QComboBox, QCheckBox, QSpinBox,
    QToolBar, QAction, QActionGroup, QFileDialog, QMessageBox, QColorDialog
)
from PyQt5.QtCore import Qt, QPointF, QRectF, QLineF
from PyQt5.QtGui import QPen, QBrush, QCursor, QPainter, QPixmap, QIcon, QPolygonF, QColor


def gen_uuid():
    return uuid.uuid4().hex[:8]


# --- GraphicsView subclass for zooming and centering ---
class GraphicsView(QGraphicsView):
    def wheelEvent(self, event):
        if event.angleDelta().y() > 0:
            zoomFactor = 1.2
        else:
            zoomFactor = 1 / 1.2
        self.scale(zoomFactor, zoomFactor)
        selected_items = self.scene().selectedItems()
        if selected_items:
            self.centerOn(selected_items[0].sceneBoundingRect().center())


# --- ConnectorItem: Child connectors that stick to parent's edges ---
class ConnectorItem(QGraphicsEllipseItem):
    def __init__(self, rect, parent=None, color=Qt.red):
        super().__init__(rect, parent)
        self.setBrush(QBrush(color))
        self.edges = []
        self.setFlags(
            QGraphicsEllipseItem.ItemIsMovable |
            QGraphicsEllipseItem.ItemIsSelectable |
            QGraphicsEllipseItem.ItemSendsScenePositionChanges
        )
        self.my_id = None

    def add_edge(self, edge):
        self.edges.append(edge)

    def itemChange(self, change, value):
        if change == QGraphicsEllipseItem.ItemPositionChange:
            new_pos = value  # in parent's coordinates
            parent = self.parentItem()
            if parent:
                rect = parent.boundingRect()
                x, y = new_pos.x(), new_pos.y()
                left, right, top, bottom = rect.left(), rect.right(), rect.top(), rect.bottom()
                d_left = abs(x - left)
                d_right = abs(right - x)
                d_top = abs(y - top)
                d_bottom = abs(bottom - y)
                d_min = min(d_left, d_right, d_top, d_bottom)
                if d_min == d_left:
                    x = left
                elif d_min == d_right:
                    x = right
                elif d_min == d_top:
                    y = top
                elif d_min == d_bottom:
                    y = bottom
                new_pos = QPointF(x, y)
            return new_pos
        if change == QGraphicsEllipseItem.ItemScenePositionHasChanged:
            for edge in self.edges:
                edge.updatePosition()
        return super().itemChange(change, value)


# --- IOConnectorItem: Top-level connector (diamond) ---
class IOConnectorItem(QGraphicsPolygonItem):
    def __init__(self, parent=None, color=Qt.magenta):
        polygon = QPolygonF([QPointF(0, -8), QPointF(8, 0), QPointF(0, 8), QPointF(-8, 0)])
        super().__init__(polygon, parent)
        self.setBrush(QBrush(color))
        self.setPen(QPen(Qt.black, 2))
        self.edges = []
        self.setFlags(
            QGraphicsPolygonItem.ItemIsMovable |
            QGraphicsPolygonItem.ItemIsSelectable |
            QGraphicsPolygonItem.ItemSendsScenePositionChanges
        )
        self.my_id = None

    def add_edge(self, edge):
        self.edges.append(edge)

    def itemChange(self, change, value):
        # IO connectors move freely (no snapping on their own movement)
        if change == QGraphicsPolygonItem.ItemScenePositionHasChanged:
            for edge in self.edges:
                edge.updatePosition()
        return super().itemChange(change, value)


# --- NodeItem: Top-level node; snapping handled via itemChange() ---
class NodeItem(QGraphicsRectItem):
    def __init__(self, rect, parent=None):
        super().__init__(rect, parent)
        # Enable move notifications.
        self.setFlags(QGraphicsRectItem.ItemIsMovable |
                      QGraphicsRectItem.ItemIsSelectable |
                      QGraphicsRectItem.ItemSendsScenePositionChanges)
        self.connectors = []
        self.my_id = None

    def add_connector(self, pos):
        color = self.scene().input_connector_color if self.scene() else Qt.red
        radius = 5
        connector = ConnectorItem(QRectF(-radius, -radius, radius * 2, radius * 2), self, color=color)
        connector.setPos(pos)
        self.connectors.append(connector)
        return connector

    def add_origin_connector(self, pos):
        color = self.scene().output_connector_color if self.scene() else Qt.blue
        radius = 5
        connector = ConnectorItem(QRectF(-radius, -radius, radius * 2, radius * 2), self, color=color)
        connector.setPos(pos)
        self.connectors.append(connector)
        return connector

    def itemChange(self, change, value):
        # Snap node to grid when moved if snap_enabled is True.
        if change == QGraphicsRectItem.ItemPositionChange and self.parentItem() is None and self.scene() and self.scene().snap_enabled:
            pos = value
            snap = self.scene().snap_size
            pos = QPointF(round(pos.x() / snap) * snap, round(pos.y() / snap) * snap)
            return pos
        return super().itemChange(change, value)

    def mouseDoubleClickEvent(self, event):
        self.connectorWindow = ConnectorWindow(self)
        self.connectorWindow.show()
        event.accept()


# --- EdgeItem: Represents a graph edge ---
class EdgeItem(QGraphicsLineItem):
    def __init__(self, start, end, start_connector=None, end_connector=None, parent=None):
        super().__init__(parent)
        self.start_connector = start_connector
        self.end_connector = end_connector
        self.fallback_start = start
        self.fallback_end = end
        self.setFlags(QGraphicsLineItem.ItemIsSelectable)
        self.setPen(QPen(Qt.black, 2))
        self.updatePosition()
        if self.start_connector is not None:
            self.start_connector.add_edge(self)
        if self.end_connector is not None:
            self.end_connector.add_edge(self)
        self.my_id = None

    def updatePosition(self):
        if self.start_connector is not None:
            if isinstance(self.start_connector, IOConnectorItem):
                start_point = self.start_connector.scenePos() + QPointF(8, 0)
            else:
                start_point = self.start_connector.scenePos()
        else:
            start_point = self.fallback_start
        if self.end_connector is not None:
            if isinstance(self.end_connector, IOConnectorItem):
                end_point = self.end_connector.scenePos() + QPointF(-8, 0)
            else:
                end_point = self.end_connector.scenePos()
        else:
            end_point = self.fallback_end
        self.setLine(start_point.x(), start_point.y(), end_point.x(), end_point.y())


# --- PreferencesDialog: Allows user to set and save preferences ---
class PreferencesDialog(QDialog):
    def __init__(self, scene, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Preferences")
        self.scene = scene
        layout = QFormLayout(self)
        self.nodeColorButton = QPushButton()
        self.nodeColorButton.setStyleSheet("background-color: " + self.scene.default_node_color.name())
        self.nodeColorButton.clicked.connect(self.chooseNodeColor)
        layout.addRow("Default Node Color:", self.nodeColorButton)
        self.edgeTypeCombo = QComboBox()
        self.edgeTypeCombo.addItems(["Straight", "Curved", "Rectilinear"])
        self.edgeTypeCombo.setCurrentText(self.scene.default_edge_type)
        layout.addRow("Default Edge Type:", self.edgeTypeCombo)
        self.inputConnectorButton = QPushButton()
        self.inputConnectorButton.setStyleSheet("background-color: " + self.scene.input_connector_color.name())
        self.inputConnectorButton.clicked.connect(self.chooseInputConnectorColor)
        layout.addRow("Input Connector Color:", self.inputConnectorButton)
        self.outputConnectorButton = QPushButton()
        self.outputConnectorButton.setStyleSheet("background-color: " + self.scene.output_connector_color.name())
        self.outputConnectorButton.clicked.connect(self.chooseOutputConnectorColor)
        layout.addRow("Output Connector Color:", self.outputConnectorButton)
        self.snapCheckBox = QCheckBox("Enable Snap")
        self.snapCheckBox.setChecked(self.scene.snap_enabled)
        layout.addRow("Snap Setting:", self.snapCheckBox)
        self.snapSizeSpin = QSpinBox()
        self.snapSizeSpin.setMinimum(1)
        self.snapSizeSpin.setMaximum(100)
        self.snapSizeSpin.setValue(self.scene.snap_size)
        layout.addRow("Snap Size:", self.snapSizeSpin)
        self.saveFileButton = QPushButton("Save to File")
        self.saveFileButton.clicked.connect(self.saveToFile)
        layout.addRow(self.saveFileButton)
        self.okButton = QPushButton("OK")
        self.cancelButton = QPushButton("Cancel")
        self.okButton.clicked.connect(self.accept)
        self.cancelButton.clicked.connect(self.reject)
        layout.addRow(self.okButton, self.cancelButton)

    def chooseNodeColor(self):
        color = QColorDialog.getColor(self.scene.default_node_color, self, "Choose Default Node Color")
        if color.isValid():
            self.scene.default_node_color = color
            self.nodeColorButton.setStyleSheet("background-color: " + color.name())

    def chooseInputConnectorColor(self):
        color = QColorDialog.getColor(self.scene.input_connector_color, self, "Choose Input Connector Color")
        if color.isValid():
            self.scene.input_connector_color = color
            self.inputConnectorButton.setStyleSheet("background-color: " + color.name())

    def chooseOutputConnectorColor(self):
        color = QColorDialog.getColor(self.scene.output_connector_color, self, "Choose Output Connector Color")
        if color.isValid():
            self.scene.output_connector_color = color
            self.outputConnectorButton.setStyleSheet("background-color: " + color.name())

    def saveToFile(self):
        prefs = {
            "default_node_color": self.scene.default_node_color.name(),
            "default_edge_type": self.edgeTypeCombo.currentText(),
            "input_connector_color": self.scene.input_connector_color.name(),
            "output_connector_color": self.scene.output_connector_color.name(),
            "snap_enabled": self.snapCheckBox.isChecked(),
            "snap_size": self.snapSizeSpin.value()
        }
        try:
            with open("GVP_settings.json", "w") as f:
                json.dump(prefs, f, indent=4)
            QMessageBox.information(self, "Preferences", "Preferences saved to GVP_settings.json")
        except Exception as e:
            QMessageBox.warning(self, "Preferences", f"Error saving preferences: {str(e)}")


# --- ConnectorWindow: Shows a preview of a node's connectors ---
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
        background.setPen(QPen(Qt.black, 1))
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


# --- GraphicsScene: Holds preferences, draws grid, snapping, key deletion, and save/load methods ---
class GraphicsScene(QGraphicsScene):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.mode = "draw_node"  # "draw_node", "draw_edge", "select"
        self.temp_line = None
        self.edge_start = None
        self.edge_origin_node = None
        self.new_node = None
        self.io_start_connector = None
        self.default_node_color = QColor(Qt.green)
        self.default_edge_type = "Straight"
        self.input_connector_color = QColor(Qt.red)
        self.output_connector_color = QColor(Qt.blue)
        self.snap_enabled = True
        self.snap_size = 10
        if os.path.exists("GVP_settings.json"):
            try:
                with open("GVP_settings.json", "r") as f:
                    prefs = json.load(f)
                self.default_node_color = QColor(prefs.get("default_node_color", "#00ff00"))
                self.default_edge_type = prefs.get("default_edge_type", "Straight")
                self.input_connector_color = QColor(prefs.get("input_connector_color", "#ff0000"))
                self.output_connector_color = QColor(prefs.get("output_connector_color", "#0000ff"))
                self.snap_enabled = prefs.get("snap_enabled", True)
                self.snap_size = prefs.get("snap_size", 10)
            except Exception as e:
                QMessageBox.warning(None, "Load Preferences", f"Error loading preferences: {str(e)}")

    def drawBackground(self, painter, rect):
        if self.snap_enabled:
            snap = self.snap_size
            painter.setPen(Qt.NoPen)
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
            new_cursor = QCursor(Qt.CrossCursor)
        elif mode == "draw_edge":
            new_cursor = QCursor(Qt.PointingHandCursor)
        elif mode == "select":
            new_cursor = QCursor(Qt.ArrowCursor)
        else:
            new_cursor = QCursor(Qt.ArrowCursor)
        for view in self.views():
            view.setCursor(new_cursor)

    def keyPressEvent(self, event):
        # Delete selected items on Backspace press.
        if event.key() == Qt.Key_Backspace:
            for item in self.selectedItems():
                self.removeItem(item)
        else:
            super().keyPressEvent(event)

    def mousePressEvent(self, event):
        if self.mode == "draw_node":
            if event.button() == Qt.LeftButton:
                size = 60
                pos = event.scenePos()
                rect = QRectF(-size / 2, -size / 2, size, size)
                node = NodeItem(rect)
                node.setBrush(QBrush(self.default_node_color))
                node.setPos(pos)
                if not node.my_id:
                    node.my_id = gen_uuid()
                self.addItem(node)
                self.new_node = node
        elif self.mode == "draw_edge":
            if event.button() == Qt.LeftButton:
                self.edge_start = event.scenePos()
                self.edge_origin_node = None
                for item in self.items(self.edge_start):
                    if isinstance(item, NodeItem):
                        self.edge_origin_node = item
                        break
                if self.edge_origin_node is None:
                    self.io_start_connector = IOConnectorItem(color=QColor(Qt.darkCyan))
                    self.io_start_connector.setPos(self.edge_start)
                    if not self.io_start_connector.my_id:
                        self.io_start_connector.my_id = gen_uuid()
                    self.addItem(self.io_start_connector)
                else:
                    self.io_start_connector = None
                self.temp_line = QGraphicsLineItem(self.edge_start.x(), self.edge_start.y(),
                                                   self.edge_start.x(), self.edge_start.y())
                self.temp_line.setPen(QPen(Qt.blue, 2, Qt.DashLine))
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
                        intersect_point = QPointF()
                        result = drawn_line.intersect(edge_line, intersect_point)
                        if result == QLineF.BoundedIntersection:
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
                    intersect_point = QPointF()
                    result = drawn_line_end.intersect(edge_line, intersect_point)
                    if result == QLineF.BoundedIntersection:
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

    def keyPressEvent(self, event):
        # Delete selected items when Backspace is pressed.
        if event.key() == Qt.Key_Backspace:
            for item in self.selectedItems():
                self.removeItem(item)
        else:
            super().keyPressEvent(event)

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
                        "type": "origin" if connector.brush().color() == QColor(Qt.blue) else "connector"
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
        if dialog.exec_():
            pass

    def create_toolbar(self):
        toolbar = QToolBar("Tools")
        self.addToolBar(Qt.LeftToolBarArea, toolbar)
        node_pixmap = QPixmap(32, 32)
        node_pixmap.fill(Qt.transparent)
        painter = QPainter(node_pixmap)
        painter.setPen(QPen(Qt.black, 2))
        painter.setBrush(QBrush(self.scene.default_node_color))
        painter.drawRect(4, 4, 24, 24)
        painter.end()
        node_icon = QIcon(node_pixmap)
        edge_pixmap = QPixmap(32, 32)
        edge_pixmap.fill(Qt.transparent)
        painter = QPainter(edge_pixmap)
        painter.setPen(QPen(Qt.black, 2))
        painter.drawLine(4, 4, 28, 28)
        painter.end()
        edge_icon = QIcon(edge_pixmap)
        select_pixmap = QPixmap(32, 32)
        select_pixmap.fill(Qt.transparent)
        painter = QPainter(select_pixmap)
        painter.setPen(QPen(Qt.black, 2))
        arrow_points = [QPointF(8, 16), QPointF(24, 8), QPointF(24, 24)]
        painter.drawPolygon(QPolygonF(arrow_points))
        painter.end()
        select_icon = QIcon(select_pixmap)
        action_group = QActionGroup(self)
        action_group.setExclusive(True)
        node_action = QAction(node_icon, "Draw Node", self)
        node_action.setCheckable(True)
        node_action.setChecked(True)
        node_action.triggered.connect(lambda: self.scene.set_mode("draw_node"))
        toolbar.addAction(node_action)
        action_group.addAction(node_action)
        edge_action = QAction(edge_icon, "Draw Edge", self)
        edge_action.setCheckable(True)
        edge_action.triggered.connect(lambda: self.scene.set_mode("draw_edge"))
        toolbar.addAction(edge_action)
        action_group.addAction(edge_action)
        select_action = QAction(select_icon, "Select", self)
        select_action.setCheckable(True)
        select_action.triggered.connect(lambda: self.scene.set_mode("select"))
        toolbar.addAction(select_action)
        action_group.addAction(select_action)
        self.scene.set_mode("draw_node")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())
