# Mapas Mentales

Aplicación de escritorio en Python (Tkinter) para crear mapas mentales: nodos que se
arrastran libremente por el lienzo y conexiones a las que se les puede cambiar el color.

## Requisitos

- Python 3.8+
- Tkinter (incluido en las instalaciones oficiales de Python en Windows y macOS).
  En Linux puede requerir instalar el paquete del sistema, por ejemplo:

  ```bash
  sudo apt-get install python3-tk
  ```

No se necesitan dependencias externas (no hay `pip install` que hacer).

## Ejecutar

```bash
python3 main.py
```

## Uso

- **Doble clic en un espacio vacío**: crea un nodo nuevo.
- **Doble clic sobre un nodo**: renombrarlo.
- **Arrastrar un nodo**: moverlo por el lienzo.
- **Shift + arrastrar desde un nodo hasta otro**: crea una conexión entre ambos.
- **Clic sobre una conexión**: la selecciona (se resalta con línea punteada).
- **Clic derecho** sobre un nodo o conexión: abre un menú con más opciones
  (cambiar color, cambiar grosor, eliminar).
- **Barra de herramientas**: botones para agregar nodo, renombrar, cambiar color
  de nodo/conexión, eliminar, guardar y abrir.
- **Tecla Supr/Backspace**: elimina el nodo o la conexión seleccionada.
- **Guardar / Abrir**: el mapa se guarda como archivo `.json`, conservando
  posiciones, textos y colores.
- **Texto → Mapa** (barra de herramientas o menú *Archivo > Generar desde texto /
  Markdown*): pega texto plano o Markdown y se genera automáticamente un mapa
  mental gráfico.
  - Con títulos Markdown (`#`, `##`, `###`) y viñetas (`-`, `*`, `1.`), se
    respeta esa jerarquía.
  - Sin ninguna marca, cada línea se convierte en un nodo conectado al centro.
  - Un párrafo corrido sin saltos de línea se separa en oraciones, y cada
    oración se convierte en un nodo.
  - Cada rama principal recibe un color distinto, aplicado también a sus
    conexiones, y luego se puede seguir editando manualmente.

## Estructura del proyecto

```
main.py              # punto de entrada
mindmap/
  app.py             # ventana principal, menú, barra de herramientas
  canvas.py          # lienzo interactivo: nodos, conexiones, arrastre, colores
  models.py          # modelos de datos (Node, Connection) y su serialización
```
