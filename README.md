# Mapas Mentales

Aplicación de escritorio en Python (Tkinter) para crear mapas mentales: nodos (cajas
redondeadas con texto) que se arrastran libremente por el lienzo, conectados con
líneas curvas a las que se les puede cambiar el color y el grosor, con un nodo
central destacado y varias paletas de colores para un estilo limpio y moderno.

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
- **Rueda del mouse**: acercar o alejar (zoom), centrado en la posición del cursor.
- **Botón "Conectar nodos"** (barra de herramientas): actívalo, haz clic en el nodo
  origen y luego en el destino para crear la conexión. También puedes mantener
  **Shift y arrastrar** de un nodo a otro, si lo prefieres.
- **Clic sobre una conexión**: la selecciona (se resalta con un borde de color).
- **Clic derecho** sobre un nodo o conexión: abre un menú con más opciones
  (cambiar color, cambiar grosor, convertir en nodo central/de rama, eliminar).
- **Barra de herramientas**: botones para agregar nodo, conectar, renombrar, cambiar
  color de nodo/conexión, eliminar, elegir paleta, guardar y abrir.
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
- **Tema** (barra de herramientas): cambia el estilo visual de todo el mapa:
  - *Cuadrados*: cajas redondeadas con relleno de color y texto blanco (por defecto).
  - *Contorno*: cajas con fondo blanco, borde y texto del color de la rama.
  - *Oscuro*: igual que Cuadrados, pero con el lienzo en fondo oscuro.
  - *Ramas*: los nodos de rama son un punto de color con el texto al lado
    (el nodo central sigue siendo una caja), para un estilo más ligero tipo
    "árbol de ideas".
- **Paleta de colores** (barra de herramientas): elige entre varios sets de
  colores (Vivo, Océano, Atardecer, Pastel, Clásico). Al seleccionar una, se
  recolorea todo el mapa actual por ramas (cada rama principal y sus
  descendientes reciben un color de la paleta) y se usa para los nodos que
  crees de ahí en adelante.
- **Nueva paleta...**: crea tu propia paleta eligiendo 6 colores de rama y un
  color para el nodo central; queda disponible en el selector de paletas
  junto con las demás (se guarda solo durante la sesión actual).
- **Deshacer / rehacer** (`Ctrl+Z` / `Ctrl+Y`, o menú *Editar*): revierte
  cualquier acción (crear, mover, renombrar, cambiar colores, eliminar,
  generar mapa desde texto, nuevo mapa, abrir archivo).
- **Exportar como imagen** (barra de herramientas o *Archivo > Exportar como
  imagen*): guarda el mapa como PNG. Requiere tener
  [Ghostscript](https://ghostscript.com/) instalado en el sistema (o Pillow +
  Ghostscript); si no están disponibles, guarda el mapa como PostScript
  (`.ps`), que se puede abrir con GIMP, Vista previa (macOS) o convertir con
  cualquier herramienta compatible.

## Estructura del proyecto

```
main.py              # punto de entrada
mindmap/
  app.py             # ventana principal, menú, barra de herramientas
  canvas.py          # lienzo interactivo: nodos, conexiones, arrastre, colores
  models.py          # modelos de datos (Node, Connection) y su serialización
```
