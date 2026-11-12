# Making History 1 & Gold Editor 3.8

- Region editor, «Install»: when scenarios that use the regionpack do not match the installed map, a popup lists what each one is missing or has extra and offers «Adapt and save» (the same as «Map compatibility» plus «Save», including changes still pending for them in the scenario editor) or «Leave them as they are». Before, it only warned, in Spanish, that the game would not load them. The «Register anyway» choice is now called «Register without saving the scenario», which is what it does.
- Warnings that only had «OK» now offer the fix when the editor can do it:
  - Scenario editor, merging or deleting regions with unsaved changes: «Save and continue» / «Revert and continue» / «Cancel» (before: «save or revert first»).
  - Scenario editor, «＋ New» scenario copied from a base with unsaved changes: «Save them and create the copy» / «Discard them and create the copy».
  - 3D Scale, «Undo» with unsaved scale changes: «Discard them and undo».
  - Switching game (MH1/Gold) with unsaved scenario changes: «Save and switch» / «Discard and switch» in the scenario editor; «Open the scenario editor» / «Discard and switch» in the region editor.
  - Region editor, saving into «World»: the warning now has a «Save as…» button that opens the copy dialog (pending changes are kept), plus «Save to World anyway» / «Don't save».
  - Region editor, «Save as…» (copy of a regionpack) with scenarios that have unsaved changes: asks to save or discard them first instead of failing.
  - Region editor, a new region for a scenario whose regionpack is not installed yet: offers «Install…» right away.
- «Map compatibility» and «Install»: a land region drawn without a nation (not cut from another region) is no longer left out of the scenarios; it gets the nation that owns most of its neighbours, with a note to change it if needed. Before, «Install» could never make those scenarios match the map, so the game would not load them.
- Region editor: renaming a region says it is already saved (so «Save» stays disabled) and offers «Install now» when the internal name changed.
- Region editor, «Install» with land regions that have no nation in the open scenario: instead of an OK/Cancel warning pointing to GeoJSON → Import, a popup offers «Assign nation…» (opens the «Regions without a nation» list), «Give them their neighbours' nation» (installs; the adaptation gives each one the nation of most of its neighbours and says so) or «Cancel».
