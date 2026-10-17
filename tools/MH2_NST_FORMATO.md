# Formato NEST de Making History II (`Regions.nst`) / MH2 NEST format

ES: ingeniería inversa de `modules/mh2 map/world map/models/Regions.nst` (7,8 MB). Código: `mh2_regions.py` (lector) y `mh2_geojson.py` (GeoJSON).
EN: reverse engineering of `Regions.nst`. Code: `mh2_regions.py` (reader), `mh2_geojson.py` (GeoJSON builder).

## Estructura / Layout (little-endian)

- Cabecera / header: `'NEST'`, u32 `2` (versión), u32 `11`, luego tabla de hashes de 8 bytes (índice de tipos/strings), sin interés para la geometría.
- Cadenas / strings: u32 longitud + ASCII (+ relleno). `VisualSceneNode` es la raíz; por cada región hay dos nodos:
  `<Nombre>Node` (transformación: matriz identidad 3x4) y `<Nombre>Node|instance_geometry` (la malla).
  `<Nombre>` es el `strName` de `GameSysRegion.xml` (p. ej. `Paraiba`, `AlbanySeamount`); 2188 nodos.
- Malla / mesh (tras el `|instance_geometry`, tras unos descriptores de 8 bytes de hash):
  - Bloque de vértices: `u32 n` y `n × 24 bytes` = `float32 x, y, z(=0), nx(=0), ny(=0), nz(=1)`.
  - Bloque de índices (unas 40 bytes después, tras hashes): `u32 count`, `u32 tamaño (=2)`, `count × uint16`; lista de triángulos (`count % 3 == 0`), todos `< n`.
- Hay exactamente una malla por región. No hay UV ni más atributos.

## Coordenadas / Coordinates

`x, y` son **longitud/latitud en grados** directamente (Paraíba ≈ -35, -7); `z` siempre 0. No hay proyección.
El mapa continúa más allá de 180°E (hasta ~360, p. ej. Mar de Bering, Fiyi, Polos), así que `mh2_geojson.py` parte esos polígonos en 180° y lleva la parte este a -180… (rango final -180..180).

## Contornos / Outlines

Cada malla es una triangulación del interior; el contorno = unión de los triángulos (`shapely.ops.unary_union`) → `MultiPolygon` (islas = varias partes, huecos = anillos interiores).

## Unión con `GameSysRegion.xml` / Join

Por nombre (`strName`, normalizado sin espacios/guiones bajos y en minúsculas). Todos los 2186 `gs_tbg.Region` del XML tienen nodo; los nodos `Gulf of Ob` y `South Pole` no están en el XML.
`mh_type`: `land_region` si la entrada tiene `nPopulation` (1486), si no `sea_region` (702: mares, lagos, estrechos, bancos, + 2 sin entrada). Propiedades: `name`, `owner` (`refOwner`), `population` (`nPopulation`), `culture` (`tmplCulture` sin `sd.`).

## Resultado / Result

`making-history/mh2/mh2_regions.geojson` — 2188 regiones (1486 tierra, 702 mar), 233 970 vértices, 0 fallos. Regenerar: `python mh2_geojson.py`.
