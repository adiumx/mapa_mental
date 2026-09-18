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
        file_menu.add_separator()
        file_menu.add_command(label="Salir", command=self._on_close)
        menubar.add_cascade(label="Archivo", menu=file_menu)

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="Instrucciones", command=self._show_help)
        menubar.add_cascade(label="Ayuda", menu=help_menu)

        self.config(menu=menubar)

        self.bind_all("<Control-n>", lambda e: self.new_map())
        self.bind_all("<Control-o>", lambda e: self.open_map())
        self.bind_all("<Control-s>", lambda e: self.save_map())

    def _build_toolbar(self):
        bar = ttk.Frame(self, padding=6)
        bar.pack(fill=tk.X)

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
            "• Tecla Supr: eliminar lo seleccionado\n\n"
            "Archivo > Generar desde texto / Markdown: pega texto o Markdown y conviértelo\n"
            "automáticamente en un mapa mental gráfico (un nodo por oración, viñeta o título).",
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

    def _delete_button(self):
        if self.mind_canvas.selected is None:
            messagebox.showinfo("Eliminar", "Selecciona primero un nodo o una conexión.")
            return
        self.mind_canvas.delete_selected()

    def _import_text_dialog(self):
        dialog = tk.Toplevel(self)
        dialog.title("Generar mapa desde texto / Markdown")
        dialog.geometry("560x440")
        dialog.transient(self)

        ttk.Label(
            dialog,
            text=(
                "Pega texto plano o Markdown. Usa #, ##, ### para títulos y - o * para\n"
                "viñetas si quieres definir la jerarquía; si pegas un párrafo corrido, cada\n"
                "oración se convertirá en un nodo."
            ),
            justify="left",
        ).pack(anchor="w", padx=10, pady=(10, 4))

        text_widget = tk.Text(dialog, wrap="word", undo=True)
        text_widget.pack(fill=tk.BOTH, expand=True, padx=10, pady=4)
        text_widget.focus_set()

        btns = ttk.Frame(dialog)
        btns.pack(fill=tk.X, padx=10, pady=8)

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
        if not messagebox.askyesno("Nuevo mapa", "¿Crear un nuevo mapa? Se perderán los cambios sin guardar."):
            return
        self.mind_canvas.clear_all()
        self.current_file = None
        self.mind_canvas.new_node(x=300, y=250, text="Idea central", color="#4a90d9")
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

    def _on_close(self):
        self.destroy()


def main():
    app = MindMapApp()
    app.mainloop()


if __name__ == "__main__":
    main()
