# Making History 1 & Gold Editor 2.0 (ENG)

A map (*regionpack*), scenario, and image editor for **Making History: The Calm and The Storm (MH1)** and **Making History Gold**.

> Fan-made project, not affiliated with Muzzy Lane. No game files are included: you must have the game installed on Steam (the editor detects it automatically).

## Features

- **Region editor:** move nodes; draw, crop, merge, create, rename, and delete regions; edit shapes while preserving topology; install results into a *regionpack*; view a changelog for each *regionpack*; inspect cities, resources, and units.
- **Scenario editor** (similar to `ed.exe`): 25 tabs, interactive map layers, multi-selection of regions and countries, creation of cities, resources, and armies, management of alliances, wars, and embargoes, historical countries, GeoJSON support, and a validator.
- **Adapt:** adapt a scenario to a *regionpack* by adding or removing the regions required for the game to load it.
- **Images:** edit titles, flags, icons, and terrain backgrounds, with separate export of backgrounds and borders.
- Available in Spanish and English. Documentation: [EDITOR.md](EDITOR.md) and [MAPA_FORMATO.md](MAPA_FORMATO.md), which describes the map format.

## Run the program without installing dependencies

Download **MHEditor.zip** from [Releases](../../releases), extract it, and open `MHEditor.exe`.

- Requirements: 64-bit Windows 10/11.
- It uses WebView2, which is included with Windows 11.

## Run it in your browser

The editor is a web app that runs on your own computer through a small local Python server. It reads and writes to your game folder, so **it cannot be hosted online** (for example, on GitHub Pages): each user must run it locally and have the game installed.

### Windows setup

1. Install **Python 3.12 or later** from https://www.python.org/downloads/ and select “Add python.exe to PATH”.
2. Download this repository using **Code → Download ZIP** and extract it, or clone it with `git clone`.
3. Open a terminal in the project folder and install the dependencies once:

   ```bash
   pip install -r requirements.txt
   ```

4. Start the editor by double-clicking `Region Editor.bat` or `Scenario Editor.bat`, or run:

   ```bash
   python tools/editor_server.py
   ```

5. Open the following address in your browser:
   - Map and region editor: http://localhost:8765
   - Scenario editor: http://localhost:8765/scenario

   If you start it using a `.bat` file, the browser opens automatically. To stop the server, close the terminal window or press `Ctrl+C`.
6. In the selector at the top, choose **MH1** or **Gold**, then choose the *regionpack* and scenario. Changes are written to the game only when you click **Save** or **Install**.

### Server options

Configure the server with `python tools/editor_server.py ...`:

| Option | Description |
|---|---|
| `--puerto 8770` | Use another port if 8765 is already in use. |
| `--juego mh1` or `--juego gold` | Choose the game at startup. |
| `--pack World` | Set the initial *regionpack*. |
| `--no-abrir` | Do not open the browser automatically. |
| `--escenarios FOLDER` | For testing: use scenario copies instead of the game's scenario files. |

### Environment variables

- `MH_ROOT`: where projects and logs are saved.
- `MH_STEAM_COMMON`: the `steamapps\common` folder if the game is installed in a different Steam library; it is normally detected automatically.
- `MH_GAME_MH1` / `MH_GAME_GOLD`: game folders for non-Steam installations.
- `MH_PORT`: port used by the `.exe`.

### Common issues

- **“An editor is already running…”**: a server is already using that port. Open it in your browser or close the other server.
- **The game cannot be found:** make sure its folder contains `Modern Europe`. Set `MH_STEAM_COMMON` for another Steam library, or `MH_GAME_MH1` / `MH_GAME_GOLD` for a non-Steam installation.
- **The page looks outdated after updating the code:** restart the server and hard-refresh with `Ctrl+F5`.
- Make a **backup** of your game and scenarios before you begin.

### Run from source (summary)

Run `pip install -r requirements.txt`, then `python tools/editor_server.py`. Open http://localhost:8765 for the map editor or http://localhost:8765/scenario for the scenario editor. You can also run `python tools/mheditor_app.py` to open the same app in its own window.

## Build `MHEditor.exe`

Run:

```bat
compilar_exe.bat
```

Or:

```bash
pip install -r requirements.txt
python tools/build_exe.py
```

The output is saved to `MHEditor\` (the executable and the `_internal` folder). To distribute it, compress the entire folder into `MHEditor.zip`.

When you push a `v*` tag to GitHub, the `.github/workflows/build.yml` workflow builds the app and automatically attaches it to the release.

## Important notice

The editor **only writes to the game folder when you save or install**. Even so, back up your game and scenarios before using it.

---
# Making History 1 & Gold Editor 2.0 (ESP)

Editor de mapas (*regionpacks*), escenarios e imágenes para **Making History: The Calm and The Storm (MH1)** y **Making History Gold**.

> Proyecto de fans, sin relación con Muzzy Lane. No incluye archivos del juego: necesitas tener el juego instalado en Steam (el editor lo detecta automáticamente).

## Funciones

- **Editor de regiones:** mover nodos, dibujar, recortar, unificar, crear, renombrar y borrar regiones; editar formas respetando la topología; instalar resultados en un *regionpack*; consultar el historial de cambios por *regionpack*; ver ciudades, recursos y unidades.
- **Editor de escenarios** (similar a `ed.exe`): 25 pestañas, capas de mapa interactivas, selección múltiple de regiones y países, creación de ciudades, recursos y ejércitos, gestión de alianzas, guerras y embargos, países históricos, GeoJSON y validador.
- **Adecuar:** adaptar un escenario a un *regionpack*, añadiendo o quitando las regiones necesarias para que el juego pueda cargarlo.
- **Imágenes:** editar títulos, banderas, iconos y fondos de terreno, con exportación separada del fondo y las fronteras.
- Disponible en español e inglés. Documentación: [EDITOR.md](EDITOR.md) y [MAPA_FORMATO.md](MAPA_FORMATO.md), sobre el formato del mapa.

## Ejecutar el programa sin instalar dependencias

Descarga **MHEditor.zip** desde [Releases](../../releases), descomprímelo y abre `MHEditor.exe`.

- Requisitos: Windows 10/11 de 64 bits.
- Usa WebView2; Windows 11 ya lo incluye.

## Ejecutarlo en el navegador

El editor es una aplicación web que se ejecuta en tu propio ordenador mediante un pequeño servidor local de Python. Lee y escribe en la carpeta del juego, por lo que **no puede alojarse en internet** (por ejemplo, en GitHub Pages): cada usuario debe ejecutarlo localmente y tener el juego instalado.

### Pasos en Windows

1. Instala **Python 3.12 o posterior** desde https://www.python.org/downloads/ y marca la opción «Add python.exe to PATH».
2. Descarga este repositorio mediante **Code → Download ZIP** y descomprímelo, o clónalo con `git clone`.
3. Abre una terminal en la carpeta del proyecto e instala las dependencias una sola vez:

   ```bash
   pip install -r requirements.txt
   ```

4. Inicia el editor haciendo doble clic en `Region Editor.bat` o `Scenario Editor.bat`, o ejecuta:

   ```bash
   python tools/editor_server.py
   ```

5. Abre en el navegador:
   - Editor de mapas y regiones: http://localhost:8765
   - Editor de escenarios: http://localhost:8765/scenario

   Si lo inicias con un archivo `.bat`, el navegador se abrirá automáticamente. Para detener el servidor, cierra la ventana de terminal o pulsa `Ctrl+C`.
6. En el selector superior, elige **MH1** o **Gold** y, después, el *regionpack* y el escenario. Los cambios solo se escribirán en el juego al pulsar **Guardar** o **Instalar**.

### Opciones del servidor

Puedes configurar el servidor con `python tools/editor_server.py ...`:

| Opción | Descripción |
|---|---|
| `--puerto 8770` | Usa otro puerto si el 8765 está ocupado. |
| `--juego mh1` o `--juego gold` | Elige el juego al iniciar. |
| `--pack World` | Indica el *regionpack* inicial. |
| `--no-abrir` | Evita que el navegador se abra automáticamente. |
| `--escenarios CARPETA` | Para pruebas: trabaja con copias de escenarios en lugar de los archivos del juego. |

### Variables de entorno

- `MH_ROOT`: ubicación para guardar proyectos y registros.
- `MH_STEAM_COMMON`: carpeta `steamapps\common` si el juego está en otra biblioteca de Steam; normalmente se detecta automáticamente.
- `MH_GAME_MH1` / `MH_GAME_GOLD`: carpetas del juego en instalaciones que no son de Steam.
- `MH_PORT`: puerto utilizado por el `.exe`.

### Problemas frecuentes

- **«Ya hay un editor abierto…»**: ya hay un servidor usando ese puerto. Ábrelo en el navegador o cierra el otro servidor.
- **No encuentra el juego:** comprueba que la carpeta contenga `Modern Europe`. Configura `MH_STEAM_COMMON` para otra biblioteca de Steam o `MH_GAME_MH1` / `MH_GAME_GOLD` para instalaciones que no son de Steam.
- **La página muestra una versión antigua tras actualizar el código:** reinicia el servidor y recarga con `Ctrl+F5`.
- Haz una **copia de seguridad** del juego y de tus escenarios antes de empezar.

### Ejecutar desde el código fuente (resumen)

Ejecuta `pip install -r requirements.txt` y después `python tools/editor_server.py`. Abre http://localhost:8765 para el editor de mapas o http://localhost:8765/scenario para el editor de escenarios. También puedes ejecutar `python tools/mheditor_app.py` para abrir la misma aplicación en su propia ventana.

## Compilar `MHEditor.exe`

Ejecuta:

```bat
compilar_exe.bat
```

O bien:

```bash
pip install -r requirements.txt
python tools/build_exe.py
```

El resultado se guarda en `MHEditor\` (el ejecutable y la carpeta `_internal`). Para distribuirlo, comprime toda esa carpeta en `MHEditor.zip`.

Al publicar en GitHub una etiqueta `v*`, el flujo `.github/workflows/build.yml` compila el programa y adjunta el archivo a la release automáticamente.

## Aviso importante

El editor **solo escribe en la carpeta del juego al guardar o instalar**. Aun así, haz una copia de seguridad del juego y de tus escenarios antes de usarlo.
