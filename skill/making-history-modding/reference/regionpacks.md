# Regionpacks, changelogs, equivalence with World
- A **regionpack** = `DisplayLibraries\Maps\<name>` (`xml\` geometry + `art\` textures). Each scenario picks one in
  `scenario.xml` (`strMapName`, `fileMapProperties`). Stock: `World`, `WorldPublicPanamaCanalAndSuez`.
- A pack's `map.xml`: `RegionRename` (scenarios use the renamed names, e.g. Maghreb → Northern Algeria), `CanalRegions`,
  `ConnectedRegions`, `DisconnectedRegions`, `FoggingLinkedRegions`.
- The map binaries are shared by every scenario on the pack: a change shows in all of them.
- The editor keeps one project per pack (`editor_proyecto` for World, `editor_proyecto_<name>` for others).
  The first **Install** asks: overwrite the current pack or create a new one, and which scenarios switch to it.
- **changelog.json**: every save records region transfers by name, new/removed adjacencies, moved centres, new regions (owner,
  controller, terrain, population, historic countries). Install copies it into the pack so other scenarios can be adapted.
- **Equivalence with World**: a modded pack is compared with `World` (or any base) **by geometry**: new regions (which base regions
  they come from and with what % of area), removed, split, merged, modified (`changelog_comparado.json` in the GeoJSON export).
- **Adapt** (Adecuar): moves a scenario to a pack and adds/removes regions so it matches, using the changelog choices; between two
  modded packs it uses geometry overlap (surplus area → region it overlaps most; missing area ← region that held it).
- New fictional world: "+ New" pack = map with 0 regions (valid empty binaries); sea-colour tiles hard-linked; Install needs ≥ 1 region.
