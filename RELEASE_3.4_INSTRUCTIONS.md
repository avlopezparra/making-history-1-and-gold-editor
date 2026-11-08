# Visual Studio instructions for version 3.4

## Source and export

The working source is `C:\Users\janit\Documents\Claude\making-history`.
Run `tools/exportar_github.py` from this source tree. It packages the current
Python modules, editor pages, translations, build scripts and documentation.
`CHANGELOG_3.4.md` is the English changelog for this release.

The reviewed export is `.scratch/github-v3.4-final` under the source directory.
It is a source package, not an existing Git checkout. Do not upload the working
source directory, which contains game files and user projects.

## Prepare the Git checkout

1. In Visual Studio, open or clone the intended repository:
   `https://github.com/avlopezparra/making-history-1-and-gold-editor.git`.
2. Check its remote, active branch and Git Changes. Preserve any local work
   before exporting into it. The exporter replaces the contents of its output
   directory, preserving `.git` and `LICENSE`.
3. Export into the absolute path of that checkout. From the source directory,
   use the command below, replacing the example destination with the actual
   checkout path. Do not point the exporter at the source directory or a parent
   directory.

```powershell
Set-Location 'C:\Users\janit\Documents\Claude\making-history'
python -B tools/exportar_github.py 'C:\absolute\path\to\the\GitHub\checkout'
```

4. In Visual Studio, inspect the resulting diff. Confirm that
   `tools/editor/i18n.js` declares `VERSION = '3.4'`, the README identifies 3.4,
   and the English `CHANGELOG_3.4.md` and this file are present.
5. Confirm that game binaries, scenarios, maps, backups, logs, local drafts and
   `.scratch` data are absent from the diff. The exporter intentionally excludes
   these files.

## Check before publishing

- Parse changed Python files, JSON translations and JavaScript script blocks.
- Review the documented test results and remaining limits in the changelog.
- Run a desktop smoke test using copied scenarios and an isolated project:
  open all four editors, change language, validate an object, add a nested item,
  edit a resource template, close selected gaps, review repair layers, and
  download/restore a map draft. Save only into test copies.
- Check the map and scenario in the game before declaring the release fully
  tested. Full desktop and in-game visual regression testing was still pending
  when these instructions were written.

## Commit and publish

1. Commit the reviewed exported files from Visual Studio's Git Changes window.
   Suggested commit message: `Release editor 3.4`.
2. Push the commit to the intended branch, or use the repository's pull request
   workflow if the branch is protected.
3. When the release checks are complete, verify that tag `v3.4` does not already
   exist locally or remotely. Create `v3.4` on the reviewed commit and push it.
   Do not replace an existing release tag.
4. The exported `.github/workflows/build.yml` builds the Windows executable on
   `v*` tags and attaches `MHEditor.3.4.zip` to a GitHub release. Follow the Actions
   run through completion and check its artifact and release attachment.
5. Use the English entries in `CHANGELOG_3.4.md` for the release description.
   Upload compiled packages through Releases; keep them out of the source tree.

## Optional local executable build

From the exported checkout, install its `requirements.txt`, then run
`python tools/build_exe.py` or `compilar_exe.bat`. Close a running MHEditor before
building. Verify the executable before distributing the package.

## Current status

The Python source, translations, editor pages and English changelog have been
exported and compared with the working files. No commit, push, tag, executable
build or GitHub release was performed by this task.
