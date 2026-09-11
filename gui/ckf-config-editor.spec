# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller one-file build of the config editor.

    cd D:\ckf-data-modding
    pyinstaller gui\ckf-config-editor.spec          -> dist\CKF-Config-Editor.exe

Nothing is installed on the player's machine and nothing is written next to
the game except the editor's own settings file. Run it from the repo root:
every path below is relative to this spec's parent directory, and PyInstaller
sets SPECPATH to the directory the spec lives in.

WHAT GOES IN, AND WHY EACH ONE

  gui/app.html                     the page. serve.py reads it off disk.
  schema/*.schema.json             the document the editor edits is described
                                   by these and by nothing else.
  schema/check_schema.py           run in a child process, not reimplemented.
  scripts/gen_teampl_labels.py     imported, to rewrite the mirror in the same
                                   save as the teampl section.
  docs/mission-reference.json      read for the mission names shown beside the
                                   payout rows; absent is handled, but the
                                   whole point of an exe is that it is not.

The bundle keeps the repo's own directory shape -- gui/, schema/, scripts/,
docs/ under the unpack root -- so serve.py's REPO is sys._MEIPASS and every
path it derives is the one it derives from a checkout. See the FROZEN block at
the top of serve.py.

check_schema and gen_teampl_labels are listed BOTH as hiddenimports (so the
frozen importer has them, which is how `import check_schema` resolves) and as
data files (so SCHEMA_DIR and SCRIPTS_DIR on disk hold what a checkout's do).

schema/check_schema.py as a DATA file is load-bearing for a second reason that
is easy to miss: with it there the frozen module's __file__ reads
<_MEIPASS>/schema/check_schema.py, so check_schema's own --schema default
resolves; without it __file__ reads <_MEIPASS>/check_schema.py and the default
points at a directory holding no *.schema.json. serve.py's re-entry passes
--schema explicitly and covers the same hole, so removing either one alone is
invisible and removing both makes the exe validate nothing. [measured
2026-09-04] Keep both; run_check_schema_entry's docstring says the same thing
from the other side.

THE CHILD PROCESS. Frozen, sys.executable is this exe, so serve.py spawns
`CKF-Config-Editor.exe --run-check-schema --config DIR` instead of handing a
script to an interpreter. main() dispatches that before argparse. Every save
therefore pays one bootloader unpack; that is the cost of not reimplementing
the validator.

console=True is deliberate. The editor prints the URL it is listening on, and
a windowed build would swallow a traceback that a player then cannot report.
"""

import os

REPO = os.path.dirname(SPECPATH)          # noqa: F821  PyInstaller defines it

GUI = os.path.join(REPO, 'gui')
SCHEMA = os.path.join(REPO, 'schema')
SCRIPTS = os.path.join(REPO, 'scripts')
DOCS = os.path.join(REPO, 'docs')

a = Analysis(                             # noqa: F821
    [os.path.join(GUI, 'serve.py')],
    pathex=[SCHEMA, SCRIPTS],
    binaries=[],
    datas=[
        (os.path.join(GUI, 'app.html'), 'gui'),
        (os.path.join(SCHEMA, '*.schema.json'), 'schema'),
        (os.path.join(SCHEMA, 'check_schema.py'), 'schema'),
        (os.path.join(SCRIPTS, 'gen_teampl_labels.py'), 'scripts'),
        (os.path.join(DOCS, 'mission-reference.json'), 'docs'),
    ],
    hiddenimports=['check_schema', 'gen_teampl_labels'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # serve.py is stdlib only and has no GUI toolkit. Excluding these keeps the
    # exe from carrying a Tk runtime and a test framework it never touches.
    excludes=['tkinter', 'unittest', 'pydoc_data', 'lib2to3'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)                         # noqa: F821

exe = EXE(                                # noqa: F821
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='CKF-Config-Editor',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                            # UPX-packed exes get flagged by AV
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
