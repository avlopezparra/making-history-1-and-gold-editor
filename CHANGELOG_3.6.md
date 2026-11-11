# Making History 1 & Gold Editor 3.6

A tester reported that the editor had filled more than 20 GB of disk space. In 3.5, every region-editor save copied the entire map background (about 400 MB) into the undo history. 3.6 shares unchanged files between saves, adds a **History** switch to disable and clear that history while keeping Undo available, deletes leftover history from all regionpack projects on startup, and caps the desktop app's browser cache at 64 MB.

- Scenario editor: with «Move and rotate elements» ticked, cities, resources and units can be dragged again after the map reloads (the map lost the setting while the box stayed ticked).
- Desktop app: the window now has its own taskbar identity, so Windows shows the editor icon in the taskbar and not a generic one.
- Region editor, Import GeoJSON: an OpenStreetMap relation can be imported by its id (a number, `r12345`, `relation/12345` or the openstreetmap.org address; several at once). The outline is downloaded and goes through the same dialog as a file, with the region name taken from OpenStreetMap.
- Region editor, Import GeoJSON: KML and KMZ files (Google Earth) are accepted, also by dragging files onto the dialog. Points and lines in them are skipped and counted.
- Region editor, Import GeoJSON: new «Simplify the outlines» tolerance, with the vertex count before and after.
- Region editor: a GeoJSON feature whose geometry is a GeometryCollection (Google Earth exports) or has altitudes could not be read; it now imports as one region with its parts joined, also in «Add / Subtract area from GeoJSON». Overlapping parts of one shape no longer leave a hole where they overlap.
- Import GeoJSON: downloading a very large OpenStreetMap boundary (Canada, Russia…) no longer stops the import with a browser error.
- Import GeoJSON: a damaged or cut-off KMZ now says «KMZ no válido» instead of failing with an internal error, and a KML whose description contains HTML with <!DOCTYPE html> is no longer rejected.
- Region editor: each «Save» no longer copies the whole background (hundreds of MB) into the Undo history; unchanged tiles are shared between saves. A long editing session could fill tens of GB on disk.
- Region editor: new «History» switch next to «Back». Unticked, «Save» keeps no copies for «Back» and the existing history is deleted; «Undo» (Ctrl+Z) still works. The choice is remembered.
- Desktop app: the editor window's browser cache is capped at 64 MB (it grew to hundreds of MB with map tiles).
- On start, the editor deletes the leftover «Back» history of every regionpack project, not only the one it opens, so disk space used by earlier versions is freed automatically.
