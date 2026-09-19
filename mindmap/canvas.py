"""Widget de canvas que dibuja y gestiona el mapa mental interactivo."""

import copy
import itertools
import math
import os
import shutil
import subprocess
import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox, simpledialog
from typing import Callable, Dict, Optional, Tuple

from .models import Connection, Node
from .svg_import import get_builtin_shape_points, import_svg_shape, list_builtin_shape_names
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
    "Ramas": {"node": "dot", "fill": "solid", "bg": "#ffffff", "root": "cloud"},
    "Angular": {"node": "box", "fill": "solid", "bg": "#faf6ef",
                "connector": "elbow", "connector_color": "#2b2b2b"},
}
DEFAULT_THEME = "Cuadrados"

SELECT_OUTLINE = "#ffd23f"

MIN_ZOOM = 0.3
MAX_ZOOM = 3.0


def _cubic_bezier_points(x1, y1, x2, y2, samples=28):
    """Puntos de una curva de Bézier cúbica de (x1,y1) a (x2,y2), con tangente
    horizontal en ambos extremos (como sale/entra un cable a una caja)."""
    dx = x2 - x1
    sign = 1 if dx >= 0 else -1
    offset = max(abs(dx) * 0.5, 30)
    c1x, c1y = x1 + sign * offset, y1
    c2x, c2y = x2 - sign * offset, y2

    pts = []
    for i in range(samples + 1):
        t = i / samples
        mt = 1 - t
        x = mt ** 3 * x1 + 3 * mt ** 2 * t * c1x + 3 * mt * t ** 2 * c2x + t ** 3 * x2
        y = mt ** 3 * y1 + 3 * mt ** 2 * t * c1y + 3 * mt * t ** 2 * c2y + t ** 3 * y2
        pts.extend([x, y])
    return pts


def _count_leaves(outline_node) -> int:
    """Cantidad de hojas en el subárbol de un OutlineNode (mínimo 1)."""
    if not outline_node.children:
        return 1
    return sum(_count_leaves(c) for c in outline_node.children)


def _split_by_weight(children):
    """Reparte una lista de OutlineNode en dos lados (derecha, izquierda),
    balanceando por cantidad de hojas y preservando el orden original en cada lado."""
    right, left = [], []
    right_w = left_w = 0
    for child in children:
        w = _count_leaves(child)
        if right_w <= left_w:
            right.append(child)
            right_w += w
        else:
            left.append(child)
            left_w += w
    return right, left


def _polygon_horizontal_extent(points, sign: int) -> float:
    """Distancia desde x=0 hasta el borde de un polígono normalizado
    (lista de (x, y) centrada en el origen), del lado que indica `sign`
    (+1 derecha, -1 izquierda), medida donde el contorno cruza y=0."""
    best = 0.0
    n = len(points)
    for i in range(n):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % n]
        if y1 == y2:
            continue
        if (y1 <= 0 <= y2) or (y2 <= 0 <= y1):
            t = (0 - y1) / (y2 - y1)
            x = x1 + t * (x2 - x1)
            if (sign > 0 and x > 0) or (sign < 0 and x < 0):
                best = max(best, abs(x))
    if best <= 0:
        for x, y in points:
            if (sign > 0 and x > 0) or (sign < 0 and x < 0):
                best = max(best, abs(x))
    return best if best > 0 else 0.5


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


def _cloud_points(cx, cy, rx, ry, lobes=8, bump=0.22, samples=160):
    """Puntos de un contorno abultado tipo "nube" alrededor de una elipse.

    El módulo del radio sólo abulta hacia afuera (nunca hacia adentro), para
    que el contorno se vea como lóbulos redondeados en vez de una estrella.
    """
    pts = []
    for i in range(samples):
        angle = 2 * math.pi * i / samples
        r_mod = 1 + bump * (0.5 + 0.5 * math.sin(lobes * angle))
        pts.append(cx + rx * r_mod * math.cos(angle))
        pts.append(cy + ry * r_mod * math.sin(angle))
    return pts


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
        self.selected_nodes: set = set()
        self._hidden_nodes: set = set()
        self._marquee_rect = None
        self._tooltip_window = None
        self._tooltip_node_id: Optional[int] = None
        self._tooltip_after = None
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
        self.canvas.bind("<Motion>", self._on_canvas_hover)
        self.canvas.bind("<Leave>", lambda e: self._hide_note_tooltip())
        self.canvas.bind("<Enter>", lambda e: self.canvas.focus_set())
        self.canvas.focus_set()

        self._space_held = False

        self._set_status(
            "Doble clic: crear nodo · Arrastrar: mover · Ctrl + clic o arrastrar sobre el "
            "lienzo: seleccionar varios nodos · Rueda del mouse: zoom · Espacio + arrastrar: "
            "desplazarse · Botón \"Conectar nodos\" (o Shift + arrastrar): crear una conexión "
            "· Clic derecho: opciones"
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
        self._hide_note_tooltip()
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
        self._apply_visibility()

    def _redraw_all_connections(self) -> None:
        for conn in self.connections.values():
            item = self.conn_items.get(conn.id)
            if item is None:
                continue
            self.canvas.coords(item, *self._connection_line_points(conn))
            selected = self.selected == ("conn", conn.id)
            width = conn.line_width * self._zoom + (3 if selected else 0)
            self.canvas.itemconfig(
                item, width=max(1, width), fill=self._connection_display_color(conn),
            )

    def _connection_display_color(self, conn: Connection) -> str:
        return THEMES[self.theme].get("connector_color") or conn.color

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
                self.canvas.itemconfig(self.conn_items[conn_id],
                                        fill=self._connection_display_color(self.connections[conn_id]))

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
            self.canvas.itemconfig(self.conn_items[conn_id],
                                    fill=self._connection_display_color(self.connections[conn_id]))
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
        if node.custom_shape:
            self._draw_node_custom(node, theme)
        elif node.shape == "root" and theme.get("root") == "cloud":
            self._draw_node_cloud(node)
        elif theme["node"] == "dot" and node.shape != "root":
            self._draw_node_dot(node)
        else:
            self._draw_node_box(node, theme)
        self._draw_note_indicator(node)
        self._draw_collapse_badge(node)

    def _draw_note_indicator(self, node: Node) -> None:
        """Ícono de "hoja" en la esquina del nodo cuando tiene una nota.

        La nota no se dibuja dentro del nodo a propósito: agrandar el nodo con
        su texto rompería el layout (es justo lo que hace que los "callout" de
        otras herramientas desplacen el resto del mapa)."""
        if not node.note.strip():
            return
        w = max(5.0, 6 * self._zoom)
        h = max(6.0, 7.5 * self._zoom)
        # Centrado sobre el borde superior: ahí no hay conexiones (que salen a
        # media altura) ni botón de colapsar, y funciona igual en todos los
        # temas, incluidos el punto y la nube.
        sx, sy = self._to_screen(node.x, node.y)
        cx, cy = sx, sy - (node.height / 2) * self._zoom
        tags = ("node", f"nid_{node.id}", f"note_{node.id}")

        self.canvas.create_rectangle(
            cx - w, cy - h, cx + w, cy + h,
            fill="#ffffff", outline=node.color, width=max(1, round(1.5 * self._zoom)),
            tags=tags,
        )
        line_width = max(1, round(self._zoom))
        for i in range(3):
            ly = cy - h * 0.45 + i * (h * 0.45)
            self.canvas.create_line(
                cx - w * 0.5, ly, cx + w * 0.5, ly,
                fill=node.color, width=line_width, tags=tags,
            )

    # ------------------------------------------------------------------ #
    # Jerarquía: colapsar / expandir ramas
    # ------------------------------------------------------------------ #
    def _children_of(self, node_id: int) -> list:
        """Hijos directos: los destinos de las conexiones que salen del nodo."""
        return [c.target_id for c in self.connections.values()
                if c.source_id == node_id and c.target_id in self.nodes]

    def _descendants_of(self, node_id: int) -> set:
        """Todo el subárbol por debajo del nodo (sin incluirlo)."""
        seen = set()
        pending = list(self._children_of(node_id))
        while pending:
            current = pending.pop()
            if current == node_id or current in seen:
                continue
            seen.add(current)
            pending.extend(self._children_of(current))
        return seen

    def _hidden_node_ids(self) -> set:
        hidden = set()
        for node_id, node in self.nodes.items():
            if node.collapsed:
                hidden |= self._descendants_of(node_id)
        return hidden

    def _apply_visibility(self) -> None:
        """Oculta o muestra nodos y conexiones según qué ramas estén colapsadas.
        Los items ocultos de Tk no se dibujan, no se pueden clicar ni salen al
        exportar la imagen, así que basta con cambiarles el estado."""
        hidden = self._hidden_node_ids()
        self._hidden_nodes = hidden

        stale = self.selected_nodes & hidden
        for node_id in stale:
            if node_id in self.node_items:
                self._apply_node_selection_style(node_id, False)
        if stale:
            self.selected_nodes -= stale
            self._sync_single_selection()

        for node_id in self.nodes:
            self.canvas.itemconfigure(
                f"nid_{node_id}", state="hidden" if node_id in hidden else "normal")
        for conn in self.connections.values():
            item = self.conn_items.get(conn.id)
            if item is None:
                continue
            conn_hidden = conn.source_id in hidden or conn.target_id in hidden
            self.canvas.itemconfigure(item, state="hidden" if conn_hidden else "normal")

    def _draw_collapse_badge(self, node: Node) -> None:
        """Círculo pequeño en el borde del nodo para colapsar/expandir su rama:
        un "–" cuando está expandida, y la cantidad de nodos ocultos cuando no."""
        children = self._children_of(node.id)
        if not children:
            return

        on_right = sum(1 for c in children if self.nodes[c].x >= node.x)
        side = 1 if on_right * 2 >= len(children) else -1
        ax, ay = self._node_anchor(node, side)
        radius = max(7.0, 9 * self._zoom)
        cx = ax + side * radius
        tags = ("node", f"nid_{node.id}", f"badge_{node.id}")

        self.canvas.create_oval(
            cx - radius, ay - radius, cx + radius, ay + radius,
            fill="#ffffff", outline=node.color, width=max(1, round(2 * self._zoom)),
            tags=tags,
        )
        if node.collapsed:
            self.canvas.create_text(
                cx, ay, text=str(len(self._descendants_of(node.id))), fill=node.color,
                font=self._font(scale=self._zoom * 0.85), tags=tags,
            )
        else:
            self.canvas.create_line(
                cx - radius * 0.45, ay, cx + radius * 0.45, ay,
                fill=node.color, width=max(1, round(2 * self._zoom)), tags=tags,
            )

    # ------------------------------------------------------------------ #
    # Notas adjuntas a un nodo
    # ------------------------------------------------------------------ #
    def edit_node_note(self, node_id: int) -> None:
        node = self.nodes[node_id]
        dialog = tk.Toplevel(self)
        dialog.title(f'Nota de "{node.text}"')
        dialog.geometry("520x400")
        dialog.minsize(360, 260)
        dialog.transient(self.winfo_toplevel())

        # Los botones van primero y anclados abajo para que no se salgan de la
        # ventana cuando el cuadro de texto crece.
        buttons = tk.Frame(dialog)
        buttons.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=8)

        tk.Label(
            dialog, justify="left",
            text="Nota del nodo. No se dibuja en el mapa: el nodo muestra un ícono\n"
                 "y la nota se lee al pasar el mouse por encima.",
        ).pack(anchor="w", padx=10, pady=(10, 4))

        text_frame = tk.Frame(dialog)
        text_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=4)
        text_widget = tk.Text(text_frame, wrap="word", undo=True, height=10)
        scrollbar = tk.Scrollbar(text_frame, orient=tk.VERTICAL, command=text_widget.yview)
        text_widget.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        text_widget.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        text_widget.insert("1.0", node.note)
        text_widget.focus_set()

        def save():
            self.set_node_note(node_id, text_widget.get("1.0", "end"))
            dialog.destroy()

        def remove():
            self.set_node_note(node_id, "")
            dialog.destroy()

        tk.Button(buttons, text="Guardar", command=save).pack(side=tk.RIGHT, padx=4)
        tk.Button(buttons, text="Cancelar", command=dialog.destroy).pack(side=tk.RIGHT)
        if node.note.strip():
            tk.Button(buttons, text="Quitar nota", command=remove).pack(side=tk.LEFT)

        dialog.grab_set()

    def set_node_note(self, node_id: int, note: str) -> None:
        node = self.nodes[node_id]
        new_note = note.strip()
        if new_note == node.note:
            return
        self._snapshot_undo()
        node.note = new_note
        self._redraw_node(node)
        self._set_status(f'Nota {"guardada en" if new_note else "quitada de"} "{node.text}".')

    def _note_node_id_at(self, x: float, y: float) -> Optional[int]:
        for item in self.canvas.find_overlapping(x - 2, y - 2, x + 2, y + 2):
            for tag in self.canvas.gettags(item):
                if tag.startswith("note_"):
                    return int(tag.split("_", 1)[1])
        return None

    def _on_canvas_hover(self, event) -> None:
        """Muestra la nota del nodo bajo el cursor, como hace Freeplane: poder
        leerla sin abrir nada es lo que evita que las notas se olviden."""
        node_id = self._node_id_at(event.x, event.y)
        if node_id is None or not self.nodes[node_id].note.strip():
            self._hide_note_tooltip()
            return
        if node_id == self._tooltip_node_id:
            return
        self._hide_note_tooltip()
        self._tooltip_node_id = node_id
        self._tooltip_after = self.after(
            450, lambda: self._show_note_tooltip(node_id, event.x_root, event.y_root))

    def _show_note_tooltip(self, node_id: int, x_root: int, y_root: int) -> None:
        node = self.nodes.get(node_id)
        if node is None or not node.note.strip() or self._tooltip_node_id != node_id:
            return
        tip = tk.Toplevel(self)
        tip.overrideredirect(True)
        tip.attributes("-topmost", True)
        tk.Label(
            tip, text=node.note, justify="left", wraplength=320,
            background="#fdf6d8", relief="solid", borderwidth=1, padx=8, pady=6,
        ).pack()
        tip.geometry(f"+{x_root + 14}+{y_root + 18}")
        self._tooltip_window = tip

    def _hide_note_tooltip(self) -> None:
        if self._tooltip_after is not None:
            self.after_cancel(self._tooltip_after)
            self._tooltip_after = None
        if self._tooltip_window is not None:
            self._tooltip_window.destroy()
            self._tooltip_window = None
        self._tooltip_node_id = None

    def _move_group_for(self, node_ids: set) -> set:
        """Al arrastrar un nodo colapsado, su rama oculta tiene que viajar con él
        para que siga en su sitio cuando se vuelva a expandir."""
        group = set(node_ids)
        for node_id in node_ids:
            if self.nodes[node_id].collapsed:
                group |= self._descendants_of(node_id)
        return group

    def toggle_collapse(self, node_id: int) -> None:
        node = self.nodes[node_id]
        if not self._children_of(node_id):
            return
        self._snapshot_undo()
        node.collapsed = not node.collapsed
        self._redraw_node(node)
        self._apply_visibility()
        if node.collapsed:
            self._set_status(
                f'Rama "{node.text}" colapsada: {len(self._descendants_of(node_id))} nodos ocultos.')
        else:
            self._set_status(f'Rama "{node.text}" expandida.')

    def collapse_all(self) -> None:
        targets = [n for n in self.nodes.values() if self._children_of(n.id) and not n.collapsed]
        if not targets:
            return
        self._snapshot_undo()
        for node in targets:
            node.collapsed = True
        self._redraw_all()
        self._set_status("Todas las ramas colapsadas.")

    def expand_all(self) -> None:
        targets = [n for n in self.nodes.values() if n.collapsed]
        if not targets:
            return
        self._snapshot_undo()
        for node in targets:
            node.collapsed = False
        self._redraw_all()
        self._set_status("Todas las ramas expandidas.")

    def _draw_node_custom(self, node: Node, theme: dict) -> None:
        base_font = self._font(node)
        lines = node.text.split("\n") or [""]
        text_w = max(base_font.measure(line) for line in lines)
        is_root = node.shape == "root"
        text_h = (26 if is_root else 20) * len(lines)
        pad_x, pad_y = (34, 20) if is_root else (16, 10)
        min_w, min_h = (140, 60) if is_root else (60, 44)
        tag = f"nid_{node.id}"

        node.width = max(min_w, text_w + 2 * pad_x)
        node.height = max(min_h, text_h + 2 * pad_y)

        zoom = self._zoom
        sx, sy = self._to_screen(node.x, node.y)
        sw, sh = node.width * zoom, node.height * zoom

        outline_mode = theme["fill"] == "outline"
        fill_color = "#ffffff" if outline_mode else node.color
        outline_color = node.color if outline_mode else "#2b2b2b"
        outline_width = max(2, round((3 if outline_mode else 1.5) * zoom))
        text_color = node.color if outline_mode else "#ffffff"

        poly = []
        for nx, ny in node.custom_shape:
            poly.extend([sx + nx * sw, sy + ny * sh])

        shape_item = self.canvas.create_polygon(
            poly, fill=fill_color, outline=outline_color, width=outline_width,
            smooth=False, tags=("node", tag),
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

    def _draw_node_cloud(self, node: Node) -> None:
        base_font = self._font(node)
        lines = node.text.split("\n") or [""]
        text_w = max(base_font.measure(line) for line in lines)
        text_h = 26 * len(lines)
        tag = f"nid_{node.id}"

        node.width = max(190, text_w + 100)
        node.height = max(120, text_h + 80)

        zoom = self._zoom
        sx, sy = self._to_screen(node.x, node.y)
        rx, ry = (node.width / 2) * zoom, (node.height / 2) * zoom
        outline_width = max(2, round(2 * zoom))

        shape_item = self.canvas.create_polygon(
            _cloud_points(sx, sy, rx, ry),
            fill=node.color, outline="#2b2b2b", width=outline_width,
            smooth=True, splinesteps=6, tags=("node", tag),
        )
        render_font = self._font(node, scale=zoom)
        text_item = self.canvas.create_text(
            sx, sy, text=node.text, fill="#ffffff",
            font=render_font, tags=("node", "node-text", tag),
            width=max(1, rx * 1.1), justify="center",
        )
        self.node_items[node.id] = {
            "shape": shape_item, "text": text_item,
            "outline": ("#2b2b2b", outline_width),
        }
        self.canvas.tag_bind(tag, "<Enter>", lambda e: self.canvas.config(cursor="fleur"))
        self.canvas.tag_bind(tag, "<Leave>", lambda e: self.canvas.config(cursor=""))

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
        was_selected = node.id in self.selected_nodes
        self.canvas.delete(f"nid_{node.id}")
        self.node_items.pop(node.id, None)
        self._draw_node(node)
        if was_selected:
            self._apply_node_selection_style(node.id, True)
        if node.id in self._hidden_nodes:
            self.canvas.itemconfigure(f"nid_{node.id}", state="hidden")
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

    def import_node_shape(self, node_id: int) -> None:
        path = filedialog.askopenfilename(
            title="Importar forma SVG", filetypes=[("Imagen SVG", "*.svg")], parent=self,
        )
        if not path:
            return
        try:
            points = import_svg_shape(path)
        except ValueError as e:
            messagebox.showerror("No se pudo importar la forma", str(e), parent=self)
            return
        node = self.nodes[node_id]
        self._snapshot_undo()
        node.custom_shape = [list(p) for p in points]
        self._redraw_node(node)

    def apply_builtin_node_shape(self, node_id: int, shape_name: str) -> None:
        try:
            points = get_builtin_shape_points(shape_name)
        except ValueError as e:
            messagebox.showerror("No se pudo aplicar la forma", str(e), parent=self)
            return
        node = self.nodes[node_id]
        self._snapshot_undo()
        node.custom_shape = [list(p) for p in points]
        self._redraw_node(node)

    def clear_node_shape(self, node_id: int) -> None:
        node = self.nodes[node_id]
        self._snapshot_undo()
        node.custom_shape = None
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

        self.selected_nodes.discard(node_id)
        self._sync_single_selection()
        self._apply_visibility()

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
        # el origen pasa a tener hijos: hay que dibujarle el botón de colapsar
        self._redraw_node(self.nodes[source_id])
        self._apply_visibility()
        self.select_connection(conn.id)
        return conn

    def _node_anchor(self, node: Node, dx_sign: int) -> Tuple[float, float]:
        """Punto de anclaje en el borde del nodo, del lado que mira hacia dx_sign
        (+1 = derecha, -1 = izquierda), para que la conexión nazca/llegue al
        borde en vez de atravesar el centro."""
        theme = THEMES[self.theme]
        sx, sy = self._to_screen(node.x, node.y)
        if node.custom_shape:
            half = _polygon_horizontal_extent(node.custom_shape, dx_sign) * node.width * self._zoom
        elif theme["node"] == "dot" and node.shape != "root":
            text_side_sign = 1 if self._dot_text_side(node) == "right" else -1
            if dx_sign == text_side_sign:
                # el texto queda de este mismo lado: hay que pasar de largo,
                # si no la línea nace encima de las letras en vez de en el punto
                half = (node.width - 7 + 6) * self._zoom
            else:
                half = 7 * self._zoom
        else:
            half = (node.width / 2) * self._zoom
        return sx + dx_sign * half, sy

    def _connection_line_points(self, conn: Connection):
        a = self.nodes[conn.source_id]
        b = self.nodes[conn.target_id]
        dx_sign = 1 if b.x >= a.x else -1
        x1, y1 = self._node_anchor(a, dx_sign)
        x2, y2 = self._node_anchor(b, -dx_sign)

        if THEMES[self.theme].get("connector") == "elbow":
            xm = (x1 + x2) / 2
            return [x1, y1, xm, y1, xm, y2, x2, y2]

        return _cubic_bezier_points(x1, y1, x2, y2)

    def _draw_connection(self, conn: Connection) -> None:
        tag = f"cid_{conn.id}"
        line = self.canvas.create_line(
            *self._connection_line_points(conn),
            fill=self._connection_display_color(conn), width=max(1, conn.line_width * self._zoom),
            smooth=False, capstyle=tk.ROUND, joinstyle=tk.ROUND,
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
        source_id = self.connections[conn_id].source_id
        self.canvas.delete(self.conn_items.pop(conn_id))
        del self.connections[conn_id]
        if self.selected == ("conn", conn_id):
            self.selected = None
        if source_id in self.nodes:
            # puede haberse quedado sin hijos: hay que quitarle el botón de colapsar
            self._redraw_node(self.nodes[source_id])
        self._apply_visibility()

    # ------------------------------------------------------------------ #
    # Selección visual
    # ------------------------------------------------------------------ #
    def clear_selection(self) -> None:
        for node_id in self.selected_nodes:
            if node_id in self.node_items:
                self._apply_node_selection_style(node_id, False)
        self.selected_nodes = set()
        if self.selected is not None and self.selected[0] == "conn":
            item_id = self.selected[1]
            conn = self.connections.get(item_id)
            if conn and item_id in self.conn_items:
                self.canvas.itemconfig(self.conn_items[item_id],
                                        width=max(1, conn.line_width * self._zoom))
        self.selected = None

    def _sync_single_selection(self) -> None:
        """Mantiene self.selected coherente con self.selected_nodes: apunta al
        único nodo seleccionado, o queda en None si hay 0 o varios."""
        if len(self.selected_nodes) == 1:
            self.selected = ("node", next(iter(self.selected_nodes)))
        elif self.selected is not None and self.selected[0] == "node":
            self.selected = None

    def select_node(self, node_id: int) -> None:
        self.clear_selection()
        self.selected = ("node", node_id)
        self.selected_nodes = {node_id}
        self._apply_node_selection_style(node_id, True)
        self._set_status(f"Nodo seleccionado: \"{self.nodes[node_id].text}\"")

    def select_connection(self, conn_id: int) -> None:
        self.clear_selection()
        self.selected = ("conn", conn_id)
        conn = self.connections[conn_id]
        self.canvas.itemconfig(self.conn_items[conn_id],
                                width=max(1, conn.line_width * self._zoom) + 3)
        self._set_status("Conexión seleccionada. Usa el botón de color para cambiarla.")

    def toggle_node_selection(self, node_id: int) -> None:
        """Ctrl+clic: agrega o quita un nodo de la selección múltiple sin
        afectar a los demás nodos seleccionados."""
        if self.selected is not None and self.selected[0] == "conn":
            self.clear_selection()
        if node_id in self.selected_nodes:
            self.selected_nodes.discard(node_id)
            self._apply_node_selection_style(node_id, False)
        else:
            self.selected_nodes.add(node_id)
            self._apply_node_selection_style(node_id, True)
        self._sync_single_selection()
        if self.selected_nodes:
            self._set_status(f"{len(self.selected_nodes)} nodo(s) seleccionados.")
        else:
            self._set_status("Selección vacía.")

    def _apply_multi_selection(self, node_ids: set, additive: bool) -> None:
        """Aplica el resultado de un recuadro de selección (marquee): reemplaza
        la selección actual, o la amplía si additive=True (Ctrl+arrastrar)."""
        new_selection = (self.selected_nodes | node_ids) if additive else set(node_ids)
        added = new_selection - self.selected_nodes
        removed = self.selected_nodes - new_selection
        self.selected_nodes = new_selection
        for node_id in added:
            if node_id in self.node_items:
                self._apply_node_selection_style(node_id, True)
        for node_id in removed:
            if node_id in self.node_items:
                self._apply_node_selection_style(node_id, False)
        self._sync_single_selection()
        if self.selected_nodes:
            self._set_status(f"{len(self.selected_nodes)} nodo(s) seleccionados.")
        else:
            self._set_status("Selección vacía.")

    def change_selected_nodes_color(self) -> None:
        if not self.selected_nodes:
            return
        sample = self.nodes[next(iter(self.selected_nodes))]
        _, hex_color = colorchooser.askcolor(
            color=sample.color, title="Color de los nodos seleccionados", parent=self,
        )
        if not hex_color:
            return
        self._snapshot_undo()
        for node_id in list(self.selected_nodes):
            node = self.nodes[node_id]
            node.color = hex_color
            self._redraw_node(node)
        self._set_status(f"Color cambiado en {len(self.selected_nodes)} nodos.")

    def delete_selected(self) -> None:
        if len(self.selected_nodes) > 1:
            ids = list(self.selected_nodes)
            self._snapshot_undo()
            previous_suspend = self._suspend_undo
            self._suspend_undo = True
            try:
                for node_id in ids:
                    self.delete_node(node_id)
            finally:
                self._suspend_undo = previous_suspend
            self._set_status(f"{len(ids)} nodos eliminados.")
            return
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

    def _badge_node_id_at(self, x: float, y: float) -> Optional[int]:
        for item in self.canvas.find_overlapping(x - 2, y - 2, x + 2, y + 2):
            for tag in self.canvas.gettags(item):
                if tag.startswith("badge_"):
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

        self._hide_note_tooltip()

        badge_node_id = self._badge_node_id_at(event.x, event.y)
        if badge_node_id is not None:
            self.toggle_collapse(badge_node_id)
            self._drag = {"mode": None, "node_id": None, "last_x": event.x, "last_y": event.y}
            return

        note_node_id = self._note_node_id_at(event.x, event.y)
        if note_node_id is not None:
            self.edit_node_note(note_node_id)
            self._drag = {"mode": None, "node_id": None, "last_x": event.x, "last_y": event.y}
            return

        shift_held = bool(event.state & 0x0001)
        ctrl_held = bool(event.state & 0x0004)

        if node_id is not None:
            if shift_held:
                # Shift siempre sirve para conectar, sin importar la selección múltiple.
                self.select_node(node_id)
                self._drag = {"mode": "connect", "node_id": node_id,
                               "last_x": event.x, "last_y": event.y}
                node = self.nodes[node_id]
                sx, sy = self._to_screen(node.x, node.y)
                self._connect_temp_line = self.canvas.create_line(
                    sx, sy, event.x, event.y,
                    fill="#999999", width=2, dash=(4, 2),
                )
                return
            if ctrl_held:
                self.toggle_node_selection(node_id)
                self._drag = {"mode": None, "node_id": None, "last_x": event.x, "last_y": event.y}
                return
            if node_id in self.selected_nodes and len(self.selected_nodes) > 1:
                # El nodo ya forma parte de una selección múltiple: arrastrar todo el grupo.
                self._snapshot_undo()
                self._drag = {"mode": "move", "node_id": node_id,
                               "group": self._move_group_for(self.selected_nodes),
                               "last_x": event.x, "last_y": event.y}
                return
            self.select_node(node_id)
            self._snapshot_undo()
            self._drag = {"mode": "move", "node_id": node_id,
                           "group": self._move_group_for({node_id}),
                           "last_x": event.x, "last_y": event.y}
            return

        conn_id = self._conn_id_at(event.x, event.y)
        if conn_id is not None:
            self.select_connection(conn_id)
            self._drag = {"mode": None, "node_id": None, "last_x": event.x, "last_y": event.y}
            return

        if not ctrl_held:
            self.clear_selection()
        self._drag = {"mode": "marquee", "node_id": None, "last_x": event.x, "last_y": event.y,
                       "start_x": event.x, "start_y": event.y, "additive": ctrl_held}
        self._marquee_rect = self.canvas.create_rectangle(
            event.x, event.y, event.x, event.y,
            outline="#5b8def", dash=(4, 2), width=1,
        )

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
            group = self._drag.get("group") or {self._drag["node_id"]}
            dx = (event.x - self._drag["last_x"]) / self._zoom
            dy = (event.y - self._drag["last_y"]) / self._zoom
            screen_dx = event.x - self._drag["last_x"]
            screen_dy = event.y - self._drag["last_y"]
            for node_id in group:
                node = self.nodes[node_id]
                node.x += dx
                node.y += dy
                self.canvas.move(f"nid_{node_id}", screen_dx, screen_dy)
                self._update_connections_for_node(node_id)
            self._drag["last_x"], self._drag["last_y"] = event.x, event.y
        elif mode == "connect" and self._connect_temp_line is not None:
            node = self.nodes[self._drag["node_id"]]
            sx, sy = self._to_screen(node.x, node.y)
            self.canvas.coords(self._connect_temp_line, sx, sy, event.x, event.y)
            target_id = self._node_id_at(event.x, event.y)
            self.canvas.config(cursor="hand2" if target_id not in (None, self._drag["node_id"])
                                else "X_cursor")
        elif mode == "marquee":
            x0, y0 = self._drag["start_x"], self._drag["start_y"]
            self.canvas.coords(self._marquee_rect, x0, y0, event.x, event.y)

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
            return
        if mode == "marquee":
            x0, y0 = self._drag["start_x"], self._drag["start_y"]
            x1, y1 = event.x, event.y
            if self._marquee_rect is not None:
                self.canvas.delete(self._marquee_rect)
                self._marquee_rect = None
            rx0, rx1 = sorted((x0, x1))
            ry0, ry1 = sorted((y0, y1))
            if rx1 - rx0 > 3 or ry1 - ry0 > 3:
                matched = set()
                for node_id, node in self.nodes.items():
                    if node_id in self._hidden_nodes:
                        continue
                    sx, sy = self._to_screen(node.x, node.y)
                    hw, hh = (node.width / 2) * self._zoom, (node.height / 2) * self._zoom
                    if sx + hw >= rx0 and sx - hw <= rx1 and sy + hh >= ry0 and sy - hh <= ry1:
                        matched.add(node_id)
                self._apply_multi_selection(matched, additive=self._drag.get("additive", False))
            self._drag = {"mode": None, "node_id": None, "last_x": 0, "last_y": 0}
            return
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
            if node_id in self.selected_nodes and len(self.selected_nodes) > 1:
                self._show_multi_node_menu(event)
            else:
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
        note_label = "Editar nota..." if node.note.strip() else "Agregar nota..."
        menu.add_command(label=note_label, command=lambda: self.edit_node_note(node_id))
        shape_label = "Convertir en nodo de rama" if node.shape == "root" else "Convertir en nodo central"
        menu.add_command(label=shape_label, command=lambda: self.toggle_node_shape(node_id))

        hidden_count = len(self._descendants_of(node_id))
        if hidden_count:
            collapse_label = ("Expandir rama" if node.collapsed
                               else f"Colapsar rama ({hidden_count} nodos)")
            menu.add_command(label=collapse_label, command=lambda: self.toggle_collapse(node_id))

        shape_menu = tk.Menu(menu, tearoff=0)
        shape_menu.add_command(label="Normal (según el tema)",
                                command=lambda: self.clear_node_shape(node_id))
        shape_menu.add_separator()
        for shape_name in list_builtin_shape_names():
            shape_menu.add_command(
                label=shape_name,
                command=lambda name=shape_name: self.apply_builtin_node_shape(node_id, name),
            )
        shape_menu.add_separator()
        shape_menu.add_command(label="Importar desde archivo SVG...",
                                command=lambda: self.import_node_shape(node_id))
        menu.add_cascade(label="Forma del nodo", menu=shape_menu)

        menu.add_separator()
        menu.add_command(label="Eliminar nodo", command=lambda: self.delete_node(node_id))
        menu.tk_popup(event.x_root, event.y_root)

    def _show_multi_node_menu(self, event) -> None:
        count = len(self.selected_nodes)
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label=f"Cambiar color de los {count} nodos",
                          command=self.change_selected_nodes_color)
        menu.add_separator()
        menu.add_command(label=f"Eliminar {count} nodos", command=self.delete_selected)
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
        menu.add_separator()
        menu.add_command(label="Expandir todo", command=self.expand_all)
        menu.add_command(label="Colapsar todo", command=self.collapse_all)
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
            self.canvas.itemconfig(self.conn_items[conn_id], fill=self._connection_display_color(conn))
            if THEMES[self.theme].get("connector_color"):
                self._set_status(
                    f"Color guardado ({hex_color}), pero el tema \"{self.theme}\" usa un color fijo "
                    "para las conexiones."
                )
            else:
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

            # Reparte las ramas principales entre el lado derecho e izquierdo
            # (balanceando por tamaño de cada subárbol) en vez de un círculo
            # completo: así las ramas no se cruzan entre sí.
            right_children, left_children = _split_by_weight(outline.children)
            leaf_spacing = 60
            right_height = sum(_count_leaves(c) for c in right_children) * leaf_spacing
            left_height = sum(_count_leaves(c) for c in left_children) * leaf_spacing

            self._layout_subtree(root_node, right_children, +1, 1, cy - right_height / 2,
                                  None, leaf_spacing)
            self._layout_subtree(root_node, left_children, -1, 1, cy - left_height / 2,
                                  None, leaf_spacing)

            self.clear_selection()
        finally:
            self._suspend_undo = False
        self._set_status(f"Mapa generado con {len(self.nodes)} nodos a partir del texto.")
        return True

    def _leaf_box_width(self, text: str) -> float:
        """Ancho aproximado (sin zoom) que tendrá una caja de nodo de rama con este texto."""
        font = self._font()
        lines = text.split("\n") or [""]
        text_w = max(font.measure(line) for line in lines)
        return max(50, text_w + 32)

    def _layout_subtree(self, parent_node: Node, outline_children: list, x_dir: int,
                         level: int, top_y: float, color: Optional[str],
                         leaf_spacing: float = 60, min_gap: float = 60) -> None:
        """Coloca outline_children (y sus descendientes) en una columna vertical
        hacia x_dir (+1 derecha, -1 izquierda), apilados sin superponerse: cada
        hijo recibe una franja vertical proporcional al tamaño de su propio
        subárbol (cantidad de hojas), y su distancia horizontal al padre se
        calcula con el ancho real de ambas cajas para no encimarlas."""
        if not outline_children:
            return
        slot_start = top_y
        branch_width = max(1, 6 - (level - 1))

        for outline_child in outline_children:
            leaves = _count_leaves(outline_child)
            slot_height = leaves * leaf_spacing
            child_width_estimate = self._leaf_box_width(outline_child.text)
            gap = parent_node.width / 2 + min_gap + child_width_estimate / 2
            child_x = parent_node.x + x_dir * gap
            child_y = slot_start + slot_height / 2
            branch_color = color or next(self._color_cycle)

            child_node = self.new_node(x=child_x, y=child_y, text=outline_child.text, color=branch_color)
            conn = self.new_connection(parent_node.id, child_node.id)
            if conn is not None:
                conn.color = branch_color
                conn.line_width = branch_width
                self.canvas.itemconfig(self.conn_items[conn.id],
                                        fill=self._connection_display_color(conn),
                                        width=max(1, branch_width * self._zoom))

            self._layout_subtree(child_node, outline_child.children, x_dir, level + 1,
                                  slot_start, branch_color, leaf_spacing, min_gap)
            slot_start += slot_height

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
        # los nodos se dibujaron antes de existir las conexiones: hay que
        # redibujarlos para que aparezcan los botones de colapsar y se aplique
        # el estado colapsado que venía guardado
        self._redraw_all()

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
        self._hide_note_tooltip()
        self.canvas.delete("all")
        self.nodes.clear()
        self.connections.clear()
        self.node_items.clear()
        self.conn_items.clear()
        self.selected = None
        self.selected_nodes = set()
        self._hidden_nodes = set()
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
