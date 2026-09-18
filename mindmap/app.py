"""Ventana principal de la aplicación de mapas mentales."""

import json
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .canvas import MindMapCanvas


class MindMapApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Mapas Mentales")
        self.geometry("1100x700")
        self.minsize(700, 450)

        self.current_file = None
        self.status_var = tk.StringVar(value="Listo.")

        self._build_menu()
        self._build_toolbar()
        self.mind_canvas = MindMapCanvas(self, on_status=self._set_status)
        self.mind_canvas.pack(fill=tk.BOTH, expand=True)
        self._build_status_bar()

        self.mind_canvas.new_node(
            x=self.winfo_screenwidth() // 4,
            y=250,
            text="Idea central",
            color="#4a90d9",
        )

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

    def _build_toolbar(self):
        bar = ttk.Frame(self, padding=6)
        bar.pack(fill=tk.X)

        ttk.Button(bar, text="Deshacer", command=self._undo).pack(side=tk.LEFT, padx=3)
        ttk.Button(bar, text="Rehacer", command=self._redo).pack(side=tk.LEFT, padx=3)
        ttk.Separator(bar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)
        ttk.Button(bar, text="+ Nodo", command=self._add_node_button).pack(side=tk.LEFT, padx=3)
        ttk.Button(bar, text="Renombrar", command=self._rename_button).pack(side=tk.LEFT, padx=3)
        ttk.Button(bar, text="Color de nodo", command=self._node_color_button).pack(side=tk.LEFT, padx=3)
        ttk.Separator(bar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)
        ttk.Button(bar, text="Color de conexión", command=self._conn_color_button).pack(side=tk.LEFT, padx=3)
        ttk.Separator(bar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)
        ttk.Button(bar, text="Eliminar", command=self._delete_button).pack(side=tk.LEFT, padx=3)
        ttk.Separator(bar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)
        ttk.Button(bar, text="Guardar", command=self.save_map).pack(side=tk.LEFT, padx=3)
        ttk.Button(bar, text="Abrir", command=self.open_map).pack(side=tk.LEFT, padx=3)
        ttk.Separator(bar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)
        ttk.Button(bar, text="Texto → Mapa", command=self._import_text_dialog).pack(side=tk.LEFT, padx=3)
        ttk.Button(bar, text="Exportar imagen", command=self.export_image).pack(side=tk.LEFT, padx=3)

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
            "• Arrastrar un nodo: moverlo\n"
            "• Shift + arrastrar desde un nodo a otro: crear una conexión\n"
            "• Clic en una conexión: seleccionarla\n"
            "• Clic derecho: menú con más opciones (color, grosor, eliminar)\n"
            "• Tecla Supr: eliminar lo seleccionado\n"
            "• Ctrl+Z / Ctrl+Y: deshacer / rehacer\n\n"
            "Archivo > Generar desde texto / Markdown: pega texto o Markdown y conviértelo\n"
            "automáticamente en un mapa mental gráfico (un nodo por oración, viñeta o título).\n\n"
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
