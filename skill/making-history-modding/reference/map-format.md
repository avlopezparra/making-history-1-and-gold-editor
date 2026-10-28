# Map format (`DisplayLibraries\Maps\<pack>\xml\`)
All little-endian; coordinates are float32 degrees (x = lon, y = lat). `map.xml` names the three files
(`fileRegionData`, `fileTriShapeGroup`, `fileBorders`) and world bounds (-180..180, -90..105, bWrapX).
The editor's `tools/mhmap.py` (`load_map`, `save_map`) round-trips all three byte-identically; `tools/check_map.py` validates.

## regions.bin (region logic; World: 852 regions)
```
u32 nRegions
per region:
  u32 type          0 = sea (274 in World); 1..4 = land
  u32 a, u32 b      land area, total area (sea: a = 0)
  u32 len, char[len] name
  u32 u_flag, f32 centerX, f32 centerY, u32 0
  u32 nNeighbours, u32 neighbour[n]     region indices, always symmetric
  u32 nPoints, (f32 x, f32 y)[n]        move locations (~0.113° grid inside the region)
```
- **u_flag**: **1 on every sea region**, 2 on some islands, 0 on other land. Never 1 on land.
  A sea region with 0 shows **red** in game and **closes the game** when clicked.
- Islands / multi-part regions (69 in World) list themselves as a neighbour.
- The region index (0..n-1) is what borders.brd, regions.nts and neighbour lists use.

## borders.brd (border lines)
```
u32 nBorders
per border: u32 nRuns; per run: u8 flag (1 = coastline, land–sea only), u32 nPts, (f32,f32)[nPts]
            u32 m (=1), (f32,f32)[m] reference point
tail: u32 nRegions; per region: u32 index, u32 ?, u32 k, (u32 neighbour, u32 borderIndex)[k]
```
Exactly one border per neighbouring pair. Game requirements (else lines shoot to (0,0) and selection outlines are cut):
the border is exactly the chain of edges shared by the two meshes; all points are mesh vertices bit-for-bit; no T-junctions;
no zero-length steps; closed rings don't repeat the first point.

## regions.nts (3D meshes)
```
u32 nShapes
per shape: u32 0xD00D1337, u32 0, u32 nVert, vert{f32 x,y,z(0), nx(0),ny(0),nz(1)} (24 B), u32 nIdx, u32 idx[] (triangle list)
tail: u32 nRegions; per region: u32 region, u32 last, u32 first, u32 last  -> shapes first..last
```
Each region has display, picking and selection meshes (islands: display = island, the others = halo).
**Triangles must be counter-clockwise** (normal 0,0,1); clockwise ones are neither drawn nor selectable.
Meshes repeat vertices; join by coordinate when tracing outlines.

## Terrain textures (`art\OperationalTerrain\OperationalTerrain-CC-RR.tga`)
Raw DXT5/BC3, no header despite `.tga`; 1024² plus mipmaps `-01..-04`. 24 cols × 13 rows of 15° (CC from -180 lon, RR from +105 lat southward).
**Borders are painted into the textures** — moving a border needs repainting (`tools/paint_changes.py`, `fix_texture.py`).
Pillow: `Image.frombytes('RGBA', (n, n), data, 'bcn', 3)`. Gold textures differ from MH1: repaint, don't copy.
`map.xml` `RegionRename` renames regions without touching the binaries.
