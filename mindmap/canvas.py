"""Widget de canvas que dibuja y gestiona el mapa mental interactivo."""

import itertools
import math
import tkinter as tk
from tkinter import colorchooser, simpledialog
from typing import Callable, Dict, Optional, Tuple

from .models import Connection, Node
from .text_import import OutlineNode, parse_outline

NODE_COLORS = [
    "#4a90d9", "#e0673a", "#3aab6b", "#c94f9e",
    "#e0a83a", "#7c5cc4", "#3ab5c9", "#c9483a",
]

SELECT_OUTLINE = "#ffd23f"
DEFAULT_OUTLINE = "#2b3a4a"


def _rounded_rect_points(x1, y1, x2, y2, radius):
    radius = min(radius, (x2 - x1) / 2, (y2 - y1) / 2)
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
    """Canvas interactivo: arrastra nodos, crea conexiones y cambia sus colores."""

    def __init__(self, master, on_status: Optional[Callable[[str], None]] = None, **kwargs):
        super().__init__(master, **kwargs)
        self.on_status = on_status or (lambda text: None)

        self.canvas = tk.Canvas(self, bg="#f4f6f8", highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)

        self.nodes: Dict[int, Node] = {}
        self.connections: Dict[int, Connection] = {}
        self.node_items: Dict[int, Dict[str, int]] = {}
        self.conn_items: Dict[int, int] = {}

        self._node_id_seq = itertools.count(1)
        self._conn_id_seq = itertools.count(1)
        self._color_cycle = itertools.cycle(NODE_COLORS)

        self.selected: Optional[Tuple[str, int]] = None
        self._drag = {"mode": None, "node_id": None, "last_x": 0, "last_y": 0}
        self._connect_temp_line = None
        self._connect_source: Optional[int] = None

        self.canvas.bind("<ButtonPress-1>", self._on_canvas_press)
        self.canvas.bind("<B1-Motion>", self._on_canvas_motion)
        self.canvas.bind("<ButtonRelease-1>", self._on_canvas_release)
        self.canvas.bind("<Double-Button-1>", self._on_canvas_double_click)
        self.canvas.bind("<Button-3>", self._on_canvas_right_click)
        self.canvas.bind("<Delete>", lambda e: self.delete_selected())
        self.canvas.bind("<BackSpace>", lambda e: self.delete_selected())
        self.canvas.bind("<Escape>", lambda e: self.clear_selection())
        self.canvas.focus_set()

        self._set_status(
            "Doble clic: crear nodo · Arrastrar: mover · Shift + arrastrar: conectar · "
            "Clic derecho: opciones"
        )

    # ------------------------------------------------------------------ #
    # Utilidades
    # ------------------------------------------------------------------ #
    def _set_status(self, text: str) -> None:
        self.on_status(text)

    def _font(self):
        import tkinter.font as tkfont
        return tkfont.Font(family="Helvetica", size=11, weight="bold")

    # ------------------------------------------------------------------ #
    # Creación / dibujo de nodos
    # ------------------------------------------------------------------ #
    def new_node(self, x: Optional[float] = None, y: Optional[float] = None,
                 text: str = "Nueva idea", color: Optional[str] = None) -> Node:
        if x is None or y is None:
            x = self.canvas.winfo_width() / 2 or 400
            y = self.canvas.winfo_height() / 2 or 300
        node = Node(
            id=next(self._node_id_seq),
            x=x, y=y, text=text,
            color=color or next(self._color_cycle),
        )
        self.nodes[node.id] = node
        self._draw_node(node)
        self.select_node(node.id)
        return node

    def _draw_node(self, node: Node) -> None:
        font = self._font()
        lines = node.text.split("\n") or [""]
        text_w = max(font.measure(line) for line in lines)
        node.width = max(100, min(260, text_w + 40))
        node.height = max(50, 24 * len(lines) + 28)

        x1, y1 = node.x - node.width / 2, node.y - node.height / 2
        x2, y2 = node.x + node.width / 2, node.y + node.height / 2
        tag = f"nid_{node.id}"

        shape = self.canvas.create_polygon(
            _rounded_rect_points(x1, y1, x2, y2, 16),
            fill=node.color, outline=DEFAULT_OUTLINE, width=2,
            smooth=True, splinesteps=12,
            tags=("node", tag),
        )
        text_item = self.canvas.create_text(
            node.x, node.y, text=node.text, fill=node.text_color,
            font=font, tags=("node", "node-text", tag), width=node.width - 16,
            justify="center",
        )
        self.node_items[node.id] = {"shape": shape, "text": text_item}

        for t in (shape, text_item):
            self.canvas.tag_bind(t, "<Enter>", lambda e: self.canvas.config(cursor="fleur"))
            self.canvas.tag_bind(t, "<Leave>", lambda e: self.canvas.config(cursor=""))

    def _redraw_node(self, node: Node) -> None:
        items = self.node_items[node.id]
        font = self._font()
        lines = node.text.split("\n") or [""]
        text_w = max(font.measure(line) for line in lines)
        node.width = max(100, min(260, text_w + 40))
        node.height = max(50, 24 * len(lines) + 28)

        x1, y1 = node.x - node.width / 2, node.y - node.height / 2
        x2, y2 = node.x + node.width / 2, node.y + node.height / 2
        self.canvas.coords(items["shape"], *_rounded_rect_points(x1, y1, x2, y2, 16))
        self.canvas.itemconfig(items["shape"], fill=node.color)
        self.canvas.coords(items["text"], node.x, node.y)
        self.canvas.itemconfig(items["text"], text=node.text, fill=node.text_color,
                                width=node.width - 16)
        self._update_connections_for_node(node.id)

    def delete_node(self, node_id: int) -> None:
        if node_id not in self.nodes:
            return
        items = self.node_items.pop(node_id)
        self.canvas.delete(items["shape"])
        self.canvas.delete(items["text"])
        del self.nodes[node_id]

        for conn_id in [c.id for c in self.connections.values()
                         if c.source_id == node_id or c.target_id == node_id]:
            self.delete_connection(conn_id)

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
        conn = Connection(id=next(self._conn_id_seq), source_id=source_id, target_id=target_id)
        self.connections[conn.id] = conn
        self._draw_connection(conn)
        self.select_connection(conn.id)
        return conn

    def _connection_coords(self, conn: Connection):
        a = self.nodes[conn.source_id]
        b = self.nodes[conn.target_id]
        return a.x, a.y, b.x, b.y

    def _draw_connection(self, conn: Connection) -> None:
        tag = f"cid_{conn.id}"
        line = self.canvas.create_line(
            *self._connection_coords(conn),
            fill=conn.color, width=conn.line_width, capstyle=tk.ROUND,
            tags=("conn", tag),
        )
        self.canvas.tag_lower(line)
        self.conn_items[conn.id] = line

    def _update_connections_for_node(self, node_id: int) -> None:
        for conn in self.connections.values():
            if conn.source_id == node_id or conn.target_id == node_id:
                self.canvas.coords(self.conn_items[conn.id], *self._connection_coords(conn))

    def delete_connection(self, conn_id: int) -> None:
        if conn_id not in self.connections:
            return
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
            self.canvas.itemconfig(self.node_items[item_id]["shape"],
                                    outline=DEFAULT_OUTLINE, width=2)
        elif kind == "conn" and item_id in self.conn_items:
            conn = self.connections.get(item_id)
            if conn:
                self.canvas.itemconfig(self.conn_items[item_id],
                                        width=conn.line_width, dash=())
        self.selected = None

    def select_node(self, node_id: int) -> None:
        self.clear_selection()
        self.selected = ("node", node_id)
        self.canvas.itemconfig(self.node_items[node_id]["shape"],
                                outline=SELECT_OUTLINE, width=3)
        self._set_status(f"Nodo seleccionado: \"{self.nodes[node_id].text}\"")

    def select_connection(self, conn_id: int) -> None:
        self.clear_selection()
        self.selected = ("conn", conn_id)
        conn = self.connections[conn_id]
        self.canvas.itemconfig(self.conn_items[conn_id], width=conn.line_width + 2, dash=(6, 3))
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
        for item in self.canvas.find_overlapping(x - 1, y - 1, x + 1, y + 1):
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
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="Renombrar", command=lambda: self.rename_node(node_id))
        menu.add_command(label="Cambiar color del nodo",
                          command=lambda: self.change_node_color(node_id))
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
            node.text = new_text.strip()
            self._redraw_node(node)

    def change_node_color(self, node_id: int) -> None:
        node = self.nodes[node_id]
        _, hex_color = colorchooser.askcolor(color=node.color, title="Color del nodo", parent=self)
        if hex_color:
            node.color = hex_color
            self._redraw_node(node)

    def change_connection_color(self, conn_id: int) -> None:
        conn = self.connections[conn_id]
        _, hex_color = colorchooser.askcolor(color=conn.color, title="Color de la conexión", parent=self)
        if hex_color:
            conn.color = hex_color
            self.canvas.itemconfig(self.conn_items[conn_id], fill=hex_color)
            self._set_status(f"Color de conexión cambiado a {hex_color}.")

    def change_connection_width(self, conn_id: int, delta: int) -> None:
        conn = self.connections[conn_id]
        conn.line_width = max(1, min(10, conn.line_width + delta))
        selected = self.selected == ("conn", conn_id)
        self.canvas.itemconfig(self.conn_items[conn_id],
                                width=conn.line_width + (2 if selected else 0))

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

        self.clear_all()
        cx = self.canvas.winfo_width() / 2 or 500
        cy = self.canvas.winfo_height() / 2 or 350

        root_node = self.new_node(x=cx, y=cy, text=outline.text, color="#2b3a4a")
        self._place_outline_children(root_node, outline.children, cx, cy, 0, 2 * math.pi, level=1)
        self.clear_selection()
        self._set_status(f"Mapa generado con {len(self.nodes)} nodos a partir del texto.")
        return True

    def _place_outline_children(self, parent_node: Node, children: list,
                                 cx: float, cy: float, angle_start: float, angle_end: float,
                                 level: int, color: Optional[str] = None) -> None:
        if not children:
            return
        count = len(children)
        step = (angle_end - angle_start) / count
        radius = 210 * level

        for i, outline_child in enumerate(children):
            angle = angle_start + step * (i + 0.5)
            x = cx + radius * math.cos(angle)
            y = cy + radius * math.sin(angle)
            branch_color = color or next(self._color_cycle)

            child_node = self.new_node(x=x, y=y, text=outline_child.text, color=branch_color)
            conn = self.new_connection(parent_node.id, child_node.id)
            if conn is not None:
                conn.color = branch_color
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

    def clear_all(self) -> None:
        self.canvas.delete("all")
        self.nodes.clear()
        self.connections.clear()
        self.node_items.clear()
        self.conn_items.clear()
        self.selected = None
        self._node_id_seq = itertools.count(1)
        self._conn_id_seq = itertools.count(1)
