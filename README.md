# Making History 1 & Gold Editor

Editor de mapa (regionpacks), de escenarios y de imágenes para **Making History: The Calm and The Storm (MH1)** y
**Making History Gold**. / Map (regionpack), scenario and image editor for Making History 1 and Gold.

> Proyecto de fans, sin relación con Muzzy Lane. No incluye archivos del juego: hace falta tener el juego instalado en Steam
> (el editor lo busca solo). / Fan project, not affiliated with Muzzy Lane. It ships no game files: you need the game on Steam.

## Qué hace / What it does
- **Editor de regiones**: mover nodos, dibujar, recortar, unificar, crear, renombrar y borrar regiones; cambios de forma que respetan
  la topología; instala el resultado en un *regionpack*; changelog por regionpack; ver ciudades, recursos y unidades.
- **Editor de escenarios** (como `ed.exe`): 25 pestañas, capas de mapa con clic, selección múltiple (regiones y países), crear
  ciudades, recursos y ejércitos, alianzas, guerras, embargos, países históricos, GeoJSON, validador.
- **Adecuar**: pasa un escenario a un regionpack añadiendo y quitando las regiones necesarias para que el juego lo cargue.
- **Imágenes**: título, banderas, iconos, fondo del terreno (con exportación separada de fondo y fronteras).
- Español e inglés. Documentación: [EDITOR.md](EDITOR.md), formato del mapa: [MAPA_FORMATO.md](MAPA_FORMATO.md).

## Usar el programa (sin instalar nada)
Descarga **MHEditor.zip** de [Releases](../../releases), descomprímelo y abre `MHEditor.exe`
(Windows 10/11 de 64 bits; usa WebView2, que ya trae Windows 11).

## Usarlo en el navegador (versión web) / Run it in the browser

El editor es una **web que corre en tu propio PC** (un pequeño servidor local, Python) y que lee y escribe la carpeta de tu juego, así que
**no se puede alojar en internet** (GitHub Pages u otro hosting): cada persona la ejecuta en su ordenador, con el juego instalado.

*The editor is a web app that runs on your own PC (a small local Python server) and reads/writes your game folder, so it cannot be hosted
online: everyone runs it locally with the game installed.*

**Paso a paso (Windows)**
1. Instala **Python 3.12 o superior** desde https://www.python.org/downloads/ (marca «Add python.exe to PATH»).
2. Descarga este repositorio («Code → Download ZIP») y descomprímelo, o clónalo con `git clone`.
3. Abre una terminal en la carpeta del proyecto e instala las dependencias (una sola vez):
   ```
   pip install -r requirements.txt
   ```
4. Arranca el editor, con **doble clic** en `Editor de regiones.bat` (o `Editor de escenarios.bat`), o desde la terminal:
   ```
   python tools/editor_server.py
   ```
5. Abre el navegador en **http://localhost:8765** (el editor de mapa/regiones) y **http://localhost:8765/escenario** (el editor de escenarios).
   Si lo arrancas con el `.bat` se abre solo. Para pararlo, cierra la ventana negra o pulsa `Ctrl+C`.
6. Arriba, el selector **MH1 / Gold** elige el juego; luego eliges regionpack y escenario. Los cambios solo se escriben en el juego al pulsar
   **Guardar** o **Instalar**.

**Opciones del servidor** (`python tools/editor_server.py ...`)
| Opción | Para qué |
|---|---|
| `--puerto 8770` | usar otro puerto si el 8765 está ocupado |
| `--juego mh1` o `--juego gold` | elegir el juego al arrancar |
| `--pack World` | regionpack con el que empezar |
| `--no-abrir` | no abrir el navegador automáticamente |
| `--escenarios CARPETA` | (pruebas) trabajar con copias de escenarios en vez de los del juego |

**Variables de entorno:** `MH_ROOT` (dónde guardar proyectos y registros), `MH_STEAM_COMMON` (carpeta `steamapps\common` si el juego está en otra
biblioteca de Steam; normalmente se detecta sola), `MH_PORT` (puerto del `.exe`).

**Problemas frecuentes**
- *«Ya hay un editor abierto…»*: ya hay un servidor en ese puerto; ábrelo en el navegador o ciérralo antes.
- *No encuentra el juego*: comprueba que está instalado en Steam y que la carpeta contiene `Modern Europe`; si no, indica la ruta con `MH_STEAM_COMMON`.
- *La página se ve vieja tras actualizar el código*: reinicia el servidor y recarga con `Ctrl+F5`.
- Haz **copia de seguridad** de tu juego y de tus escenarios antes de empezar.

**Run from source (summary):** `pip install -r requirements.txt`, then `python tools/editor_server.py` and open http://localhost:8765
(map editor) or http://localhost:8765/escenario (scenario editor); `python tools/mheditor_app.py` opens the same thing in its own window.

## Compilar MHEditor.exe / Build the exe
```
compilar_exe.bat          (o:  pip install -r requirements.txt  &&  python tools/build_exe.py)
```
El resultado queda en `MHEditor\` (ejecutable + `_internal`). Para publicarlo, comprime esa carpeta entera en `MHEditor.zip`.
Al subir una etiqueta `v*` a GitHub, el flujo `.github/workflows/build.yml` lo compila y lo adjunta a la release solo.

## Aviso importante
El editor **escribe en la carpeta del juego solo al guardar o instalar**. Haz una copia de seguridad de tu juego y de tus
escenarios antes de usarlo. / The editor only writes to the game folder when you save or install; back up first.
