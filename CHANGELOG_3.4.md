# Making History 1 & Gold Editor 3.4

## Scenario editing

- Added **Validate object** to scenario object cards. It checks the object and its children, including edits that have not been applied, using a temporary copy of the scenario.
- Added **Add content** for supported empty compositions: army, air force and fleet units, factory resource requirements, research prerequisites, unlocked and removed production outputs, and unit upgrades.
- Added clearer labels for these child types in Spanish and English.
- Added resource template controls to producer cards for the additional maximum-output multiplier, workers per base output and maintenance per base output.
- Explain that resource template settings apply to all producers of the same resource. Shared default files retain the existing save-choice workflow.
- Validate template values before applying any of them, preventing partial changes when a value is invalid.
- Keep scenario changes in memory when opening or reloading another editor page, instead of automatically discarding every open scenario.
- Discard stale tab-list responses when users switch tabs quickly.
- Remove discarded object IDs from the scenario store.
- Write scenario XML through a temporary file before replacing the original. Keep renamed files pending if removing the old filename fails.
- Offer a ZIP download of pending scenario XML files when scenario saving reports an error, including save retries after map compatibility checks. This archive contains modified XML, not a complete standalone scenario or its art assets.

## Scenario validation

- Report malformed integer values instead of silently treating them as absent.
- Report negative producer base production. Treat initial zero production as a warning requiring an in-game check.
- Warn when a producer's resource template cannot be found in the loaded scenario files.
- Check negative worker requirements in producer templates.
- Warn about missing initial city production outputs.
- Check unit hit points, speed, attack, manpower, maintenance, ammunition, carrier air hit points, hit percentages and resistance ranges.
- Check numeric production and research costs and requirements.
- Check production resource requirements and warn about missing resource references.
- Warn about missing research prerequisites, initial research projects, production unlock/replacement references and unit production templates.
- Keep unresolved references as warnings where external data or scenario effects may require additional investigation.

## Region editing and borders

- Added toggleable geometry review layers for saved/proposed outlines, added/removed area, problem edges and collapsed lines or points, with a zoom-to-problems button.
- Use Shapely coverage-edge diagnostics when Shapely 2.1+ and GEOS 3.12+ support them; retain a clearly labelled proximity fallback for older supported installations.
- Accept repairs through the interactive review panel, leaving them pending until an explicit save.
- Report polygon part counts and unchanged, split, removed and collapsed components. Preserve polygons nested inside geometry collections when extracting polygonal repair results.
- Handle completely collapsed repair results in the diagnostic report while preventing acceptance of an empty region.

- Preview proposed gap repairs with per-region area gained/lost, newly uncovered area, overlap and shared border length and connected-part counts.
- Compare repaired invalid outlines against the saved meshes and neighbouring regions before accepting them for review.
- For saves consisting only of gap-repair operations, check the actual rebuilt meshes before writing and reject empty regions, new uncovered area or increased overlap beyond the numerical tolerance. Mixed edits retain the regular mesh checks.
- Verified the three Benine/Foreskin zone gap repairs without lost coverage or increased overlap; the shared border grew from 0.440346 to 2.091083 degrees.

- Added **All intersected regions** to the cut dialog. It transfers the drawn area to the selected destination and excludes the destination from the sources.
- Reject multiple-source cuts that would leave a source region without area.
- Support chained pending cuts, including moving an area from A to B and then from B to C before a single save.
- Make the main **Close gaps** button use the selected region or the two regions selected through multiple selection. Require one or two regions when multiple selection is active. With no selection and the panel closed, retain the whole-map search.
- Preserve edits when selecting a different regionpack fails.
- Identify the originating regionpack when saving. Reject saves from a window whose map no longer matches the active server project, and retain the project reference throughout save and scenario registration.
- Offer repaired outlines for review when edited polygons are invalid. Repairs remain pending and can be undone before saving. Geometric repair can change outlines and may leave gaps that need further editing.

## Save failure recovery

- Handle server responses containing `error` as failed map saves, preserving pending edits instead of clearing them.
- Add a **Draft** recovery panel with retry, download and restore actions for map edits.
- Map drafts include edited polygons, queued operations, centers and new-scenario settings. Restore checks the regionpack, scenario and region metadata before replacing pending edits.
- Allow users to rename pending new regions from the recovery panel.
- Allow a blocking operation to be set aside after downloading the complete draft, so the remaining operations can be saved. The downloaded draft retains the original pending work.
- Stage encoded map files before replacing them. On a replacement error, attempt to restore files already replaced, then reload the project before a retry.
- Keep the existing mesh checks and partial-change recovery choices. The editor cannot guarantee recovery from every filesystem failure or infer the intended shape of an invalid polygon.

## Images and 3D models

- Ignore stale model responses, including asynchronous GLB parsing, after another model is selected.
- Disable model operations while loading and keep them disabled after a load failure.
- Reset model selection and texture state when reloading the model list or changing scenarios.
- Discard stale texture and import previews after the selected model changes.
- Prevent icon and flag writes when the current inputs differ from the previewed inputs.

## Language and desktop integration

- Translate combined save-error headings and server details, including invalid-polygon messages.
- Correct mixed-language confirmation text when renaming a country's internal name.
- Read the current editor language when showing the native unsaved-changes exit confirmation.
- Add Spanish and English text for the new validation, resource editing and recovery controls. Native Windows button captions follow the operating system language.

## Verification and packaging

- Tested gap closure and saved border geometry on an isolated copy of the supplied Benine regionpack.
- Tested chained cuts, stale model parsing, stale image previews, numeric validation, empty child creation and temporary object validation using isolated data or mocked responses.
- Added failure-injection checks for staged map writes and rollback.
- Tested a map draft download/restore round trip with pending polygon edits and centers.
- The GitHub exporter includes the updated Python modules, editor pages, translations and this English changelog.
- Full visual verification in the game and comprehensive desktop UI regression testing remain outstanding.

