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

THEMES = {
    "Cuadrados": {"node": "box", "fill": "solid", "bg": "#f4f6f8"},
    "Contorno": {"node": "box", "fill": "outline", "bg": "#ffffff"},
    "Oscuro": {"node": "box", "fill": "solid", "bg": "#1e1e2e"},
    "Ramas": {"node": "dot", "fill": "solid", "bg": "#ffffff"},
}
DEFAULT_THEME = "Cuadrados"

SELECT_OUTLINE = "#ffd23f"

MIN_ZOOM = 0.3
MAX_ZOOM = 3.0


def _rect_clearance(width, height, ux, uy):
    """Distancia del centro al borde de un rectángulo width x height en la dirección (ux, uy)."""
    tx = (width / 2) / abs(ux) if abs(ux) > 1e-6 else float("inf")
    ty = (height / 2) / abs(uy) if abs(uy) > 1e-6 else float("inf")
    return min(tx, ty)


def _rounded_rect_points(x1, y1, x2, y2, radius):
    radius = max(0, min(radius, (x2 - x1) / 2, (y2 - y1) / 2))
    return [
        x1 + radius, y1,
        x2 - radius, y1,
        x2, y1,
        x2, y1 + radius,
        x2, y2 - radius,
        x2, y2,
        x2 - radius, y2,
        x1 + radius, y2,
        x1, y2,
        x1, y2 - radius,
        x1, y1 + radius,
        x1, y1,
    ]


class MindMapCanvas(tk.Frame):
    """Canvas interactivo: arrastra nodos, crea conexiones, cambia colores/tema y hace zoom."""

    def __init__(self, master, on_status: Optional[Callable[[str], None]] = None,
                 on_connect_mode_change: Optional[Callable[[bool], None]] = None, **kwargs):
        super().__init__(master, **kwargs)
        self.on_status = on_status or (lambda text: None)
        self.on_connect_mode_change = on_connect_mode_change or (lambda active: None)

        self.theme = DEFAULT_THEME
        self.canvas = tk.Canvas(self, bg=THEMES[self.theme]["bg"], highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)

        self.nodes: Dict[int, Node] = {}
        self.connections: Dict[int, Connection] = {}
        self.node_items: Dict[int, dict] = {}
        self.conn_items: Dict[int, int] = {}

        self._node_id_seq = itertools.count(1)
        self._conn_id_seq = itertools.count(1)
        self.palette_name = DEFAULT_PALETTE
        self._color_cycle = itertools.cycle(PALETTES[self.palette_name]["colors"])

        self._zoom = 1.0
        self._pan_x = 0.0
        self._pan_y = 0.0

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
        self.canvas.bind("<MouseWheel>", self._on_mousewheel)
        self.canvas.bind("<Button-4>", self._on_mousewheel)
        self.canvas.bind("<Button-5>", self._on_mousewheel)
        self.canvas.bind("<KeyPress-space>", self._on_space_press)
        self.canvas.bind("<KeyRelease-space>", self._on_space_release)
        self.canvas.bind("<Enter>", lambda e: self.canvas.focus_set())
        self.canvas.focus_set()

        self._space_held = False

        self._set_status(
            "Doble clic: crear nodo · Arrastrar: mover · Rueda del mouse: zoom · Espacio + "
            "arrastrar: desplazarse · Botón \"Conectar nodos\" (o Shift + arrastrar): crear "
            "una conexión · Clic derecho: opciones"
        )

    # ------------------------------------------------------------------ #
    # Utilidades
    # ------------------------------------------------------------------ #
    def _set_status(self, text: str) -> None:
        self.on_status(text)

    def _font(self, node: Optional[Node] = None, scale: float = 1.0):
        import tkinter.font as tkfont
        base_size = 16 if (node and node.shape == "root") else 12
        size = max(6, round(base_size * scale))
        return tkfont.Font(family="Helvetica", size=size, weight="bold")

    def _to_screen(self, x: float, y: float) -> Tuple[float, float]:
        return x * self._zoom + self._pan_x, y * self._zoom + self._pan_y

    def _to_model(self, x: float, y: float) -> Tuple[float, float]:
        return (x - self._pan_x) / self._zoom, (y - self._pan_y) / self._zoom

    def _canvas_center(self) -> Tuple[float, float]:
        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        sx = w / 2 if w > 1 else 400
        sy = h / 2 if h > 1 else 300
        return self._to_model(sx, sy)

    def _on_escape(self) -> None:
        self._connect_first_node = None
        self.clear_selection()

    # ------------------------------------------------------------------ #
    # Desplazarse (paneo) con Espacio + arrastrar
    # ------------------------------------------------------------------ #
    def _on_space_press(self, event) -> None:
        if not self._space_held:
            self._space_held = True
            if self._drag.get("mode") != "pan":
                self.canvas.config(cursor="fleur")

    def _on_space_release(self, event) -> None:
        self._space_held = False
        if self._drag.get("mode") != "pan":
            self.canvas.config(cursor="")

    # ------------------------------------------------------------------ #
    # Zoom con la rueda del mouse
    # ------------------------------------------------------------------ #
    def _on_mousewheel(self, event) -> None:
        delta = getattr(event, "delta", 0)
        if delta:
            factor = 1.1 if delta > 0 else (1 / 1.1)
        else:
            factor = 1.1 if getattr(event, "num", 5) == 4 else (1 / 1.1)
        self._zoom_at(event.x, event.y, factor)

    def _zoom_at(self, screen_x: float, screen_y: float, factor: float) -> None:
        old_zoom = self._zoom
        new_zoom = min(MAX_ZOOM, max(MIN_ZOOM, old_zoom * factor))
        if abs(new_zoom - old_zoom) < 1e-9:
            return
        applied = new_zoom / old_zoom
        self._pan_x = screen_x - (screen_x - self._pan_x) * applied
        self._pan_y = screen_y - (screen_y - self._pan_y) * applied
        self._zoom = new_zoom
        self._redraw_all()
        self._set_status(f"Zoom: {round(self._zoom * 100)}%")

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
    # Tema visual
    # ------------------------------------------------------------------ #
    def set_theme(self, name: str) -> None:
        if name not in THEMES:
            return
        self.theme = name
        self.canvas.config(bg=THEMES[name]["bg"])
        self._redraw_all()
        self._set_status(f'Tema "{name}" aplicado.')

    def _redraw_all(self) -> None:
        for node in list(self.nodes.values()):
            self._redraw_node(node)
        self._redraw_all_connections()

    def _redraw_all_connections(self) -> None:
        for conn in self.connections.values():
            item = self.conn_items.get(conn.id)
            if item is None:
                continue
            self.canvas.coords(item, *self._connection_line_points(conn))
            selected = self.selected == ("conn", conn.id)
            width = conn.line_width * self._zoom + (3 if selected else 0)
            self.canvas.itemconfig(item, width=max(1, width))

    # ------------------------------------------------------------------ #
    # Paleta de colores
    # ------------------------------------------------------------------ #
    def add_custom_palette(self, name: str, colors: list, accent: str) -> None:
        PALETTES[name] = {"colors": list(colors), "accent": accent}

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
        theme = THEMES[self.theme]
        if theme["node"] == "dot" and node.shape != "root":
            self._draw_node_dot(node)
        else:
            self._draw_node_box(node, theme)

    def _draw_node_box(self, node: Node, theme: dict) -> None:
        base_font = self._font(node)
        lines = node.text.split("\n") or [""]
        text_w = max(base_font.measure(line) for line in lines)
        is_root = node.shape == "root"
        text_h = (26 if is_root else 20) * len(lines)
        pad_x, pad_y = (34, 20) if is_root else (16, 10)
        min_w, min_h = (140, 60) if is_root else (50, 34)
        tag = f"nid_{node.id}"

        node.width = max(min_w, text_w + 2 * pad_x)
        node.height = max(min_h, text_h + 2 * pad_y)

        zoom = self._zoom
        sx, sy = self._to_screen(node.x, node.y)
        sw, sh = node.width * zoom, node.height * zoom
        x1, y1 = sx - sw / 2, sy - sh / 2
        x2, y2 = sx + sw / 2, sy + sh / 2
        radius = min(18 * zoom, sh / 2)

        outline_mode = theme["fill"] == "outline"
        fill_color = "#ffffff" if outline_mode else node.color
        outline_color = node.color if outline_mode else ""
        outline_width = max(2, round(3 * zoom)) if outline_mode else 0
        text_color = node.color if outline_mode else "#ffffff"

        shape_item = self.canvas.create_polygon(
            _rounded_rect_points(x1, y1, x2, y2, radius),
            fill=fill_color, outline=outline_color, width=outline_width,
            smooth=True, splinesteps=8, tags=("node", tag),
        )
        render_font = self._font(node, scale=zoom)
        text_item = self.canvas.create_text(
            sx, sy, text=node.text, fill=text_color,
            font=render_font, tags=("node", "node-text", tag),
            width=max(1, sw - 2 * pad_x * zoom), justify="center",
        )
        self.node_items[node.id] = {
            "shape": shape_item, "text": text_item,
            "outline": (outline_color, outline_width),
        }
        self.canvas.tag_bind(tag, "<Enter>", lambda e: self.canvas.config(cursor="fleur"))
        self.canvas.tag_bind(tag, "<Leave>", lambda e: self.canvas.config(cursor=""))

    def _draw_node_dot(self, node: Node) -> None:
        base_font = self._font(node)
        lines = node.text.split("\n") or [""]
        text_w = max(base_font.measure(line) for line in lines)
        text_h = 18 * len(lines)
        tag = f"nid_{node.id}"

        dot_r_base = 7
        gap_base = dot_r_base + 8
        side = self._dot_text_side(node)

        node.width = text_w + gap_base + dot_r_base
        node.height = max(20, text_h)

        zoom = self._zoom
        sx, sy = self._to_screen(node.x, node.y)
        dot_r = dot_r_base * zoom
        gap = gap_base * zoom

        anchor = "w" if side == "right" else "e"
        text_x = sx + gap if side == "right" else sx - gap

        shape_item = self.canvas.create_oval(
            sx - dot_r, sy - dot_r, sx + dot_r, sy + dot_r,
            fill=node.color, outline="", tags=("node", tag),
        )
        render_font = self._font(node, scale=zoom)
        text_item = self.canvas.create_text(
            text_x, sy, text=node.text, fill=node.color,
            font=render_font, tags=("node", "node-text", tag),
            anchor=anchor, justify="left" if anchor == "w" else "right",
        )
        self.node_items[node.id] = {
            "shape": shape_item, "text": text_item,
            "outline": ("", 0),
        }
        self.canvas.tag_bind(tag, "<Enter>", lambda e: self.canvas.config(cursor="fleur"))
        self.canvas.tag_bind(tag, "<Leave>", lambda e: self.canvas.config(cursor=""))

    def _incoming_connection(self, node_id: int) -> Optional[Connection]:
        for conn in self.connections.values():
            if conn.target_id == node_id:
                return conn
        return None

    def _dot_text_side(self, node: Node) -> str:
        incoming = self._incoming_connection(node.id)
        if incoming is None:
            return "right"
        parent = self.nodes.get(incoming.source_id)
        if parent is None:
            return "right"
        return "right" if node.x >= parent.x else "left"

    def _redraw_node(self, node: Node) -> None:
        was_selected = self.selected == ("node", node.id)
        self.canvas.delete(f"nid_{node.id}")
        self.node_items.pop(node.id, None)
        self._draw_node(node)
        if was_selected:
            self.selected = ("node", node.id)
            self._apply_node_selection_style(node.id, True)
        self._update_connections_for_node(node.id)

    def _apply_node_selection_style(self, node_id: int, selected: bool) -> None:
        items = self.node_items[node_id]
        shape_item = items["shape"]
        default_color, default_width = items.get("outline", ("", 0))
        if selected:
            self.canvas.itemconfig(
                shape_item, outline=SELECT_OUTLINE,
                width=max(default_width, round(2 * self._zoom)) + 1,
            )
        else:
            self.canvas.itemconfig(shape_item, outline=default_color, width=default_width)

    def toggle_node_shape(self, node_id: int) -> None:
        node = self.nodes[node_id]
        self._snapshot_undo()
        node.shape = "leaf" if node.shape == "root" else "root"
        self._redraw_node(node)

    def delete_node(self, node_id: int) -> None:
        if node_id not in self.nodes:
            return
        self._snapshot_undo()
        self.canvas.delete(f"nid_{node_id}")
        self.node_items.pop(node_id, None)
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
            color=self.nodes[target_id].color, line_width=3,
        )
        self.connections[conn.id] = conn
        self._draw_connection(conn)
        if THEMES[self.theme]["node"] == "dot":
            # el lado del texto del destino puede depender de dónde quedó el origen
            self._redraw_node(self.nodes[target_id])
        self.select_connection(conn.id)
        return conn

    def _connection_line_points(self, conn: Connection):
        a = self.nodes[conn.source_id]
        b = self.nodes[conn.target_id]
        x1, y1 = self._to_screen(a.x, a.y)
        x2, y2 = self._to_screen(b.x, b.y)
        dist = math.hypot(x2 - x1, y2 - y1) or 1
        px, py = -(y2 - y1) / dist, (x2 - x1) / dist
        offset = dist * 0.15
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        cx, cy = mx + px * offset, my + py * offset
        return [x1, y1, cx, cy, x2, y2]

    def _draw_connection(self, conn: Connection) -> None:
        tag = f"cid_{conn.id}"
        line = self.canvas.create_line(
            *self._connection_line_points(conn),
            fill=conn.color, width=max(1, conn.line_width * self._zoom), smooth=True,
            capstyle=tk.ROUND, joinstyle=tk.ROUND,
            tags=("conn", tag),
        )
        self.canvas.tag_lower(line)
        self.conn_items[conn.id] = line

    def _update_connections_for_node(self, node_id: int) -> None:
        for conn in self.connections.values():
            if conn.source_id == node_id or conn.target_id == node_id:
                self.canvas.coords(self.conn_items[conn.id], *self._connection_line_points(conn))
                selected = self.selected == ("conn", conn.id)
                width = conn.line_width * self._zoom + (3 if selected else 0)
                self.canvas.itemconfig(self.conn_items[conn.id], width=max(1, width))

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
            conn = self.connections.get(item_id)
            if conn:
                self.canvas.itemconfig(self.conn_items[item_id],
                                        width=max(1, conn.line_width * self._zoom))
        self.selected = None

    def select_node(self, node_id: int) -> None:
        self.clear_selection()
        self.selected = ("node", node_id)
        self._apply_node_selection_style(node_id, True)
        self._set_status(f"Nodo seleccionado: \"{self.nodes[node_id].text}\"")

    def select_connection(self, conn_id: int) -> None:
        self.clear_selection()
        self.selected = ("conn", conn_id)
        conn = self.connections[conn_id]
        self.canvas.itemconfig(self.conn_items[conn_id],
                                width=max(1, conn.line_width * self._zoom) + 3)
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
        for item in self.canvas.find_overlapping(x - 6, y - 6, x + 6, y + 6):
            for tag in self.canvas.gettags(item):
                if tag.startswith("nid_"):
                    return int(tag.split("_", 1)[1])
        return None

    def _conn_id_at(self, x: float, y: float) -> Optional[int]:
        for item in self.canvas.find_overlapping(x - 4, y - 4, x + 4, y + 4):
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

        if self._space_held:
            self._drag = {"mode": "pan", "node_id": None, "last_x": event.x, "last_y": event.y}
            self.canvas.config(cursor="fleur")
            return

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
                sx, sy = self._to_screen(node.x, node.y)
                self._connect_temp_line = self.canvas.create_line(
                    sx, sy, event.x, event.y,
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
        if mode == "pan":
            dx = event.x - self._drag["last_x"]
            dy = event.y - self._drag["last_y"]
            self.canvas.move("all", dx, dy)
            self._pan_x += dx
            self._pan_y += dy
            self._drag["last_x"], self._drag["last_y"] = event.x, event.y
            return
        if mode == "move":
            node_id = self._drag["node_id"]
            node = self.nodes[node_id]
            dx = (event.x - self._drag["last_x"]) / self._zoom
            dy = (event.y - self._drag["last_y"]) / self._zoom
            node.x += dx
            node.y += dy
            self.canvas.move(f"nid_{node_id}",
                              event.x - self._drag["last_x"], event.y - self._drag["last_y"])
            self._update_connections_for_node(node_id)
            self._drag["last_x"], self._drag["last_y"] = event.x, event.y
        elif mode == "connect" and self._connect_temp_line is not None:
            node = self.nodes[self._drag["node_id"]]
            sx, sy = self._to_screen(node.x, node.y)
            self.canvas.coords(self._connect_temp_line, sx, sy, event.x, event.y)
            target_id = self._node_id_at(event.x, event.y)
            self.canvas.config(cursor="hand2" if target_id not in (None, self._drag["node_id"])
                                else "X_cursor")

    def _on_canvas_release(self, event) -> None:
        mode = self._drag.get("mode")
        if mode == "pan":
            self.canvas.config(cursor="fleur" if self._space_held else "")
            self._drag = {"mode": None, "node_id": None, "last_x": 0, "last_y": 0}
            return
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
            mx, my = self._to_model(event.x, event.y)
            self.new_node(x=mx, y=my)

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
        menu.add_command(label="Aumentar grosor", command=lambda: self.change_connection_width(conn_id, 1))
        menu.add_command(label="Disminuir grosor", command=lambda: self.change_connection_width(conn_id, -1))
        menu.add_separator()
        menu.add_command(label="Eliminar conexión", command=lambda: self.delete_connection(conn_id))
        menu.tk_popup(event.x_root, event.y_root)

    def _show_canvas_menu(self, event) -> None:
        menu = tk.Menu(self, tearoff=0)
        mx, my = self._to_model(event.x, event.y)
        menu.add_command(label="Nuevo nodo aquí", command=lambda: self.new_node(x=mx, y=my))
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
        conn.line_width = max(1, min(12, conn.line_width + delta))
        selected = self.selected == ("conn", conn_id)
        width = conn.line_width * self._zoom + (3 if selected else 0)
        self.canvas.itemconfig(self.conn_items[conn_id], width=max(1, width))

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
        branch_width = max(1, 6 - (level - 1))

        for i, outline_child in enumerate(children):
            angle = angle_start + step * (i + 0.5)
            if level == 1 and parent_node.shape == "root":
                # deja espacio suficiente para que el hijo no quede pegado a un
                # nodo raíz ancho (título largo) sin lugar para su propio texto
                radius = _rect_clearance(
                    parent_node.width, parent_node.height, math.cos(angle), math.sin(angle)
                ) + 110
            else:
                radius = 170 * level
            x = cx + radius * math.cos(angle)
            y = cy + radius * math.sin(angle)
            branch_color = color or next(self._color_cycle)

            child_node = self.new_node(x=x, y=y, text=outline_child.text, color=branch_color)
            conn = self.new_connection(parent_node.id, child_node.id)
            if conn is not None:
                conn.color = branch_color
                conn.line_width = branch_width
                self.canvas.itemconfig(self.conn_items[conn.id], fill=branch_color,
                                        width=max(1, branch_width * self._zoom))

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
        self._zoom = 1.0
        self._pan_x = 0.0
        self._pan_y = 0.0

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
        if not self.nodes:
            raise ValueError("El mapa está vacío: no hay nada que exportar.")

        # Exporta siempre a un zoom del 100%, sin importar el nivel de zoom
        # actual en pantalla, para que el resultado sea siempre nítido y consistente.
        prev_zoom, prev_pan_x, prev_pan_y = self._zoom, self._pan_x, self._pan_y
        self._zoom, self._pan_x, self._pan_y = 1.0, 0.0, 0.0
        self._redraw_all()
        try:
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
        finally:
            self._zoom, self._pan_x, self._pan_y = prev_zoom, prev_pan_x, prev_pan_y
            self._redraw_all()

        if not wants_png:
            return path

        gs_bin = (shutil.which("gs") or shutil.which("gswin64c")
                  or shutil.which("gswin32c"))
        if gs_bin:
            try:
                subprocess.run(
                    [gs_bin, "-dSAFER", "-dBATCH", "-dNOPAUSE", "-dEPSCrop",
                     "-sDEVICE=png16m", "-r150", f"-sOutputFile={path}", ps_path],
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
