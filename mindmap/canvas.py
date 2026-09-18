"""Widget de canvas que dibuja y gestiona el mapa mental interactivo."""

import copy
import itertools
import math
import os
import shutil
import subprocess
import tkinter as tk
from tkinter import colorchooser, simpledialog
from typing import Callable, Dict, Optional, Tuple

from .models import Connection, Node
from .text_import import OutlineNode, parse_outline

PALETTES = {
    "Vivo": {
        "colors": ["#00c2a8", "#2f8fef", "#3ddc84", "#f5c316", "#f4287a", "#7c5cc4"],
        "accent": "#5b2bd6",
    },
    "Océano": {
        "colors": ["#0077b6", "#00b4d8", "#48cae4", "#023e8a", "#0096c7", "#03045e"],
        "accent": "#023047",
    },
    "Atardecer": {
        "colors": ["#ff595e", "#ff924c", "#ffca3a", "#e07a5f", "#f4a261", "#e63946"],
        "accent": "#9d0208",
    },
    "Pastel": {
        "colors": ["#8ecae6", "#ffb4a2", "#b8e0a8", "#ffd166", "#cdb4db", "#a2d2ff"],
        "accent": "#6d6875",
    },
    "Clásico": {
        "colors": ["#4a90d9", "#e0673a", "#3aab6b", "#c94f9e", "#e0a83a", "#7c5cc4"],
        "accent": "#2b3a4a",
    },
}
DEFAULT_PALETTE = "Vivo"

SELECT_OUTLINE = "#ffd23f"


def _rect_clearance(width, height, ux, uy):
    """Distancia del centro al borde de un rectángulo width x height en la dirección (ux, uy)."""
    tx = (width / 2) / abs(ux) if abs(ux) > 1e-6 else float("inf")
    ty = (height / 2) / abs(uy) if abs(uy) > 1e-6 else float("inf")
    return min(tx, ty)


def _quad_bezier(p0, p1, p2, t):
    x = (1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t ** 2 * p2[0]
    y = (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t ** 2 * p2[1]
    return x, y


def _tapered_branch_points(x1, y1, x2, y2, base_width, tip_width, curve=0.18, samples=18):
    """Puntos de un polígono suave que va de grueso (origen) a fino (destino),
    como una rama, siguiendo una curva cuadrática de Bézier en vez de una recta."""
    dist = math.hypot(x2 - x1, y2 - y1) or 1
    mx, my = (x1 + x2) / 2, (y1 + y2) / 2
    px, py = -(y2 - y1) / dist, (x2 - x1) / dist
    offset = dist * curve
    cx, cy = mx + px * offset, my + py * offset

    top_pts, bottom_pts = [], []
    for i in range(samples + 1):
        t = i / samples
        bx, by = _quad_bezier((x1, y1), (cx, cy), (x2, y2), t)
        t2 = min(t + 0.02, 1.0)
        nx, ny = _quad_bezier((x1, y1), (cx, cy), (x2, y2), t2)
        tdx, tdy = nx - bx, ny - by
        tlen = math.hypot(tdx, tdy) or 1
        tpx, tpy = -tdy / tlen, tdx / tlen
        w = (base_width + (tip_width - base_width) * t) / 2
        top_pts.append((bx + tpx * w, by + tpy * w))
        bottom_pts.append((bx - tpx * w, by - tpy * w))

    flat = []
    for px_, py_ in top_pts + bottom_pts[::-1]:
        flat.extend([px_, py_])
    return flat


class MindMapCanvas(tk.Frame):
    """Canvas interactivo: arrastra nodos, crea conexiones y cambia sus colores."""

    def __init__(self, master, on_status: Optional[Callable[[str], None]] = None,
                 on_connect_mode_change: Optional[Callable[[bool], None]] = None, **kwargs):
        super().__init__(master, **kwargs)
        self.on_status = on_status or (lambda text: None)
        self.on_connect_mode_change = on_connect_mode_change or (lambda active: None)

        self.canvas = tk.Canvas(self, bg="#f4f6f8", highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)

        self.nodes: Dict[int, Node] = {}
        self.connections: Dict[int, Connection] = {}
        self.node_items: Dict[int, Dict[str, int]] = {}
        self.conn_items: Dict[int, int] = {}

        self._node_id_seq = itertools.count(1)
        self._conn_id_seq = itertools.count(1)
        self.palette_name = DEFAULT_PALETTE
        self._color_cycle = itertools.cycle(PALETTES[self.palette_name]["colors"])

        self.selected: Optional[Tuple[str, int]] = None
        self._drag = {"mode": None, "node_id": None, "last_x": 0, "last_y": 0}
        self._connect_temp_line = None
        self._connect_source: Optional[int] = None
        self.connect_mode = False
        self._connect_first_node: Optional[int] = None

        self.undo_stack: list = []
        self.redo_stack: list = []
        self._suspend_undo = False
        self._max_undo = 50

        self.canvas.bind("<ButtonPress-1>", self._on_canvas_press)
        self.canvas.bind("<B1-Motion>", self._on_canvas_motion)
        self.canvas.bind("<ButtonRelease-1>", self._on_canvas_release)
        self.canvas.bind("<Double-Button-1>", self._on_canvas_double_click)
        self.canvas.bind("<Button-3>", self._on_canvas_right_click)
        self.canvas.bind("<Delete>", lambda e: self.delete_selected())
        self.canvas.bind("<BackSpace>", lambda e: self.delete_selected())
        self.canvas.bind("<Escape>", lambda e: self._on_escape())
        self.canvas.focus_set()

        self._set_status(
            "Doble clic: crear nodo · Arrastrar: mover · Botón \"Conectar nodos\" (o "
            "Shift + arrastrar): crear una conexión · Clic derecho: opciones"
        )

    # ------------------------------------------------------------------ #
    # Utilidades
    # ------------------------------------------------------------------ #
    def _set_status(self, text: str) -> None:
        self.on_status(text)

    def _font(self, node: Optional[Node] = None):
        import tkinter.font as tkfont
        size = 15 if (node and node.shape == "root") else 12
        return tkfont.Font(family="Helvetica", size=size, weight="bold")

    def _canvas_center(self) -> Tuple[float, float]:
        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        cx = w / 2 if w > 1 else 400
        cy = h / 2 if h > 1 else 300
        return cx, cy

    def _on_escape(self) -> None:
        self._connect_first_node = None
        self.clear_selection()

    # ------------------------------------------------------------------ #
    # Modo conectar (clic en origen, clic en destino)
    # ------------------------------------------------------------------ #
    def toggle_connect_mode(self) -> None:
        self.connect_mode = not self.connect_mode
        self._connect_first_node = None
        self.clear_selection()
        self.canvas.config(cursor="crosshair" if self.connect_mode else "")
        self.on_connect_mode_change(self.connect_mode)
        if self.connect_mode:
            self._set_status("Modo conectar activo: haz clic en el nodo origen y luego en el destino.")
        else:
            self._set_status("Modo conectar desactivado.")

    def _handle_connect_mode_click(self, node_id: Optional[int]) -> None:
        if node_id is None:
            if self._connect_first_node is not None:
                self._connect_first_node = None
                self.clear_selection()
                self._set_status("Conexión cancelada. Haz clic en un nodo para elegir el origen.")
            return

        if self._connect_first_node is None:
            self._connect_first_node = node_id
            self.select_node(node_id)
            self._set_status(f'Origen: "{self.nodes[node_id].text}". Ahora haz clic en el nodo destino.')
            return

        if node_id == self._connect_first_node:
            self._set_status("Elige un nodo distinto como destino.")
            return

        source_id = self._connect_first_node
        self._connect_first_node = None
        self.new_connection(source_id, node_id)

    # ------------------------------------------------------------------ #
    # Paleta de colores
    # ------------------------------------------------------------------ #
    def apply_palette(self, name: str, recolor_existing: bool = True) -> None:
        if name not in PALETTES:
            return
        self.palette_name = name
        self._color_cycle = itertools.cycle(PALETTES[name]["colors"])

        if not recolor_existing or not self.nodes:
            self._set_status(f'Paleta "{name}" seleccionada para los próximos nodos.')
            return

        self._snapshot_undo()
        children: Dict[int, list] = {nid: [] for nid in self.nodes}
        incoming: Dict[int, int] = {nid: 0 for nid in self.nodes}
        for conn in self.connections.values():
            children.setdefault(conn.source_id, []).append((conn.target_id, conn.id))
            incoming[conn.target_id] = incoming.get(conn.target_id, 0) + 1

        roots = [nid for nid, n in self.nodes.items() if n.shape == "root"]
        if not roots:
            roots = [nid for nid, deg in incoming.items() if deg == 0] or [next(iter(self.nodes))]

        accent = PALETTES[name]["accent"]
        for root_id in roots:
            root_node = self.nodes[root_id]
            if root_node.shape == "root":
                root_node.color = accent
                self._redraw_node(root_node)

        branch_colors = itertools.cycle(PALETTES[name]["colors"])
        visited = set(roots)
        for root_id in roots:
            for child_id, conn_id in children.get(root_id, []):
                self._recolor_branch(child_id, next(branch_colors), visited, children)
                self.connections[conn_id].color = self.nodes[child_id].color
                self.canvas.itemconfig(self.conn_items[conn_id], fill=self.nodes[child_id].color)

        self._set_status(f'Paleta "{name}" aplicada al mapa.')

    def _recolor_branch(self, node_id: int, color: str, visited: set, children: Dict[int, list]) -> None:
        if node_id in visited:
            return
        visited.add(node_id)
        node = self.nodes[node_id]
        node.color = color
        self._redraw_node(node)
        for child_id, conn_id in children.get(node_id, []):
            self.connections[conn_id].color = color
            self.canvas.itemconfig(self.conn_items[conn_id], fill=color)
            self._recolor_branch(child_id, color, visited, children)

    # ------------------------------------------------------------------ #
    # Deshacer / rehacer
    # ------------------------------------------------------------------ #
    def _snapshot_undo(self) -> None:
        if self._suspend_undo:
            return
        self.undo_stack.append(copy.deepcopy(self.to_dict()))
        if len(self.undo_stack) > self._max_undo:
            self.undo_stack.pop(0)
        self.redo_stack.clear()

    def can_undo(self) -> bool:
        return bool(self.undo_stack)

    def can_redo(self) -> bool:
        return bool(self.redo_stack)

    def undo(self) -> None:
        if not self.undo_stack:
            self._set_status("No hay nada que deshacer.")
            return
        current = copy.deepcopy(self.to_dict())
        state = self.undo_stack.pop()
        self.redo_stack.append(current)
        self._suspend_undo = True
        try:
            self._apply_dict(state)
        finally:
            self._suspend_undo = False
        self._set_status("Acción deshecha.")

    def redo(self) -> None:
        if not self.redo_stack:
            self._set_status("No hay nada que rehacer.")
            return
        current = copy.deepcopy(self.to_dict())
        state = self.redo_stack.pop()
        self.undo_stack.append(current)
        self._suspend_undo = True
        try:
            self._apply_dict(state)
        finally:
            self._suspend_undo = False
        self._set_status("Acción rehecha.")

    # ------------------------------------------------------------------ #
    # Creación / dibujo de nodos
    # ------------------------------------------------------------------ #
    def new_node(self, x: Optional[float] = None, y: Optional[float] = None,
                 text: str = "Nueva idea", color: Optional[str] = None,
                 shape: str = "leaf") -> Node:
        self._snapshot_undo()
        if x is None or y is None:
            x, y = self._canvas_center()
        node = Node(
            id=next(self._node_id_seq),
            x=x, y=y, text=text,
            color=color or next(self._color_cycle),
            shape=shape,
        )
        self.nodes[node.id] = node
        self._draw_node(node)
        self.select_node(node.id)
        return node

    def _draw_node(self, node: Node) -> None:
        font = self._font(node)
        display_text = node.text.upper() if node.shape == "root" else node.text
        lines = display_text.split("\n") or [""]
        text_w = max(font.measure(line) for line in lines)
        text_h = 22 * len(lines)
        tag = f"nid_{node.id}"

        if node.shape == "root":
            node.width = max(160, text_w + 70)
            node.height = max(100, text_h + 60)
            x1, y1 = node.x - node.width / 2, node.y - node.height / 2
            x2, y2 = node.x + node.width / 2, node.y + node.height / 2
            shape_item = self.canvas.create_oval(
                x1, y1, x2, y2, outline=node.color, width=7, fill="#ffffff",
                tags=("node", tag),
            )
            text_item = self.canvas.create_text(
                node.x, node.y, text=node.text.upper(), fill="#1a1a1a",
                font=font, tags=("node", "node-text", tag), width=node.width - 30,
                justify="center",
            )
        else:
            node.width = max(50, text_w + 20)
            node.height = max(26, text_h + 12)
            x1, y1 = node.x - node.width / 2, node.y - node.height / 2
            x2, y2 = node.x + node.width / 2, node.y + node.height / 2
            shape_item = self.canvas.create_rectangle(
                x1, y1, x2, y2, outline="", fill="", tags=("node", tag),
            )
            text_item = self.canvas.create_text(
                node.x, node.y, text=node.text, fill=node.color,
                font=font, tags=("node", "node-text", tag), width=max(node.width, 220),
                justify="center",
            )

        self.node_items[node.id] = {"shape": shape_item, "text": text_item}

        for t in (shape_item, text_item):
            self.canvas.tag_bind(t, "<Enter>", lambda e: self.canvas.config(cursor="fleur"))
            self.canvas.tag_bind(t, "<Leave>", lambda e: self.canvas.config(cursor=""))

    def _redraw_node(self, node: Node) -> None:
        old_items = self.node_items.get(node.id)
        was_selected = self.selected == ("node", node.id)
        if old_items:
            self.canvas.delete(old_items["shape"])
            self.canvas.delete(old_items["text"])
        self._draw_node(node)
        if was_selected:
            self.selected = ("node", node.id)
            self._apply_node_selection_style(node.id, True)
        self._update_connections_for_node(node.id)

    def _apply_node_selection_style(self, node_id: int, selected: bool) -> None:
        node = self.nodes[node_id]
        shape_item = self.node_items[node_id]["shape"]
        if node.shape == "root":
            self.canvas.itemconfig(
                shape_item, outline=SELECT_OUTLINE if selected else node.color,
                width=9 if selected else 7,
            )
        else:
            self.canvas.itemconfig(
                shape_item, outline=SELECT_OUTLINE if selected else "",
                width=2 if selected else 0,
            )

    def toggle_node_shape(self, node_id: int) -> None:
        node = self.nodes[node_id]
        self._snapshot_undo()
        node.shape = "leaf" if node.shape == "root" else "root"
        self._redraw_node(node)

    def delete_node(self, node_id: int) -> None:
        if node_id not in self.nodes:
            return
        self._snapshot_undo()
        items = self.node_items.pop(node_id)
        self.canvas.delete(items["shape"])
        self.canvas.delete(items["text"])
        del self.nodes[node_id]

        previous_suspend = self._suspend_undo
        self._suspend_undo = True
        try:
            for conn_id in [c.id for c in self.connections.values()
                             if c.source_id == node_id or c.target_id == node_id]:
                self.delete_connection(conn_id)
        finally:
            self._suspend_undo = previous_suspend

        if self.selected == ("node", node_id):
            self.selected = None

    # ------------------------------------------------------------------ #
    # Creación / dibujo de conexiones
    # ------------------------------------------------------------------ #
    def new_connection(self, source_id: int, target_id: int) -> Optional[Connection]:
        if source_id == target_id:
            return None
        if any(c.source_id == source_id and c.target_id == target_id
               or c.source_id == target_id and c.target_id == source_id
               for c in self.connections.values()):
            self._set_status("Esos nodos ya están conectados.")
            return None
        self._snapshot_undo()
        conn = Connection(
            id=next(self._conn_id_seq), source_id=source_id, target_id=target_id,
            color=self.nodes[target_id].color, line_width=10,
        )
        self.connections[conn.id] = conn
        self._draw_connection(conn)
        self.select_connection(conn.id)
        return conn

    def _connection_coords(self, conn: Connection):
        a = self.nodes[conn.source_id]
        b = self.nodes[conn.target_id]
        return a.x, a.y, b.x, b.y

    def _branch_points(self, conn: Connection):
        a = self.nodes[conn.source_id]
        b = self.nodes[conn.target_id]
        x1, y1, x2, y2 = a.x, a.y, b.x, b.y
        dist = math.hypot(x2 - x1, y2 - y1) or 1
        ux, uy = (x2 - x1) / dist, (y2 - y1) / dist

        base_w = conn.line_width * 2.2
        tip_w = max(2.5, base_w * 0.3)

        if a.shape == "root":
            start_trim = min(a.width, a.height) / 2 + 2
        else:
            start_trim = max(_rect_clearance(a.width, a.height, ux, uy) + 4, base_w / 2 + 4)
        if b.shape == "root":
            end_trim = min(b.width, b.height) / 2 + 6
        else:
            end_trim = max(_rect_clearance(b.width, b.height, ux, uy) + 12, tip_w / 2 + 12)
        start_trim = min(start_trim, dist * 0.4)
        end_trim = min(end_trim, dist * 0.4)

        x1t, y1t = x1 + ux * start_trim, y1 + uy * start_trim
        x2t, y2t = x2 - ux * end_trim, y2 - uy * end_trim

        return _tapered_branch_points(x1t, y1t, x2t, y2t, base_w, tip_w)

    def _draw_connection(self, conn: Connection) -> None:
        tag = f"cid_{conn.id}"
        poly = self.canvas.create_polygon(
            self._branch_points(conn),
            fill=conn.color, outline="", smooth=True, splinesteps=10,
            tags=("conn", tag),
        )
        self.canvas.tag_lower(poly)
        self.conn_items[conn.id] = poly

    def _update_connections_for_node(self, node_id: int) -> None:
        for conn in self.connections.values():
            if conn.source_id == node_id or conn.target_id == node_id:
                self.canvas.coords(self.conn_items[conn.id], *self._branch_points(conn))

    def delete_connection(self, conn_id: int) -> None:
        if conn_id not in self.connections:
            return
        self._snapshot_undo()
        self.canvas.delete(self.conn_items.pop(conn_id))
        del self.connections[conn_id]
        if self.selected == ("conn", conn_id):
            self.selected = None

    # ------------------------------------------------------------------ #
    # Selección visual
    # ------------------------------------------------------------------ #
    def clear_selection(self) -> None:
        if self.selected is None:
            return
        kind, item_id = self.selected
        if kind == "node" and item_id in self.node_items:
            self._apply_node_selection_style(item_id, False)
        elif kind == "conn" and item_id in self.conn_items:
            self.canvas.itemconfig(self.conn_items[item_id], outline="", width=0)
        self.selected = None

    def select_node(self, node_id: int) -> None:
        self.clear_selection()
        self.selected = ("node", node_id)
        self._apply_node_selection_style(node_id, True)
        self._set_status(f"Nodo seleccionado: \"{self.nodes[node_id].text}\"")

    def select_connection(self, conn_id: int) -> None:
        self.clear_selection()
        self.selected = ("conn", conn_id)
        self.canvas.itemconfig(self.conn_items[conn_id], outline=SELECT_OUTLINE, width=2)
        self._set_status("Conexión seleccionada. Usa el botón de color para cambiarla.")

    def delete_selected(self) -> None:
        if self.selected is None:
            return
        kind, item_id = self.selected
        if kind == "node":
            self.delete_node(item_id)
        else:
            self.delete_connection(item_id)
        self._set_status("Elemento eliminado.")

    # ------------------------------------------------------------------ #
    # Identificación de elementos bajo el cursor
    # ------------------------------------------------------------------ #
    def _node_id_at(self, x: float, y: float) -> Optional[int]:
        for item in self.canvas.find_overlapping(x - 4, y - 4, x + 4, y + 4):
            for tag in self.canvas.gettags(item):
                if tag.startswith("nid_"):
                    return int(tag.split("_", 1)[1])
        return None

    def _conn_id_at(self, x: float, y: float) -> Optional[int]:
        for item in self.canvas.find_overlapping(x - 3, y - 3, x + 3, y + 3):
            tags = self.canvas.gettags(item)
            if "conn" in tags:
                for tag in tags:
                    if tag.startswith("cid_"):
                        return int(tag.split("_", 1)[1])
        return None

    # ------------------------------------------------------------------ #
    # Eventos de mouse
    # ------------------------------------------------------------------ #
    def _on_canvas_press(self, event) -> None:
        self.canvas.focus_set()
        node_id = self._node_id_at(event.x, event.y)

        if self.connect_mode:
            self._handle_connect_mode_click(node_id)
            self._drag = {"mode": None, "node_id": None, "last_x": event.x, "last_y": event.y}
            return

        shift_held = bool(event.state & 0x0001)

        if node_id is not None:
            self.select_node(node_id)
            if shift_held:
                self._drag = {"mode": "connect", "node_id": node_id,
                               "last_x": event.x, "last_y": event.y}
                node = self.nodes[node_id]
                self._connect_temp_line = self.canvas.create_line(
                    node.x, node.y, event.x, event.y,
                    fill="#999999", width=2, dash=(4, 2),
                )
            else:
                self._snapshot_undo()
                self._drag = {"mode": "move", "node_id": node_id,
                               "last_x": event.x, "last_y": event.y}
            return

        conn_id = self._conn_id_at(event.x, event.y)
        if conn_id is not None:
            self.select_connection(conn_id)
            self._drag = {"mode": None, "node_id": None, "last_x": event.x, "last_y": event.y}
            return

        self.clear_selection()
        self._drag = {"mode": None, "node_id": None, "last_x": event.x, "last_y": event.y}

    def _on_canvas_motion(self, event) -> None:
        mode = self._drag.get("mode")
        if mode == "move":
            node_id = self._drag["node_id"]
            node = self.nodes[node_id]
            dx = event.x - self._drag["last_x"]
            dy = event.y - self._drag["last_y"]
            node.x += dx
            node.y += dy
            self.canvas.move(f"nid_{node_id}", dx, dy)
            self._update_connections_for_node(node_id)
            self._drag["last_x"], self._drag["last_y"] = event.x, event.y
        elif mode == "connect" and self._connect_temp_line is not None:
            node = self.nodes[self._drag["node_id"]]
            self.canvas.coords(self._connect_temp_line, node.x, node.y, event.x, event.y)
            target_id = self._node_id_at(event.x, event.y)
            self.canvas.config(cursor="hand2" if target_id not in (None, self._drag["node_id"])
                                else "X_cursor")

    def _on_canvas_release(self, event) -> None:
        mode = self._drag.get("mode")
        if mode == "connect":
            if self._connect_temp_line is not None:
                self.canvas.delete(self._connect_temp_line)
                self._connect_temp_line = None
            self.canvas.config(cursor="")
            target_id = self._node_id_at(event.x, event.y)
            source_id = self._drag["node_id"]
            if target_id is not None and target_id != source_id:
                self.new_connection(source_id, target_id)
            else:
                self._set_status("Conexión cancelada: suelta sobre otro nodo para conectar.")
        self._drag = {"mode": None, "node_id": None, "last_x": 0, "last_y": 0}

    def _on_canvas_double_click(self, event) -> None:
        node_id = self._node_id_at(event.x, event.y)
        if node_id is not None:
            self.rename_node(node_id)
        else:
            self.new_node(x=event.x, y=event.y)

    def _on_canvas_right_click(self, event) -> None:
        node_id = self._node_id_at(event.x, event.y)
        if node_id is not None:
            self.select_node(node_id)
            self._show_node_menu(event, node_id)
            return
        conn_id = self._conn_id_at(event.x, event.y)
        if conn_id is not None:
            self.select_connection(conn_id)
            self._show_conn_menu(event, conn_id)
            return
        self._show_canvas_menu(event)

    # ------------------------------------------------------------------ #
    # Menús contextuales
    # ------------------------------------------------------------------ #
    def _show_node_menu(self, event, node_id: int) -> None:
        node = self.nodes[node_id]
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="Renombrar", command=lambda: self.rename_node(node_id))
        menu.add_command(label="Cambiar color del nodo",
                          command=lambda: self.change_node_color(node_id))
        shape_label = "Convertir en nodo de rama" if node.shape == "root" else "Convertir en nodo central"
        menu.add_command(label=shape_label, command=lambda: self.toggle_node_shape(node_id))
        menu.add_separator()
        menu.add_command(label="Eliminar nodo", command=lambda: self.delete_node(node_id))
        menu.tk_popup(event.x_root, event.y_root)

    def _show_conn_menu(self, event, conn_id: int) -> None:
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="Cambiar color de la conexión",
                          command=lambda: self.change_connection_color(conn_id))
        menu.add_command(label="Aumentar grosor", command=lambda: self.change_connection_width(conn_id, 3))
        menu.add_command(label="Disminuir grosor", command=lambda: self.change_connection_width(conn_id, -3))
        menu.add_separator()
        menu.add_command(label="Eliminar conexión", command=lambda: self.delete_connection(conn_id))
        menu.tk_popup(event.x_root, event.y_root)

    def _show_canvas_menu(self, event) -> None:
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="Nuevo nodo aquí", command=lambda: self.new_node(x=event.x, y=event.y))
        menu.tk_popup(event.x_root, event.y_root)

    # ------------------------------------------------------------------ #
    # Acciones de edición
    # ------------------------------------------------------------------ #
    def rename_node(self, node_id: int) -> None:
        node = self.nodes[node_id]
        new_text = simpledialog.askstring(
            "Editar nodo", "Texto del nodo:", initialvalue=node.text, parent=self,
        )
        if new_text is not None and new_text.strip():
            self._snapshot_undo()
            node.text = new_text.strip()
            self._redraw_node(node)

    def change_node_color(self, node_id: int) -> None:
        node = self.nodes[node_id]
        _, hex_color = colorchooser.askcolor(color=node.color, title="Color del nodo", parent=self)
        if hex_color:
            self._snapshot_undo()
            node.color = hex_color
            self._redraw_node(node)

    def change_connection_color(self, conn_id: int) -> None:
        conn = self.connections[conn_id]
        _, hex_color = colorchooser.askcolor(color=conn.color, title="Color de la conexión", parent=self)
        if hex_color:
            self._snapshot_undo()
            conn.color = hex_color
            self.canvas.itemconfig(self.conn_items[conn_id], fill=hex_color)
            self._set_status(f"Color de conexión cambiado a {hex_color}.")

    def change_connection_width(self, conn_id: int, delta: int) -> None:
        self._snapshot_undo()
        conn = self.connections[conn_id]
        conn.line_width = max(4, min(40, conn.line_width + delta))
        self.canvas.coords(self.conn_items[conn_id], *self._branch_points(conn))

    # ------------------------------------------------------------------ #
    # Selección desde botones externos (toolbar)
    # ------------------------------------------------------------------ #
    def selected_node_id(self) -> Optional[int]:
        if self.selected and self.selected[0] == "node":
            return self.selected[1]
        return None

    def selected_connection_id(self) -> Optional[int]:
        if self.selected and self.selected[0] == "conn":
            return self.selected[1]
        return None

    # ------------------------------------------------------------------ #
    # Generar mapa a partir de texto plano o Markdown
    # ------------------------------------------------------------------ #
    def build_mindmap_from_text(self, raw_text: str) -> bool:
        outline = parse_outline(raw_text)
        if outline is None:
            return False

        self._snapshot_undo()
        self._suspend_undo = True
        try:
            self.clear_all()
            cx, cy = self._canvas_center()

            accent = PALETTES[self.palette_name]["accent"]
            root_node = self.new_node(x=cx, y=cy, text=outline.text, color=accent, shape="root")
            self._place_outline_children(root_node, outline.children, cx, cy, 0, 2 * math.pi, level=1)
            self.clear_selection()
        finally:
            self._suspend_undo = False
        self._set_status(f"Mapa generado con {len(self.nodes)} nodos a partir del texto.")
        return True

    def _place_outline_children(self, parent_node: Node, children: list,
                                 cx: float, cy: float, angle_start: float, angle_end: float,
                                 level: int, color: Optional[str] = None) -> None:
        if not children:
            return
        count = len(children)
        step = (angle_end - angle_start) / count
        radius = 190 * level
        branch_width = max(4, 18 - 4 * (level - 1))

        for i, outline_child in enumerate(children):
            angle = angle_start + step * (i + 0.5)
            x = cx + radius * math.cos(angle)
            y = cy + radius * math.sin(angle)
            branch_color = color or next(self._color_cycle)

            child_node = self.new_node(x=x, y=y, text=outline_child.text, color=branch_color)
            conn = self.new_connection(parent_node.id, child_node.id)
            if conn is not None:
                conn.color = branch_color
                conn.line_width = branch_width
                self.canvas.coords(self.conn_items[conn.id], *self._branch_points(conn))
                self.canvas.itemconfig(self.conn_items[conn.id], fill=branch_color)

            self._place_outline_children(
                child_node, outline_child.children, cx, cy,
                angle_start + step * i, angle_start + step * (i + 1),
                level + 1, branch_color,
            )

    # ------------------------------------------------------------------ #
    # Persistencia
    # ------------------------------------------------------------------ #
    def to_dict(self) -> dict:
        return {
            "nodes": [n.to_dict() for n in self.nodes.values()],
            "connections": [c.to_dict() for c in self.connections.values()],
        }

    def load_dict(self, data: dict) -> None:
        self._snapshot_undo()
        self._suspend_undo = True
        try:
            self._apply_dict(data)
        finally:
            self._suspend_undo = False

    def _apply_dict(self, data: dict) -> None:
        self.clear_all()
        max_node_id = 0
        for nd in data.get("nodes", []):
            node = Node.from_dict(nd)
            self.nodes[node.id] = node
            self._draw_node(node)
            max_node_id = max(max_node_id, node.id)
        max_conn_id = 0
        for cd in data.get("connections", []):
            conn = Connection.from_dict(cd)
            if conn.source_id in self.nodes and conn.target_id in self.nodes:
                self.connections[conn.id] = conn
                self._draw_connection(conn)
                max_conn_id = max(max_conn_id, conn.id)
        self._node_id_seq = itertools.count(max_node_id + 1)
        self._conn_id_seq = itertools.count(max_conn_id + 1)

    def reset_to_default(self, text: str = "Idea central", color: Optional[str] = None) -> Node:
        self._snapshot_undo()
        self._suspend_undo = True
        try:
            self.clear_all()
            cx, cy = self._canvas_center()
            node = self.new_node(
                x=cx, y=cy,
                text=text, color=color or PALETTES[self.palette_name]["accent"],
                shape="root",
            )
        finally:
            self._suspend_undo = False
        return node

    def clear_all(self) -> None:
        self.canvas.delete("all")
        self.nodes.clear()
        self.connections.clear()
        self.node_items.clear()
        self.conn_items.clear()
        self.selected = None
        self._node_id_seq = itertools.count(1)
        self._conn_id_seq = itertools.count(1)

    # ------------------------------------------------------------------ #
    # Exportar como imagen
    # ------------------------------------------------------------------ #
    def export_image(self, path: str) -> str:
        """Exporta el mapa a un archivo de imagen. Devuelve la ruta final escrita.

        Siempre genera primero un PostScript (soportado nativamente por Tkinter).
        Si se pidió un .png, intenta convertirlo con Ghostscript (si está en el
        PATH) o con Pillow (si está instalado); si ninguno está disponible, deja
        el archivo como PostScript (.ps) y lo informa mediante RuntimeError.
        """
        bbox = self.canvas.bbox("all")
        if bbox is None:
            raise ValueError("El mapa está vacío: no hay nada que exportar.")

        x1, y1, x2, y2 = bbox
        margin = 24
        width = (x2 - x1) + 2 * margin
        height = (y2 - y1) + 2 * margin

        wants_png = path.lower().endswith(".png")
        ps_path = path + ".tmp.ps" if wants_png else path

        self.canvas.postscript(
            file=ps_path, x=x1 - margin, y=y1 - margin,
            width=width, height=height, colormode="color",
        )

        if not wants_png:
            return path

        gs_bin = (shutil.which("gs") or shutil.which("gswin64c")
                  or shutil.which("gswin32c"))
        if gs_bin:
            try:
                subprocess.run(
                    [gs_bin, "-dSAFER", "-dBATCH", "-dNOPAUSE", "-sDEVICE=png16m",
                     "-r150", f"-sOutputFile={path}", ps_path],
                    check=True, capture_output=True,
                )
                os.remove(ps_path)
                return path
            except (subprocess.CalledProcessError, OSError):
                pass

        try:
            from PIL import Image
            img = Image.open(ps_path)
            img.load(scale=3)
            img.save(path, "png")
            os.remove(ps_path)
            return path
        except Exception:
            pass

        fallback_path = path[:-4] + ".ps"
        os.replace(ps_path, fallback_path)
        raise RuntimeError(
            "No se encontró Ghostscript ni Pillow en este equipo para generar el PNG.\n"
            f"El mapa se guardó como PostScript en su lugar:\n{fallback_path}\n\n"
            "Para exportar a PNG, instala Ghostscript (https://ghostscript.com/) "
            "o Pillow (pip install Pillow) junto con Ghostscript."
        )
