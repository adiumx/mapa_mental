"""Ventana principal de la aplicación de mapas mentales."""

import json
import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox, ttk

from .canvas import DEFAULT_PALETTE, DEFAULT_THEME, MindMapCanvas, PALETTES, THEMES
from .notes_panel import NotesPanel


class MindMapApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Mapas Mentales")
        self.geometry("1100x700")
        self.minsize(700, 450)

        self.current_file = None
        self.status_var = tk.StringVar(value="Listo.")

        self.notes_panel = None
        self.notes_panel_var = tk.BooleanVar(value=False)

        self._build_menu()
        self._build_toolbar()
        # El canvas vive dentro de un panel dividido para poder acoplarle el
        # panel de notas a la derecha con un divisor arrastrable.
        self._paned = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        self.mind_canvas = MindMapCanvas(
            self._paned, on_status=self._set_status,
            on_connect_mode_change=self._on_connect_mode_change,
        )
        self._paned.add(self.mind_canvas, weight=1)
        self._paned.pack(fill=tk.BOTH, expand=True)
        self._build_status_bar()

        self.update_idletasks()  # asegura que el canvas ya tenga su tamaño real antes de centrar el nodo
        self.mind_canvas.reset_to_default()

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------ #
    def _build_menu(self):
        menubar = tk.Menu(self)

        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Nuevo mapa", command=self.new_map, accelerator="Ctrl+N")
        file_menu.add_command(label="Abrir...", command=self.open_map, accelerator="Ctrl+O")
        file_menu.add_command(label="Guardar", command=self.save_map, accelerator="Ctrl+S")
        file_menu.add_command(label="Guardar como...", command=self.save_map_as)
        file_menu.add_separator()
        file_menu.add_command(label="Generar desde texto / Markdown...", command=self._import_text_dialog)
        file_menu.add_command(label="Exportar como imagen...", command=self.export_image)
        file_menu.add_separator()
        file_menu.add_command(label="Salir", command=self._on_close)
        menubar.add_cascade(label="Archivo", menu=file_menu)

        edit_menu = tk.Menu(menubar, tearoff=0)
        edit_menu.add_command(label="Deshacer", command=self._undo, accelerator="Ctrl+Z")
        edit_menu.add_command(label="Rehacer", command=self._redo, accelerator="Ctrl+Y")
        menubar.add_cascade(label="Editar", menu=edit_menu)

        view_menu = tk.Menu(menubar, tearoff=0)
        view_menu.add_command(label="Ajustar a la pantalla", command=self._zoom_to_fit,
                               accelerator="Ctrl+0")
        view_menu.add_command(label="Reorganizar mapa", command=self._relayout_map,
                               accelerator="Ctrl+R")
        view_menu.add_separator()
        view_menu.add_checkbutton(label="Panel de notas", variable=self.notes_panel_var,
                                   command=self._toggle_notes_panel)
        menubar.add_cascade(label="Ver", menu=view_menu)

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="Instrucciones", command=self._show_help)
        menubar.add_cascade(label="Ayuda", menu=help_menu)

        self.config(menu=menubar)

        self.bind_all("<Control-n>", lambda e: self.new_map())
        self.bind_all("<Control-o>", lambda e: self.open_map())
        self.bind_all("<Control-s>", lambda e: self.save_map())
        self.bind_all("<Control-z>", lambda e: self._undo())
        self.bind_all("<Control-y>", lambda e: self._redo())
        self.bind_all("<Control-Shift-Z>", lambda e: self._redo())
        self.bind_all("<Control-0>", lambda e: self._zoom_to_fit())
        self.bind_all("<Control-r>", lambda e: self._relayout_map())

    def _build_toolbar(self):
        row1 = ttk.Frame(self, padding=(6, 6, 6, 3))
        row1.pack(fill=tk.X)
        row2 = ttk.Frame(self, padding=(6, 0, 6, 6))
        row2.pack(fill=tk.X)

        ttk.Button(row1, text="Deshacer", command=self._undo).pack(side=tk.LEFT, padx=3)
        ttk.Button(row1, text="Rehacer", command=self._redo).pack(side=tk.LEFT, padx=3)
        ttk.Separator(row1, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)
        ttk.Button(row1, text="+ Nodo", command=self._add_node_button).pack(side=tk.LEFT, padx=3)
        self.connect_btn = ttk.Button(row1, text="Conectar nodos", command=self._toggle_connect_mode)
        self.connect_btn.pack(side=tk.LEFT, padx=3)
        ttk.Button(row1, text="Renombrar", command=self._rename_button).pack(side=tk.LEFT, padx=3)
        ttk.Separator(row1, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)
        ttk.Button(row1, text="Color de nodo", command=self._node_color_button).pack(side=tk.LEFT, padx=3)
        ttk.Button(row1, text="Color de conexión", command=self._conn_color_button).pack(side=tk.LEFT, padx=3)
        ttk.Separator(row1, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)
        ttk.Button(row1, text="Eliminar", command=self._delete_button).pack(side=tk.LEFT, padx=3)

        ttk.Label(row2, text="Tema:").pack(side=tk.LEFT, padx=(3, 4))
        self.theme_var = tk.StringVar(value=DEFAULT_THEME)
        self.theme_combo = ttk.Combobox(
            row2, textvariable=self.theme_var, values=list(THEMES.keys()),
            state="readonly", width=10,
        )
        self.theme_combo.pack(side=tk.LEFT, padx=3)
        self.theme_combo.bind("<<ComboboxSelected>>", lambda e: self._apply_theme())
        ttk.Separator(row2, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)

        ttk.Label(row2, text="Paleta:").pack(side=tk.LEFT, padx=(3, 4))
        self.palette_var = tk.StringVar(value=DEFAULT_PALETTE)
        self.palette_combo = ttk.Combobox(
            row2, textvariable=self.palette_var, values=list(PALETTES.keys()),
            state="readonly", width=12,
        )
        self.palette_combo.pack(side=tk.LEFT, padx=3)
        self.palette_combo.bind("<<ComboboxSelected>>", lambda e: self._apply_palette())
        ttk.Button(row2, text="Nueva paleta...", command=self._create_custom_palette_dialog).pack(
            side=tk.LEFT, padx=3)
        ttk.Separator(row2, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)
        ttk.Button(row2, text="Guardar", command=self.save_map).pack(side=tk.LEFT, padx=3)
        ttk.Button(row2, text="Abrir", command=self.open_map).pack(side=tk.LEFT, padx=3)
        ttk.Separator(row2, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)
        ttk.Button(row2, text="Texto → Mapa", command=self._import_text_dialog).pack(side=tk.LEFT, padx=3)
        ttk.Button(row2, text="Exportar imagen", command=self.export_image).pack(side=tk.LEFT, padx=3)
        ttk.Separator(row2, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)
        ttk.Button(row2, text="Reorganizar", command=self._relayout_map).pack(side=tk.LEFT, padx=3)
        ttk.Button(row2, text="Ajustar", command=self._zoom_to_fit).pack(side=tk.LEFT, padx=3)
        ttk.Button(row2, text="Notas", command=self._toggle_notes_panel).pack(side=tk.LEFT, padx=3)

    def _relayout_map(self):
        self.mind_canvas.relayout_map()

    def _zoom_to_fit(self):
        if not self.mind_canvas.zoom_to_fit():
            messagebox.showinfo("Ajustar a la pantalla", "El mapa está vacío.")

    def _toggle_notes_panel(self):
        if self.notes_panel is not None:
            self._paned.forget(self.notes_panel)
            self.notes_panel.destroy()
            self.notes_panel = None
            self.notes_panel_var.set(False)
            self._set_status("Panel de notas cerrado.")
            return
        self.notes_panel = NotesPanel(self._paned, self.mind_canvas,
                                       on_close=self._toggle_notes_panel)
        self._paned.add(self.notes_panel, weight=0)
        self.notes_panel.start()
        self.notes_panel_var.set(True)
        self._set_status("Panel de notas abierto: clic en una nota para ir a su nodo.")

    def _build_status_bar(self):
        bar = ttk.Frame(self, padding=(8, 3))
        bar.pack(fill=tk.X, side=tk.BOTTOM)
        ttk.Label(bar, textvariable=self.status_var).pack(side=tk.LEFT)

    # ------------------------------------------------------------------ #
    def _set_status(self, text: str):
        self.status_var.set(text)

    def _show_help(self):
        messagebox.showinfo(
            "Instrucciones",
            "• Doble clic en un espacio vacío: crear un nodo nuevo\n"
            "• Doble clic en un nodo: renombrarlo\n"
            "• Tab: agregar un nodo hijo al seleccionado · Enter: agregar un hermano\n"
            "• Ctrl+R: reorganizar el mapa · Ctrl+0: ajustar la vista a todo el mapa\n"
            "• Arrastrar un nodo: moverlo\n"
            "• Rueda del mouse: acercar / alejar (zoom), centrado en el cursor\n"
            "• Mantén Espacio y arrastra: desplazarte por el lienzo (paneo)\n"
            "• Botón \"Conectar nodos\": actívalo, haz clic en el nodo origen y luego\n"
            "  en el nodo destino para crear la conexión (o mantén Shift y arrastra\n"
            "  de un nodo a otro, si lo prefieres)\n"
            "• Clic en una conexión: seleccionarla\n"
            "• Clic derecho: menú con más opciones (color, grosor, eliminar)\n"
            "• Tecla Supr: eliminar lo seleccionado\n"
            "• Ctrl+Z / Ctrl+Y: deshacer / rehacer\n"
            "• Clic derecho en un nodo: convertirlo en nodo central o de rama\n\n"
            "Ver > Panel de notas (o el botón \"Notas\"): abre a la derecha la lista de todas\n"
            "las notas del mapa, con buscador. Un clic lleva al nodo (expandiendo su rama si\n"
            "estaba colapsada) y un doble clic abre el editor de la nota.\n\n"
            "Archivo > Generar desde texto / Markdown: pega texto o Markdown y conviértelo\n"
            "automáticamente en un mapa mental gráfico (un nodo por oración, viñeta o título).\n\n"
            "Tema (barra de herramientas): cambia el estilo visual de los nodos y conexiones\n"
            "(Cuadrados, Contorno, Oscuro, Ramas, Angular).\n\n"
            "Paleta de colores (barra de herramientas): elige un set de colores; se aplica\n"
            "a todo el mapa actual y a los nodos que generes de ahí en adelante. El botón\n"
            "\"Nueva paleta...\" te deja crear y guardar tu propia combinación de colores.\n\n"
            "Archivo > Exportar como imagen: guarda el mapa como PNG (requiere Ghostscript\n"
            "o Pillow instalado en el sistema; si no están disponibles, se guarda como .ps).",
        )

    # ------------------------------------------------------------------ #
    def _add_node_button(self):
        self.mind_canvas.new_node()

    def _rename_button(self):
        node_id = self.mind_canvas.selected_node_id()
        if node_id is None:
            messagebox.showinfo("Renombrar", "Selecciona primero un nodo.")
            return
        self.mind_canvas.rename_node(node_id)

    def _node_color_button(self):
        if len(self.mind_canvas.selected_nodes) > 1:
            self.mind_canvas.change_selected_nodes_color()
            return
        node_id = self.mind_canvas.selected_node_id()
        if node_id is None:
            messagebox.showinfo("Color de nodo", "Selecciona primero un nodo.")
            return
        self.mind_canvas.change_node_color(node_id)

    def _conn_color_button(self):
        conn_id = self.mind_canvas.selected_connection_id()
        if conn_id is None:
            messagebox.showinfo("Color de conexión", "Selecciona primero una conexión (clic sobre la línea).")
            return
        self.mind_canvas.change_connection_color(conn_id)

    def _toggle_connect_mode(self):
        self.mind_canvas.toggle_connect_mode()

    def _apply_palette(self):
        self.mind_canvas.apply_palette(self.palette_var.get())

    def _apply_theme(self):
        self.mind_canvas.set_theme(self.theme_var.get())

    def _refresh_palette_choices(self):
        self.palette_combo["values"] = list(PALETTES.keys())

    def _create_custom_palette_dialog(self):
        dialog = tk.Toplevel(self)
        dialog.title("Nueva paleta de colores")
        dialog.resizable(False, False)
        dialog.transient(self)

        ttk.Label(dialog, text="Nombre de la paleta:").grid(
            row=0, column=0, columnspan=2, sticky="w", padx=10, pady=(10, 4))
        name_var = tk.StringVar(value="Mi paleta")
        ttk.Entry(dialog, textvariable=name_var, width=28).grid(
            row=1, column=0, columnspan=6, sticky="we", padx=10)

        default_colors = ["#4a90d9", "#e0673a", "#3aab6b", "#c94f9e", "#e0a83a", "#7c5cc4"]
        color_vars = [tk.StringVar(value=c) for c in default_colors]

        ttk.Label(dialog, text="Colores de las ramas (haz clic para cambiar cada uno):").grid(
            row=2, column=0, columnspan=6, sticky="w", padx=10, pady=(12, 2))

        def make_pick_handler(var, btn):
            def handler():
                _, hex_color = colorchooser.askcolor(color=var.get(), title="Elegir color", parent=dialog)
                if hex_color:
                    var.set(hex_color)
                    btn.config(bg=hex_color, activebackground=hex_color)
            return handler

        for i, var in enumerate(color_vars):
            btn = tk.Button(dialog, bg=var.get(), activebackground=var.get(),
                             width=4, relief="raised", bd=2)
            btn.grid(row=3, column=i, padx=4, pady=2)
            btn.config(command=make_pick_handler(var, btn))

        ttk.Label(dialog, text="Color del nodo central:").grid(
            row=4, column=0, columnspan=3, sticky="w", padx=10, pady=(14, 2))
        accent_var = tk.StringVar(value="#2b3a4a")
        accent_btn = tk.Button(dialog, bg=accent_var.get(), activebackground=accent_var.get(),
                                width=4, relief="raised", bd=2)
        accent_btn.grid(row=5, column=0, padx=10, pady=2, sticky="w")
        accent_btn.config(command=make_pick_handler(accent_var, accent_btn))

        btns = ttk.Frame(dialog)
        btns.grid(row=6, column=0, columnspan=6, sticky="we", padx=10, pady=14)

        def on_save():
            name = name_var.get().strip()
            if not name:
                messagebox.showinfo("Nueva paleta", "Ponle un nombre a la paleta.", parent=dialog)
                return
            colors = [v.get() for v in color_vars]
            self.mind_canvas.add_custom_palette(name, colors, accent_var.get())
            self._refresh_palette_choices()
            self.palette_var.set(name)
            self._apply_palette()
            dialog.destroy()

        ttk.Button(btns, text="Guardar y aplicar", command=on_save).pack(side=tk.RIGHT, padx=4)
        ttk.Button(btns, text="Cancelar", command=dialog.destroy).pack(side=tk.RIGHT)

        dialog.grab_set()

    def _on_connect_mode_change(self, active: bool):
        self.connect_btn.config(text="Conectar (clic para salir)" if active else "Conectar nodos")

    def _undo(self):
        self.mind_canvas.undo()

    def _redo(self):
        self.mind_canvas.redo()

    def _delete_button(self):
        if self.mind_canvas.selected is None:
            messagebox.showinfo("Eliminar", "Selecciona primero un nodo o una conexión.")
            return
        self.mind_canvas.delete_selected()

    def _import_text_dialog(self):
        dialog = tk.Toplevel(self)
        dialog.title("Generar mapa desde texto / Markdown")
        dialog.geometry("560x480")
        dialog.minsize(420, 320)
        dialog.transient(self)

        # Los botones se empaquetan primero, anclados abajo, para que siempre
        # queden visibles sin importar cuánto crezca el cuadro de texto.
        btns = ttk.Frame(dialog)
        btns.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=8)

        ttk.Label(
            dialog,
            text=(
                "Pega texto plano o Markdown. Usa #, ##, ### para títulos y - o * para\n"
                "viñetas si quieres definir la jerarquía; si pegas un párrafo corrido, cada\n"
                "oración se convertirá en un nodo."
            ),
            justify="left",
        ).pack(anchor="w", padx=10, pady=(10, 4))

        text_frame = ttk.Frame(dialog)
        text_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=4)

        text_widget = tk.Text(text_frame, wrap="word", undo=True, height=12)
        scrollbar = ttk.Scrollbar(text_frame, orient=tk.VERTICAL, command=text_widget.yview)
        text_widget.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        text_widget.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        text_widget.focus_set()

        def on_generate():
            raw = text_widget.get("1.0", "end").strip()
            if not raw:
                messagebox.showinfo("Generar mapa", "Escribe o pega algo de texto primero.", parent=dialog)
                return
            if self.mind_canvas.nodes and not messagebox.askyesno(
                "Generar mapa",
                "Esto reemplazará el mapa actual por uno nuevo generado del texto. ¿Continuar?",
                parent=dialog,
            ):
                return
            if self.mind_canvas.build_mindmap_from_text(raw):
                self.current_file = None
                dialog.destroy()
            else:
                messagebox.showinfo("Generar mapa", "No se pudo extraer ninguna idea del texto.", parent=dialog)

        ttk.Button(btns, text="Generar mapa mental", command=on_generate).pack(side=tk.RIGHT, padx=4)
        ttk.Button(btns, text="Cancelar", command=dialog.destroy).pack(side=tk.RIGHT)

        dialog.grab_set()

    # ------------------------------------------------------------------ #
    def new_map(self):
        if not messagebox.askyesno("Nuevo mapa", "¿Crear un nuevo mapa? Podrás deshacer esta acción con Ctrl+Z."):
            return
        self.mind_canvas.reset_to_default()
        self.current_file = None
        self._set_status("Nuevo mapa creado.")

    def save_map(self):
        if self.current_file is None:
            self.save_map_as()
            return
        self._write_to_file(self.current_file)

    def save_map_as(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("Mapa mental JSON", "*.json")],
            title="Guardar mapa mental",
        )
        if not path:
            return
        self.current_file = path
        self._write_to_file(path)

    def _write_to_file(self, path):
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.mind_canvas.to_dict(), f, ensure_ascii=False, indent=2)
            self._set_status(f"Guardado en {path}")
        except OSError as exc:
            messagebox.showerror("Error al guardar", str(exc))

    def open_map(self):
        path = filedialog.askopenfilename(
            filetypes=[("Mapa mental JSON", "*.json")],
            title="Abrir mapa mental",
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.mind_canvas.load_dict(data)
            self.current_file = path
            self._set_status(f"Cargado {path}")
        except (OSError, json.JSONDecodeError) as exc:
            messagebox.showerror("Error al abrir", str(exc))

    def export_image(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".png",
            filetypes=[("Imagen PNG", "*.png"), ("PostScript", "*.ps")],
            title="Exportar mapa como imagen",
        )
        if not path:
            return
        try:
            final_path = self.mind_canvas.export_image(path)
            self._set_status(f"Mapa exportado a {final_path}")
            messagebox.showinfo("Exportar", f"Mapa exportado correctamente:\n{final_path}")
        except RuntimeError as exc:
            self._set_status("Exportado como PostScript (no se encontró Ghostscript/Pillow para PNG).")
            messagebox.showwarning("Exportar", str(exc))
        except ValueError as exc:
            messagebox.showinfo("Exportar", str(exc))
        except OSError as exc:
            messagebox.showerror("Error al exportar", str(exc))

    def _on_close(self):
        self.destroy()


def main():
    app = MindMapApp()
    app.mainloop()


if __name__ == "__main__":
    main()
