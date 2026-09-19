"""Panel lateral que lista todas las notas del mapa.

Sirve de índice navegable: un clic lleva al nodo (expandiendo su rama si hacía
falta) y el panel queda abierto, para poder leer una nota mientras se recorre el
mapa en vez de abrir y cerrar una por vez.
"""

import tkinter as tk
from tkinter import ttk

REFRESH_MS = 400
PREVIEW_LINES = 2

BG = "#ffffff"
ROW_BG = "#ffffff"
ROW_HOVER_BG = "#eef3fb"
TITLE_FG = "#1f2933"
PREVIEW_FG = "#6b7580"
HINT_FG = "#8a94a0"


def _preview(note: str) -> str:
    lines = [line.strip() for line in note.strip().splitlines() if line.strip()]
    text = " ".join(lines[:PREVIEW_LINES])
    return text[:140] + "…" if len(text) > 140 else text


class NotesPanel(ttk.Frame):
    def __init__(self, master, mind_canvas, on_close=None, **kwargs):
        super().__init__(master, **kwargs)
        self.mind_canvas = mind_canvas
        self.on_close = on_close or (lambda: None)
        self._state = None
        self._after_id = None
        self.filter_var = tk.StringVar()

        header = ttk.Frame(self, padding=(8, 6, 4, 2))
        header.pack(fill=tk.X)
        ttk.Label(header, text="Notas del mapa", font=("Helvetica", 11, "bold")).pack(side=tk.LEFT)
        ttk.Button(header, text="✕", width=3, command=self.on_close).pack(side=tk.RIGHT)

        search = ttk.Frame(self, padding=(8, 2, 8, 6))
        search.pack(fill=tk.X)
        self.search_entry = ttk.Entry(search, textvariable=self.filter_var)
        self.search_entry.pack(fill=tk.X)
        self.filter_var.trace_add("write", lambda *_: self.refresh())

        list_frame = ttk.Frame(self)
        list_frame.pack(fill=tk.BOTH, expand=True)
        self._list_canvas = tk.Canvas(list_frame, highlightthickness=0, width=270, bg=BG)
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self._list_canvas.yview)
        self._list_canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self._list_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.rows = tk.Frame(self._list_canvas, bg=BG)
        self._rows_window = self._list_canvas.create_window((0, 0), window=self.rows, anchor="nw")
        self.rows.bind(
            "<Configure>",
            lambda e: self._list_canvas.configure(scrollregion=self._list_canvas.bbox("all")))
        self._list_canvas.bind(
            "<Configure>",
            lambda e: self._list_canvas.itemconfigure(self._rows_window, width=e.width))
        self._list_canvas.bind_all("<Button-4>", self._on_wheel, add="+")
        self._list_canvas.bind_all("<Button-5>", self._on_wheel, add="+")

        ttk.Label(
            self, text="Clic: ir al nodo · Doble clic: editar",
            foreground=HINT_FG, padding=(8, 4),
        ).pack(fill=tk.X, side=tk.BOTTOM)

        self.refresh(force=True)

    # ------------------------------------------------------------------ #
    def start(self) -> None:
        if self._after_id is None:
            self._tick()

    def stop(self) -> None:
        if self._after_id is not None:
            self.after_cancel(self._after_id)
            self._after_id = None

    def _tick(self) -> None:
        self.refresh()
        self._after_id = self.after(REFRESH_MS, self._tick)

    def refresh(self, force: bool = False) -> None:
        """Reconstruye la lista sólo si cambió algo.

        Se compara una firma barata en vez de avisar desde cada punto que puede
        cambiar una nota (editarla, renombrar o borrar el nodo, recolorear,
        deshacer, abrir otro mapa...): olvidar uno de esos caminos dejaría el
        panel desactualizado en silencio.
        """
        notes = self.mind_canvas.nodes_with_notes()
        query = self.filter_var.get().strip().lower()
        state = (tuple(notes), query)
        if not force and state == self._state:
            return
        self._state = state

        for child in self.rows.winfo_children():
            child.destroy()

        visible = [n for n in notes
                   if not query or query in n[1].lower() or query in n[2].lower()]
        if not visible:
            message = ("Ninguna nota coincide con la búsqueda."
                       if notes else "Ningún nodo tiene notas todavía.")
            tk.Label(self.rows, text=message, bg=BG, fg=PREVIEW_FG,
                      wraplength=230, justify="left").pack(anchor="w", padx=10, pady=12)
            return

        for node_id, text, note, color in visible:
            self._build_row(node_id, text, note, color)

    def _build_row(self, node_id: int, text: str, note: str, color: str) -> None:
        row = tk.Frame(self.rows, bg=ROW_BG, cursor="hand2")
        row.pack(fill=tk.X, pady=(0, 1))
        tk.Frame(row, bg=color, width=5).pack(side=tk.LEFT, fill=tk.Y)

        body = tk.Frame(row, bg=ROW_BG, padx=8, pady=6)
        body.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tk.Label(body, text=text, bg=ROW_BG, fg=TITLE_FG, font=("Helvetica", 10, "bold"),
                  anchor="w", justify="left", wraplength=215).pack(fill=tk.X)
        tk.Label(body, text=_preview(note), bg=ROW_BG, fg=PREVIEW_FG,
                  anchor="w", justify="left", wraplength=215).pack(fill=tk.X)

        widgets = [row, body] + list(body.winfo_children())
        for widget in widgets:
            widget.bind("<Button-1>", lambda e, nid=node_id: self.go_to_node(nid))
            widget.bind("<Double-Button-1>", lambda e, nid=node_id: self.edit_note(nid))
            widget.bind("<Enter>", lambda e, ws=widgets: self._set_row_bg(ws, ROW_HOVER_BG))
            widget.bind("<Leave>", lambda e, ws=widgets: self._set_row_bg(ws, ROW_BG))

    def go_to_node(self, node_id: int) -> None:
        self.mind_canvas.reveal_node(node_id)

    def edit_note(self, node_id: int) -> None:
        self.mind_canvas.edit_node_note(node_id)

    @staticmethod
    def _set_row_bg(widgets, color: str) -> None:
        for widget in widgets:
            widget.configure(bg=color)

    def _on_wheel(self, event) -> None:
        # El binding es global, así que hay que confirmar que el puntero esté
        # dentro del panel: si no, la rueda sobre el mapa (que hace zoom)
        # scrollearía también esta lista.
        widget = self.winfo_containing(event.x_root, event.y_root)
        while widget is not None:
            if widget is self:
                self._list_canvas.yview_scroll(-1 if event.num == 4 else 1, "units")
                return
            widget = getattr(widget, "master", None)

    def destroy(self) -> None:
        self.stop()
        super().destroy()
