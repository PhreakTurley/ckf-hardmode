#!/usr/bin/env python3
"""Build the player zip, and refuse to build it out of anything unproven.

    python scripts/make_release.py                 # build the exe, gate it, zip
    python scripts/make_release.py --skip-exe      # reuse dist/CKF-Config-Editor.exe
    python scripts/make_release.py --config DIR    # package a config other than the live one
    python scripts/make_release.py --selftest      # prove every refusal can fire

Everything a player gets comes from five places and this script checks all
five before it writes a byte:

  mods/CKFHardMode/bin/Release/net6.0/CKFHardMode.dll   built by David
  vendor/BepInEx-6.0.0-be.785/                          unpacked once, pinned
  dist/CKF-Config-Editor.exe                            built here by PyInstaller
  release/*.in                                          the three text templates
  <game>/BepInEx/config/                                the live tuning

THE TUNING COMES FROM THE LIVE CONFIG, AND ONLY FROM THERE

The config directory packaged is the one the editor edits: gui/settings.json,
read through serve.py's own load_settings and config_dir_for, so "what I tuned
in the editor" and "what the zip ships" cannot name two different folders.
--config overrides it. The repo holds no copy of the tuning -- there used to be
two (mods/CKFHardMode/defaults/ and overlays/), byte-identical to the live files
and kept that way by hand, and they were removed on 2026-09-11 for exactly
that reason. [David's ruling, 2026-09-11: one source of truth, the live config;
he backs it up himself]

The DLL embeds nothing. The eight files that live under BepInEx\\config -- the
config document, the master-switch cfg, the rule set, the self-check input and
the four files of ckf.hardmode.d -- are copied into the zip, and extracting
the zip is what puts them on disk. Defaults.cs checks they are there and
reports what is not; it writes nothing.

Seven come out of the live directory by the names in CONFIG_FILES. The eighth,
ckf.hardmode.cfg, is rendered from release/ckf.hardmode.cfg.in so its header
carries the release version. It ships with the mod switched on, whatever the
live file says.
BepInEx rewrites that file on launch from the key the plugin binds, so shipping
it only means the player's first launch is not what creates it.

Any OTHER file Overlays.Load would read out of ckf.hardmode.d (.csv, .tsv,
.json) ships too, because the game on this machine loads it and a player
without it plays a different mod. Anything in there the loader would not read
is left out and named in the output. Nothing else at the top of BepInEx\\config
ships -- BepInEx.cfg and other plugins' configs live there too.

The files are copied into a temporary snapshot first, and every check, the
gate and the zip all read the snapshot. A save made in the editor while the
build runs therefore cannot put bytes in the zip that nothing validated.

WHAT THE CHECKS ARE FOR

Each one exists because the thing it looks at can be stale in a way that ships
and is invisible until a player reports it.

  The version is in three files.  CKFHardMode.csproj <Version>, Plugin.cs
  PluginVersion, and the built DLL's own metadata. The .cfg header BepInEx
  writes carries PluginVersion, so a Plugin.cs left behind makes every
  player's config claim a version that was never released. All three are
  compared and any disagreement refuses. This is the check that catches the
  2.13.0 the sources sat on through Phases 0-5.

  A config file can be missing from the live directory.  A release that ships
  six of the seven extracts cleanly and costs a subsystem everything it reads,
  and the player sees one "Defaults: missing" line in a log they have no
  reason to open. Every name in CONFIG_FILES is required and an absent one
  refuses by name.

  The live config can be half-saved.  The editor's save is a journalled
  transaction; a journal left in the directory means the teampl section and
  its mirror may disagree. Its presence refuses, and opening the editor once
  finishes the save (recover_journal).

  The live config can be invalid.  It is the file David edits by hand as well
  as through the editor, so the build runs the two checks the editor runs on a
  save: check_schema.py over the snapshot (any problem refuses, not only the
  RANGE and INVARIANT classes a save blocks on), and gen_teampl_labels.py
  --check, which proves the Team PL mirror still agrees with its section.

  The document's layout stamp can drift from the code.  Defaults.DocVersion is
  what the C# calls the document's shape; the shipped document carries the same
  string in its "_version". They are two literals in two files and nothing
  derives one from the other, so both are read and compared here.

  The vendored BepInEx can be the wrong build.  "Latest bleeding-edge" is not
  a reproducible dependency, so the pin is a build number AND the commit, and
  both are read out of BepInEx.Core.dll rather than trusted from the directory
  name. A vendor tree can also carry a config directory or a plugin left over
  from a test install; those are refused by path.

  The exe can be older than serve.py.  It is rebuilt every run unless
  --skip-exe says otherwise, and either way the gate runs against the exe that
  goes in the zip.

THE GATE, AND WHAT IT DOES ABOUT NOT RUN

`serve.py --selftest --frozen-exe <exe>` is run against the exe about to be
packaged. Any FAIL refuses the release. A missing report line also refuses:
a suite that could not finish reports nothing, and nothing must not read as
clean (AGENTS.md section 3) -- the same rule serve.py's own run_check_schema
applies to check_schema's summary line.

NOT RUN does not refuse. It is printed in full, with the reason the suite gave.
The case that produces one in practice is the temp directory a just-executed
exe leaves behind when antivirus or the search indexer holds it for a moment,
which is not a defect in anything being shipped, and blocking on it would make
a release fail for a reason no edit can fix. [David's ruling, 2026-09-04]

Building the exe with --frozen-exe pointed at it is what makes that safe: the
14 frozen cases are reported, not silently absent, so a NOT RUN is a named
case with a reason and not a hole.

THE ZIP IS DETERMINISTIC

Sorted paths, a fixed timestamp, fixed permissions. Two runs over unchanged
inputs produce byte-identical zips, so "did anything actually change" is one
md5 rather than a diff of two archives. --selftest asserts it.

This script reads the game's BepInEx\\config and never writes to it, or to
anything else outside --out and its own temporary directories.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GUI_DIR = os.path.join(REPO, 'gui')

# ---------------------------------------------------------------------------
# the pin

# Read out of BepInEx.Core.dll, not out of the directory name. The build
# number alone is not enough: BE builds are rebuilt and renumbered, and the
# commit is what identifies the source. Both strings live in one
# AssemblyInformationalVersion, "<build>+<commit>", and that is how they are
# compared.
#
# 6.0.0-be.785 is the build every run recorded in openspec/ was made against.
# [measured, BepInEx/LogOutput.log line 1-2, 2026-09-04]
BE_BUILD = '6.0.0-be.785'
BE_COMMIT = '6abdba47eeebe08552282e7a58ef0f4a9ab60b62'
VENDOR_DIRNAME = 'BepInEx-' + BE_BUILD

# Present in a BepInEx 6 IL2CPP win-x64 tree and load-bearing. Not the whole
# file list -- that is the vendor tree's business and it is copied whole. This
# is the set whose absence means the unpack went somewhere else or the Mono
# build was downloaded by mistake.
VENDOR_REQUIRED = (
    '.doorstop_version',
    'doorstop_config.ini',
    'winhttp.dll',
    'BepInEx/core/BepInEx.Core.dll',
    'BepInEx/core/BepInEx.Preloader.Core.dll',
    'BepInEx/core/BepInEx.Unity.Common.dll',
    'BepInEx/core/BepInEx.Unity.IL2CPP.dll',
    'BepInEx/core/0Harmony.dll',
    'BepInEx/core/Il2CppInterop.Generator.dll',
    'BepInEx/core/Il2CppInterop.Runtime.dll',
)

# A vendor tree assembled by copying out of a live install carries these. They
# are a player's own state or machine-generated, none of them belong in a
# release, and BepInEx recreates every one on first launch.
VENDOR_FORBIDDEN_PREFIXES = (
    'BepInEx/config/',
    'BepInEx/cache/',
    'BepInEx/interop/',
    'BepInEx/unity-libs/',
    'BepInEx/plugins/',
)

PLUGIN_IN_ZIP = 'BepInEx/plugins/CKFHardMode.dll'
EDITOR_IN_ZIP = 'CKF-Config-Editor.exe'

# Paths under BepInEx/config, forward-slashed, read out of the live config
# directory and written to the same path under BepInEx/config in the zip.
# Seven files; the eighth, ckf.hardmode.cfg, is rendered from a template and is
# in TEMPLATES below.
#
# The other half of this table is `Expected` in mods/CKFHardMode/Defaults.cs,
# which is what checks at runtime that they arrived. Nothing derives either
# list from the other; change one and change the other.
CONFIG_FILES = (
    'ckf.hardmode.json',
    'ckf.hardmode.selfcheck.csv',
    'ckf.hardmode.rules.json',
    'ckf.hardmode.d/ArmorModel.csv',
    'ckf.hardmode.d/WeaponModel.csv',
    'ckf.hardmode.d/MonsterTypeModel.csv',
    'ckf.hardmode.d/MissionPowerLevelModel.generated.json',
)
CONFIG_IN_ZIP = 'BepInEx/config/'
DOC_NAME = 'ckf.hardmode.json'
CFG_NAME = 'ckf.hardmode.cfg'

# The extensions Overlays.Load reads out of ckf.hardmode.d (Overlays.cs, the
# Directory.GetFiles filter). A file there with one of these is loaded by the
# game, so it ships; anything else is not, so it does not.
OVERLAY_DIR = 'ckf.hardmode.d'
OVERLAY_EXTS = ('.csv', '.tsv', '.json')

# release/<name> -> path in the zip. Rendered through `render`, which fills the
# placeholders and folds to CRLF. ckf.hardmode.cfg is here rather than in
# CONFIG_FILES because its header names the release version.
TEMPLATES = (
    ('README.txt.in', 'README.txt'),
    ('LICENSE-BepInEx.txt.in', 'LICENSE-BepInEx.txt'),
    ('ckf.hardmode.cfg.in', 'BepInEx/config/ckf.hardmode.cfg'),
)

DEFAULT_DLL = os.path.join(REPO, 'mods', 'CKFHardMode', 'bin', 'Release',
                           'net6.0', 'CKFHardMode.dll')
CSPROJ = os.path.join(REPO, 'mods', 'CKFHardMode', 'CKFHardMode.csproj')
PLUGIN_CS = os.path.join(REPO, 'mods', 'CKFHardMode', 'Plugin.cs')
DEFAULTS_CS = os.path.join(REPO, 'mods', 'CKFHardMode', 'Defaults.cs')
SPEC = os.path.join(REPO, 'gui', 'ckf-config-editor.spec')
TEAMPL_LABELS = os.path.join(REPO, 'scripts', 'gen_teampl_labels.py')
RELEASE_DIR = os.path.join(REPO, 'release')

# Windows names it CKF-Config-Editor.exe; a container build is an ELF with no
# extension. Both are accepted so the pipeline can be exercised off Windows,
# and the name inside the zip is always the .exe one.
EXE_NAMES = ('CKF-Config-Editor.exe', 'CKF-Config-Editor')

ZIP_DATE = (1980, 1, 1, 0, 0, 0)


class Refused(Exception):
    """A reason not to build a release. Every check raises this and nothing
    else, so --selftest can assert on the message rather than on a traceback."""


# ---------------------------------------------------------------------------
# reading the version out of the three places that carry it

_CSPROJ_VERSION = re.compile(r'<Version>\s*([^<\s]+)\s*</Version>')
_PLUGIN_VERSION = re.compile(
    r'PluginVersion\s*=\s*"([^"]+)"')


def read_text(path):
    with open(path, encoding='utf-8-sig') as f:
        return f.read()


def read_bytes(path):
    with open(path, 'rb') as f:
        return f.read()


def csproj_version(csproj=CSPROJ):
    m = _CSPROJ_VERSION.search(read_text(csproj))
    if not m:
        raise Refused('%s has no <Version> element; it is the one place the '
                      'release version is authored' % csproj)
    return m.group(1)


def plugin_cs_version(plugin_cs=PLUGIN_CS):
    m = _PLUGIN_VERSION.search(read_text(plugin_cs))
    if not m:
        raise Refused('%s has no PluginVersion string' % plugin_cs)
    return m.group(1)


def version_blob(version):
    """The bytes an assembly stores `version` as inside a custom-attribute blob.

    A SerString is a compressed length followed by UTF-8. Every version string
    that reaches here is short enough for the length to be one byte, so the
    needle is len(v) then the ASCII, and a match is the assembly's own metadata
    rather than the same digits somewhere else in the file.

    It was written that way because the DLL used to embed ckf.hardmode.json,
    whose "_version" stamp is a different number with the same shape.
    [measured 2026-09-04: bare "3.0.0" appears in the 2.13.0 DLL; the prefixed
    form does not] The defaults are not embedded any more, so that particular
    collision is gone -- but reading the metadata by its length prefix is what
    makes this a version check rather than a substring search, and --selftest
    still holds it to it.
    """
    raw = version.encode('utf-8')
    if len(raw) > 0x7f:
        raise Refused('version %r is too long to look for this way' % version)
    return bytes([len(raw)]) + raw


def check_versions(dll_bytes, csproj=CSPROJ, plugin_cs=PLUGIN_CS):
    """-> the version, once all three places agree on it."""
    v_proj = csproj_version(csproj)
    v_cs = plugin_cs_version(plugin_cs)
    if v_proj != v_cs:
        raise Refused(
            'version disagreement: %s says <Version>%s</Version>, %s says '
            'PluginVersion = "%s". BepInEx writes PluginVersion into the '
            'header of every player\'s ckf.hardmode.cfg, so shipping this '
            'would put a version that was never released into their config.'
            % (os.path.basename(csproj), v_proj, os.path.basename(plugin_cs), v_cs))
    if version_blob(v_proj) not in dll_bytes:
        raise Refused(
            'the built DLL does not carry the version string %s, so it was '
            'built before the bump. Rebuild:\n'
            '    dotnet build -c Release\n'
            '(This reads the assembly\'s own version out of its metadata '
            'blob. If you are certain the DLL is current, the reader is what '
            'is wrong -- see version_blob.)' % v_proj)
    return v_proj


# ---------------------------------------------------------------------------
# the config files that ship loose, out of the live config directory

def _serve():
    """gui/serve.py, imported for what this script has to agree with it on:
    which directory the editor edits, the name of its save journal, and how
    check_schema's output is read. Imported, not restated, so the two cannot
    drift. serve.py is stdlib only and does nothing at import."""
    if GUI_DIR not in sys.path:
        sys.path.insert(0, GUI_DIR)
    import serve
    return serve


def default_config_dir():
    """The directory the editor edits: gui/settings.json, or the default game
    path when that file names none."""
    s = _serve()
    return s.config_dir_for(s.load_settings())


def config_sources(config_dir):
    """-> ([(absolute source, path in zip)], [names left out]).

    Every name in CONFIG_FILES is required. A zip with six of the seven
    extracts cleanly and costs one subsystem everything it reads, so an absent
    one refuses here and names itself rather than shipping a config surface
    with a hole in it.

    Every other file in ckf.hardmode.d that Overlays.Load would read ships as
    well, after the required ones. Anything else in that directory is returned
    in the second list so the caller can say it was left out: a file skipped
    without a word would be a silent difference between the machine the build
    ran on and every player's.
    """
    if not os.path.isdir(config_dir):
        raise Refused(
            'no config directory at %s.\n'
            'The release packages the live BepInEx\\config. Set the game '
            'folder in the editor (gui/settings.json), or name the directory:\n'
            '    python scripts\\make_release.py --config "<game>\\BepInEx\\config"'
            % config_dir)
    journal = os.path.join(config_dir, _serve().JOURNAL_NAME)
    if os.path.exists(journal):
        raise Refused(
            '%s is there, so an editor save did not finish and the teampl '
            'section and its mirror may disagree. Start the editor once -- it '
            'completes the save on start -- and build again.' % journal)
    out, missing = [], []
    for rel in CONFIG_FILES:
        path = os.path.join(config_dir, *rel.split('/'))
        if not os.path.isfile(path):
            missing.append(rel)
        out.append((path, CONFIG_IN_ZIP + rel))
    if missing:
        raise Refused(
            'the release ships these as loose files under BepInEx\\config and '
            'they are not in %s:\n' % config_dir
            + ''.join('    %s\n' % m for m in missing)
            + 'Every one of them is required; the mod does not write them and '
              'a player who does not have one gets a subsystem with nothing to '
              'read.')
    skipped = []
    # By case-folded name, then by identity: Windows finds ArmorModel.csv as
    # armormodel.csv above, and listdir then returns it under its own
    # spelling, which a plain compare would ship a second time.
    listed = dict((r.lower(), r) for r in CONFIG_FILES)
    overlay_dir = os.path.join(config_dir, OVERLAY_DIR)
    for name in sorted(os.listdir(overlay_dir)):
        rel = OVERLAY_DIR + '/' + name
        path = os.path.join(overlay_dir, name)
        canon = listed.get(rel.lower())
        if canon and (canon == rel or os.path.samefile(
                path, os.path.join(config_dir, *canon.split('/')))):
            continue
        if os.path.isfile(path) and name.lower().endswith(OVERLAY_EXTS):
            out.append((path, CONFIG_IN_ZIP + rel))
        else:
            skipped.append(rel + ('/' if os.path.isdir(path) else ''))
    return out, skipped


def _stamp(path):
    st = os.stat(path)
    return st.st_size, st.st_mtime_ns


def snapshot_config(sources, snap, cfg_bytes, config_dir=None):
    """Copy what ships into `snap`, shaped like BepInEx/config. -> snap.

    The .cfg written here is the rendered template, the one the zip carries,
    so check_schema reads the same master switch a player gets rather than
    whatever the live one happens to say.

    A save in the editor while this copies would leave a snapshot that is half
    one config and half another, and only the Team PL pair has a check that
    would notice. So each source's size and mtime are taken before and after
    its copy, and the save journal is looked for again once everything is
    copied; either refuses. `config_dir` is where to look for the journal.
    """
    for src, dest in sources:
        p = os.path.join(snap, *dest[len(CONFIG_IN_ZIP):].split('/'))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        before = _stamp(src)
        shutil.copyfile(src, p)
        if _stamp(src) != before:
            raise Refused('%s changed while it was being copied -- was the '
                          'editor saving? Build again.' % src)
    if config_dir and os.path.exists(
            os.path.join(config_dir, _serve().JOURNAL_NAME)):
        raise Refused('an editor save started while the config was being '
                      'copied, so the copy may be half of each. Let it finish '
                      'and build again.')
    with open(os.path.join(snap, CFG_NAME), 'wb') as f:
        f.write(cfg_bytes)
    return snap


def check_json(config_dir):
    """Refuses unless every .json that ships parses.

    check_schema reads ckf.hardmode.json and nothing else, so the rule set,
    the Team PL mirror and any extra rules file in ckf.hardmode.d would
    otherwise ship unread. Parsed the way the engine reads them -- // and /* */
    comments and trailing commas allowed -- through check_schema's own
    load_jsonc. The CSVs have no equivalent here: what a cell means depends on
    the dump, which is scripts/validate_rules.py's job and needs --game.
    """
    load = _serve().check_schema.load_jsonc
    bad = []
    for root, _dirs, names in os.walk(config_dir):
        for name in sorted(names):
            if name.lower().endswith('.json'):
                p = os.path.join(root, name)
                try:
                    load(p)
                except Exception as e:
                    bad.append('    %s: %s' % (os.path.relpath(p, config_dir), e))
    if bad:
        raise Refused('these would ship and the game could not read them:\n%s'
                      % '\n'.join(bad))


def check_config(config_dir, schema_run=None, teampl_cmd=None):
    """Refuses unless check_schema finds nothing and the Team PL mirror is
    current. `schema_run` and `teampl_cmd` are there for --selftest.

    check_schema is run through serve.run_check_schema, which already refuses
    to read a truncated or summary-less run as clean. Every problem class
    refuses here, not only the two a save blocks on: a save is one field
    changing, a release is every player's starting config.
    """
    r = (schema_run or _serve().run_check_schema)(config_dir)
    if not r.get('ran'):
        raise Refused('check_schema did not finish, so the config is '
                      'unchecked and its silence is not a pass:\n%s'
                      % (r.get('error') or '(no detail)'))
    if r.get('problems'):
        raise Refused(
            'check_schema found %d problem(s) in the config about to ship:\n%s'
            'Fix them in the editor or the file, then build again. To see the '
            'same list yourself:\n'
            '    python schema\\check_schema.py --config "%s"'
            % (len(r['problems']),
               ''.join('    %s  %s\n' % (p.get('kind'), p.get('message'))
                       for p in r['problems']),
               config_dir))
    cmd = teampl_cmd or [sys.executable, TEAMPL_LABELS,
                         '--config', config_dir, '--check']
    try:
        t = subprocess.run(cmd, cwd=REPO, stdin=subprocess.DEVNULL,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        out = t.stdout.decode('utf-8', 'replace')
        code = t.returncode
    except Exception as e:
        out, code = '%s: %s' % (type(e).__name__, e), None
    # The exit code AND the line it prints when current: an interpreter that
    # died before printing anything also exits non-zero, but a stub that
    # printed nothing and exited 0 must not read as current either.
    if code != 0 or 'current' not in out:
        raise Refused(
            'the Team PL mirror (ckf.hardmode.d/MissionPowerLevelModel.'
            'generated.json) does not agree with the teampl section, or the '
            'check could not run (exit %s):\n%s\n'
            'Saving the teampl section in the editor regenerates it.'
            % (code, out.strip()[-2000:]))


_DOC_VERSION = re.compile(r'DocVersion\s*=\s*"([^"]+)"')


def defaults_cs_doc_version(defaults_cs=DEFAULTS_CS):
    m = _DOC_VERSION.search(read_text(defaults_cs))
    if not m:
        raise Refused('%s has no DocVersion string; it is what the shipped '
                      'document\'s "_version" is checked against' % defaults_cs)
    return m.group(1)


def check_doc_version(doc, defaults_cs=DEFAULTS_CS):
    """-> the layout version, once the C# and the shipped document agree on it.

    Two literals in two files with nothing deriving one from the other. The
    document is also parsed here, which is the only place anything asks whether
    the file about to be copied into the zip is JSON at all.
    """
    want = defaults_cs_doc_version(defaults_cs)
    if not os.path.exists(doc):
        raise Refused('no %s; it is the config document the release ships' % doc)
    try:
        parsed = json.loads(read_text(doc))
    except ValueError as e:
        raise Refused('%s is not valid JSON (%s), so it would ship as a file '
                      'the mod cannot read' % (doc, e))
    if not isinstance(parsed, dict):
        raise Refused('%s does not hold a JSON object, so it is not a config '
                      'document' % doc)
    got = parsed.get('_version')
    if got != want:
        raise Refused(
            '%s is at _version %r and %s says DocVersion = "%s". They are the '
            'same number and they have drifted apart; set both to whatever the '
            'document\'s shape is now.'
            % (doc, got, os.path.basename(defaults_cs), want))
    return want


# ---------------------------------------------------------------------------
# the vendored BepInEx is the pinned one

_BE_VERSION = re.compile(rb'\d+\.\d+\.\d+-be\.\d+\+[0-9a-f]{40}')


def be_version(blob):
    """-> ('6.0.0-be.785', '<40 hex>') out of an assembly's bytes, or None.

    The string is stored as a SerString: one compressed-length byte, then
    UTF-8. For "6.0.0-be.785+<40 hex>" that length is 53, which is the ASCII
    digit '5', so a regex reading digits leftward swallows it and reports the
    build as 56.0.0-be.785. That is not hypothetical -- it is what this
    function did on its first run against the real BepInEx.Core.dll.
    [measured 2026-09-04]

    So the length byte is what a hit is anchored on. Only LEADING DIGITS are
    trimmed, and what is left has to still be a whole version string with the
    length byte in front of it. Trimming further -- walking the start forward
    one byte at a time until the arithmetic happens to work -- reads
    "6.0.0-be.999+<40 a>" preceded by an 'x' as the build "-be.999", because
    the fifth byte of it is an ASCII '0' and 48 bytes remain after it. That
    version of this function passed every check here except the one written
    to look for it. A hit with no valid prefix is not the informational
    version and is not accepted.
    """
    for m in _BE_VERSION.finditer(blob):
        start, end = m.start(), m.end()
        while start < end and blob[start:start + 1].isdigit():
            if start > 0 and blob[start - 1] == end - start \
                    and _BE_VERSION.fullmatch(blob[start:end]):
                build, commit = blob[start:end].decode('ascii').split('+')
                return build, commit
            start += 1
    return None


_DOORSTOP_KEY = re.compile(r'^\s*(target_assembly|coreclr_path|corlib_dir)\s*=\s*(\S.*?)\s*$',
                           re.M | re.I)


def doorstop_wants(vendor_dir):
    """-> [(key, path relative to the game root)] that doorstop_config.ini names.

    BepInEx 6 for IL2CPP does not borrow the game's runtime. It ships a .NET
    CoreCLR under `dotnet/` and points doorstop at it:

        target_assembly = BepInEx\\core\\BepInEx.Unity.IL2CPP.dll
        coreclr_path    = dotnet\\coreclr.dll
        corlib_dir      = dotnet

    `dotnet/` is 187 of the 232 files in the release and 35 of its 43 MB
    [measured, CKF-Hard-Mode-3.0.0.zip, 2026-09-04]. A vendor tree without it
    passes every other check here and builds a zip that extracts, installs,
    and does not launch -- doorstop finds no runtime and the game starts
    unmodded or not at all.

    The paths are READ OUT of the vendored ini rather than restated in this
    file, so a BepInEx build that moves them is followed rather than
    contradicted, and a hand-edited ini is checked against what it actually
    says.
    """
    ini = os.path.join(vendor_dir, 'doorstop_config.ini')
    if not os.path.exists(ini):
        return []
    out = []
    for key, raw in _DOORSTOP_KEY.findall(read_text(ini)):
        val = raw.split('#')[0].strip().strip('"')
        if val:
            out.append((key.lower(), val.replace('\\', '/').strip('/')))
    return out


def vendor_files(vendor_dir):
    """-> sorted [path relative to vendor_dir, forward slashes]."""
    out = []
    for root, _dirs, names in os.walk(vendor_dir):
        for n in names:
            p = os.path.join(root, n)
            out.append(os.path.relpath(p, vendor_dir).replace(os.sep, '/'))
    return sorted(out)


def check_vendor(vendor_dir):
    """-> (build, commit) read out of the tree, once it is the pinned one."""
    if not os.path.isdir(vendor_dir):
        raise Refused(
            'no vendored BepInEx at %s.\n'
            'Download the pinned build and unpack it there:\n'
            '    https://builds.bepinex.dev/projects/bepinex_be   ->   '
            'BepInEx-Unity.IL2CPP-win-x64-%s\n'
            'The zip\'s BepInEx/ and doorstop files go directly under that '
            'directory.' % (vendor_dir, BE_BUILD))

    present = set(vendor_files(vendor_dir))
    absent = [p for p in VENDOR_REQUIRED if p not in present]
    if absent:
        raise Refused(
            '%s is not a BepInEx 6 IL2CPP win-x64 tree; it is missing:\n%s'
            'Unpack the zip\'s contents directly into that directory, not '
            'into a subdirectory of it, and check you took the IL2CPP build '
            'rather than the Unity Mono one.'
            % (vendor_dir, ''.join('    %s\n' % p for p in absent)))

    stray = sorted(p for p in present
                   if p.startswith(VENDOR_FORBIDDEN_PREFIXES))
    if stray:
        raise Refused(
            '%s carries files that belong to an install, not to a release:\n%s'
            'BepInEx recreates all of these on first launch. Remove them, or '
            'unpack a clean copy of the zip.'
            % (vendor_dir, ''.join('    %s\n' % p for p in stray[:12])))

    missing = []
    for key, rel in doorstop_wants(vendor_dir):
        target = os.path.join(vendor_dir, *rel.split('/'))
        ok = os.path.isdir(target) and os.listdir(target) if key == 'corlib_dir' \
            else os.path.isfile(target)
        if not ok:
            missing.append('%s = %s' % (key, rel))
    if missing:
        raise Refused(
            '%s\\doorstop_config.ini names files that are not in the tree:\n%s'
            'BepInEx for IL2CPP ships its own .NET runtime under dotnet\\ and '
            'points doorstop at it; a release without it extracts, installs '
            'and does not launch. Unpack the whole zip, not part of it.'
            % (vendor_dir, ''.join('    %s\n' % m for m in missing)))

    core = os.path.join(vendor_dir, 'BepInEx', 'core', 'BepInEx.Core.dll')
    found = be_version(read_bytes(core))
    if found is None:
        raise Refused(
            '%s carries no <build>+<commit> version string, so which BepInEx '
            'this is cannot be established. A tree whose build cannot be read '
            'is not a pin.' % core)
    build, commit = found
    if (build, commit) != (BE_BUILD, BE_COMMIT):
        raise Refused(
            'vendored BepInEx is %s+%s; the pin is %s+%s.\n'
            'Either unpack the pinned build, or change BE_BUILD and BE_COMMIT '
            'in this script and re-run the end-to-end test on a clean install '
            'before shipping the result.'
            % (build, commit, BE_BUILD, BE_COMMIT))
    return build, commit


# ---------------------------------------------------------------------------
# the exe, and the gate it has to pass

def find_exe(dist_dir):
    for n in EXE_NAMES:
        p = os.path.join(dist_dir, n)
        if os.path.exists(p):
            return p
    raise Refused('no editor binary in %s. Build it:\n'
                  '    pyinstaller gui\\ckf-config-editor.spec' % dist_dir)


def build_exe(dist_dir, spec=SPEC, cwd=REPO):
    """PyInstaller, from the repo root, into dist_dir. -> the built path.

    Its scratch goes to dist_dir/build rather than PyInstaller's default of
    ./build, so a release leaves one ignored directory behind, not two."""
    cmd = [sys.executable, '-m', 'PyInstaller', '--noconfirm',
           '--distpath', dist_dir,
           '--workpath', os.path.join(dist_dir, 'build'), spec]
    r = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT)
    if r.returncode != 0:
        raise Refused('PyInstaller exited %d:\n%s'
                      % (r.returncode, r.stdout.decode('utf-8', 'replace')[-4000:]))
    return find_exe(dist_dir)


_REPORT = re.compile(
    r'^gui/serve\.py verification: (\d+) passed, (\d+) failed'
    r'(?:, (\d+) not run)?\s*$', re.M)


_CASE_START = ('PASS', 'FAIL', 'NOT RUN')


def _blocks(out, kind):
    """-> ['FAIL <name>\n        <detail>', ...] for every case of `kind`.

    A case is its name AND the detail line under it, and taking only the line
    the word is on throws the second half away. `_T.check` prints
    `  FAIL  <name>` and then the detail indented by eight, so the block runs
    to the next line that starts another case or is not indented at all.

    That is not a cosmetic loss. The frozen-teardown case reads
    `no process is left running from the exe copy`, and whether that is a
    survivor, a false positive, or an instrument that could not look is stated
    only in the detail -- so a refusal quoting the name alone names the check
    and reports none of what it measured. It did exactly that on David's first
    Windows run, 2026-09-04, and cost a round trip.
    """
    lines = out.splitlines()
    blocks, i = [], 0
    while i < len(lines):
        stripped = lines[i].lstrip()
        if lines[i][:1].isspace() and stripped.startswith(kind):
            block = [lines[i].strip()]
            i += 1
            while i < len(lines):
                nxt = lines[i]
                if not nxt.strip() or not nxt[:1].isspace():
                    break
                if any(nxt.lstrip().startswith(k) for k in _CASE_START):
                    break
                block.append(nxt.rstrip())
                i += 1
            blocks.append('\n'.join(block))
            continue
        i += 1
    return blocks


def _dedupe_cases(blocks):
    """One entry per case name, keeping whichever copy says the most.

    `_T` prints a NOT RUN twice: once where it happens, with the reason on the
    next line, and once in the trailing summary as `<name> -- <reason>`. The
    two strings differ, so de-duplicating on the whole block keeps both and a
    two-case run prints four lines. Keyed on the name, which is the part
    before the first newline or ` -- `.
    """
    best = {}
    for b in blocks:
        name = b.split('\n', 1)[0].split(' -- ', 1)[0].rstrip()
        if len(b) > len(best.get(name, '')):
            best[name] = b
    return list(best.values())


def run_gate(cmd, cwd=REPO):
    """-> {'ran','passed','failed','notrun','lines','output'}

    `cmd` is the whole command, so --selftest can hand this stubs that fail in
    each of the shapes a real run can fail in.

    A run that could not run is reported as could-not-run, and that is not
    only the exception path: the report line has to be there. serve.py's suite
    has twice died mid-run and printed no result -- once on a
    FileNotFoundError out of its own fixture resolver, once on a leaked
    process tree -- and on both occasions the exit code was the only thing
    left to read. An absent report reads exactly like a clean one if you only
    look at the count of FAIL lines, so the count is not what is looked at.
    """
    try:
        r = subprocess.run(cmd, cwd=cwd, stdin=subprocess.DEVNULL,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    except Exception as e:
        return {'ran': False, 'output': '%s: %s' % (type(e).__name__, e),
                'passed': 0, 'failed': 0, 'notrun': 0, 'lines': []}
    out = r.stdout.decode('utf-8', 'replace')
    m = _REPORT.search(out)
    if m is None:
        return {'ran': False, 'output': out, 'passed': 0, 'failed': 0,
                'notrun': 0, 'lines': []}
    return {'ran': True, 'output': out,
            'passed': int(m.group(1)), 'failed': int(m.group(2)),
            'notrun': int(m.group(3) or 0),
            'lines': _dedupe_cases(_blocks(out, 'NOT RUN')),
            'fails': _blocks(out, 'FAIL')}


def gate(exe, cwd=REPO, cmd=None, echo=True, log_dir=None, config_dir=None):
    """Refuses on a FAIL or on a suite that printed no result. Prints NOT RUN.

    A refusal carries each failing case WITH its detail line and writes the
    whole run to `log_dir/selftest-failed.log`, so the next question is never
    "re-run it and paste more" -- a re-run of a teardown that failed once is
    not the same sample.

    `config_dir` is the snapshot about to ship. The suite copies its fixtures
    out of it and never writes to it, so the gate runs against the config the
    zip carries rather than whatever settings.json names at that moment.
    """
    cmd = cmd or ([sys.executable, os.path.join(cwd, 'gui', 'serve.py'),
                   '--selftest', '--frozen-exe', exe]
                  + (['--config', config_dir] if config_dir else []))
    g = run_gate(cmd, cwd=cwd)
    log_hint = ''
    if (not g['ran'] or g['failed']) and log_dir:
        # The whole run, kept, before anything is summarised out of it. A
        # refusal that quotes an excerpt and discards the rest makes the next
        # question a re-run, and a re-run of a flaky teardown is not the same
        # sample.
        try:
            os.makedirs(log_dir, exist_ok=True)
            log = os.path.join(log_dir, 'selftest-failed.log')
            with open(log, 'w', encoding='utf-8', newline='\n') as f:
                f.write(' '.join(cmd) + '\n\n' + g['output'])
            log_hint = '\n\nThe whole run is in %s' % log
        except Exception as e:
            log_hint = '\n\n(the run could not be written to %s: %s)' % (log_dir, e)
    if not g['ran']:
        raise Refused(
            'the verification suite printed no report line, so it did not '
            'finish and its silence is not a pass. Its output:\n%s%s'
            % (g['output'][-4000:], log_hint))
    if g['failed']:
        raise Refused('%d verification failure(s) against %s:\n%s%s'
                      % (g['failed'], exe,
                         '\n'.join('  ' + f for f in g.get('fails') or []),
                         log_hint))
    if echo:
        print('  gate: %d passed, 0 failed%s'
              % (g['passed'],
                 (', %d not run' % g['notrun']) if g['notrun'] else ''))
        # Named, with the reason, every time. A NOT RUN that nobody reads is a
        # silent skip wearing a label.
        for ln in dict.fromkeys(g['lines']):
            print('    %s' % ln)
    return g


# ---------------------------------------------------------------------------
# assembling

def render(src, version):
    """A release/*.in rendered to the bytes that go in the zip.

    The pin appears in the README and in the licence header, and both are
    wrong the moment BE_BUILD changes, so neither states it literally. An
    unfilled placeholder refuses rather than shipping the @NAME@ text -- the
    fault it catches is adding a placeholder to a template and not to this
    list, which otherwise reaches a player and not a test.

    CRLF, because these are the two files a player opens in Notepad.
    """
    text = read_text(src)
    for key, val in (('@VERSION@', version),
                     ('@BE_BUILD@', BE_BUILD),
                     ('@BE_COMMIT@', BE_COMMIT)):
        text = text.replace(key, val)
    left = re.findall(r'@[A-Z_]+@', text)
    if left:
        raise Refused('%s has placeholders nothing fills: %s'
                      % (src, ', '.join(sorted(set(left)))))
    return text.replace('\r\n', '\n').replace('\n', '\r\n').encode('utf-8')


def collect(vendor_dir, dll, exe, version, config_dir, release_dir=RELEASE_DIR):
    """-> {path in zip: bytes}, the whole release, before any of it is written."""
    out = {}
    for rel in vendor_files(vendor_dir):
        out[rel] = read_bytes(os.path.join(vendor_dir, rel))
    out[PLUGIN_IN_ZIP] = read_bytes(dll)
    out[EDITOR_IN_ZIP] = read_bytes(exe)
    # The config files, byte for byte as they are on disk. Copied, not
    # rendered: these are the files the mod reads and the editor edits, and a
    # substitution or a line-ending fold in one of them would change what the
    # game loads.
    for src, dest in config_sources(config_dir)[0]:
        out[dest] = read_bytes(src)
    for name, dest in TEMPLATES:
        src = os.path.join(release_dir, name)
        if not os.path.exists(src):
            raise Refused('no %s; the zip cannot ship without it' % src)
        out[dest] = render(src, version)
    return out


def write_zip(path, members):
    """Deterministic: sorted names, one timestamp, one permission bit."""
    tmp = path + '.part'
    with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as z:
        for name in sorted(members):
            zi = zipfile.ZipInfo(name, date_time=ZIP_DATE)
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = 0o644 << 16
            zi.create_system = 0
            z.writestr(zi, members[name])
    os.replace(tmp, path)
    return path


# ---------------------------------------------------------------------------

def build(out_dir, vendor_dir, dll, config_dir, skip_exe=False, echo=True,
          gate_fn=None, check_fn=None):
    """-> the zip path.

    Every refusal about the inputs -- DLL, versions, config, vendor tree --
    happens before PyInstaller runs. The exe is then built into out_dir and
    gated; a gate refusal leaves that exe and selftest-failed.log there, and no
    zip. The zip is written last."""
    if not os.path.exists(dll):
        raise Refused('no plugin at %s. Build it:\n'
                      '    dotnet build -c Release' % dll)
    dll_bytes = read_bytes(dll)
    version = check_versions(dll_bytes)
    # Found before PyInstaller runs rather than after: a missing file, a
    # half-finished editor save.
    sources, skipped = config_sources(config_dir)
    build_no, commit = check_vendor(vendor_dir)

    with tempfile.TemporaryDirectory(prefix='ckf-release-config-',
                                     ignore_cleanup_errors=True) as snap:
        snapshot_config(sources, snap, render(
            os.path.join(RELEASE_DIR, 'ckf.hardmode.cfg.in'), version),
            config_dir)
        doc_version = check_doc_version(os.path.join(snap, DOC_NAME))
        check_json(snap)
        (check_fn or check_config)(snap)
        if echo:
            print('  version %s, in the csproj, Plugin.cs and the DLL' % version)
            print('  config from %s' % config_dir)
            print('  %d config file(s) shipping loose under BepInEx\\config, at '
                  'document _version %s; every .json parses, check_schema '
                  'clean, Team PL mirror current'
                  % (len(sources) + 1, doc_version))
            for _src, dest in sources[len(CONFIG_FILES):]:
                print('    also shipping %s (the loader reads it)' % dest)
            for rel in skipped:
                print('    NOT shipping %s (the loader would not read it)' % rel)
            print('  BepInEx %s+%s' % (build_no, commit[:7]))

        os.makedirs(out_dir, exist_ok=True)
        exe = find_exe(out_dir) if skip_exe else build_exe(out_dir)
        if echo:
            print('  editor %s (%d bytes)'
                  % (os.path.basename(exe), os.path.getsize(exe)))
        (gate_fn or gate)(exe, echo=echo, log_dir=out_dir, config_dir=snap)

        members = collect(vendor_dir, dll, exe, version, snap)
    if echo and os.path.exists(snap):
        print('  (the config snapshot could not be removed and is still at %s)'
              % snap)
    path = os.path.join(out_dir, 'CKF-Hard-Mode-%s.zip' % version)
    write_zip(path, members)
    if echo:
        raw = sum(len(v) for v in members.values())
        print('\n%s\n  %d file(s), %s raw, %s packed, md5 %s'
              % (path, len(members), _si(raw), _si(os.path.getsize(path)),
                 hashlib.md5(read_bytes(path)).hexdigest()))
        for name in sorted(members):
            if not name.startswith('BepInEx/core/'):
                print('    %-32s %9d' % (name, len(members[name])))
        print('    %-32s %9d  (%d files)'
              % ('BepInEx/core/*', sum(len(v) for k, v in members.items()
                                       if k.startswith('BepInEx/core/')),
                 sum(1 for k in members if k.startswith('BepInEx/core/'))))
    return path


def _si(n):
    return '%.1f MB' % (n / 1048576.0) if n >= 1048576 else '%d B' % n


# ---------------------------------------------------------------------------
# verification
# ---------------------------------------------------------------------------

class _T:
    def __init__(self):
        self.passed = 0
        self.failed = []

    def check(self, name, cond, detail=''):
        if cond:
            self.passed += 1
            print('  PASS  %s' % name)
        else:
            self.failed.append(name)
            print('  FAIL  %s%s' % (name, ('\n        ' + str(detail)) if detail else ''))

    def refuses(self, name, fn, expect):
        """`fn` must raise Refused and the message must carry `expect`.

        Not "raises something": a check that accepts any exception passes on a
        typo in the code it is checking. Every refusal in this file raises
        Refused and nothing else, so anything else reaching here is the finding.
        """
        try:
            fn()
        except Refused as e:
            self.check(name, expect in str(e),
                       'refused, but for a different reason:\n%s' % e)
        except Exception as e:
            self.check(name, False, 'raised %s, not Refused: %s'
                       % (type(e).__name__, e))
        else:
            self.check(name, False, 'did not refuse')

    def report(self):
        print('\nscripts/make_release.py verification: %d passed, %d failed'
              % (self.passed, len(self.failed)))
        return 0 if not self.failed else 1


_STUB_CSPROJ = '''<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup><Version>%s</Version></PropertyGroup>
</Project>
'''

_STUB_PLUGIN_CS = '''namespace CKFHardMode {
    public class Plugin {
        public const string PluginVersion = "%s";
    }
}
'''

_STUB_DEFAULTS_CS = '''namespace CKFHardMode {
    internal static class Defaults {
        internal const string DocVersion = "%s";
    }
}
'''


def _fake_repo(td, version='3.0.0', doc_version='3.0.0', dll_extra=b''):
    """A tree shaped like the real one, small enough to build in a loop.

    It carries no config: the config comes from a directory of its own, see
    _fake_config. The Defaults.cs here holds `doc_version`.
    """
    proj = os.path.join(td, 'mods', 'CKFHardMode')
    os.makedirs(proj)
    csproj = os.path.join(proj, 'CKFHardMode.csproj')
    plugin_cs = os.path.join(proj, 'Plugin.cs')
    defaults_cs = os.path.join(proj, 'Defaults.cs')
    with open(csproj, 'w') as f:
        f.write(_STUB_CSPROJ % version)
    with open(plugin_cs, 'w') as f:
        f.write(_STUB_PLUGIN_CS % version)
    with open(defaults_cs, 'w') as f:
        f.write(_STUB_DEFAULTS_CS % doc_version)
    dll = b'MZ\x90\x00' + version_blob(version) + b'\x00' + dll_extra
    return csproj, plugin_cs, dll


def _fake_config(td, doc_version='3.0.0', extra=()):
    """A BepInEx/config directory holding every name in CONFIG_FILES, plus
    `extra` (names under it), plus the files a real one also holds and that
    must never ship. -> its path.

    Every file is written with its own bytes, so a case can assert that each
    one reaches the zip as itself rather than that some file of the right
    length did.
    """
    cd = os.path.join(td, 'config')
    for rel in tuple(CONFIG_FILES) + tuple(extra) + (
            'BepInEx.cfg', 'ckf.datadump.cfg', CFG_NAME):
        p = os.path.join(cd, *rel.split('/'))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, 'wb') as f:
            f.write(_stub_config_bytes(rel, doc_version))
    return cd


def _stub_config_bytes(rel, doc_version='3.0.0'):
    """Distinct bytes per file, and real JSON for every .json."""
    if rel == DOC_NAME:
        return ('{"_version": "%s", "from": "%s"}\n' % (doc_version, rel)).encode()
    if rel.endswith('.json'):
        return ('{"from": "%s"}\n' % rel).encode()
    return ('from %s\n' % rel).encode()


def _stub_schema_run(ran=True, problems=(), error=None):
    return lambda _cd: {'ran': ran, 'problems': list(problems), 'error': error}


def _stub_teampl_cmd(code=0, text='MissionPowerLevelModel.generated.json current'):
    return [sys.executable, '-c',
            'import sys; print(%r); sys.exit(%d)' % (text, code)]


def _fake_release_dir(td):
    """A release/ holding every template in TEMPLATES. -> its path.

    The real ckf.hardmode.cfg.in is copied in rather than stubbed, because a
    case below asserts on what it renders to; the prose templates are stubs,
    because a `collect` case has no business depending on the wording of the
    README or on the 26 KB of licence text beside it. The real ones are checked
    for their own sake in [6].
    """
    out = os.path.join(td, 'release')
    os.makedirs(out, exist_ok=True)
    for name, _dest in TEMPLATES:
        real = os.path.join(RELEASE_DIR, name)
        body = (read_bytes(real) if name == 'ckf.hardmode.cfg.in'
                and os.path.exists(real)
                else ('stub %s for v@VERSION@\n' % name).encode())
        with open(os.path.join(out, name), 'wb') as f:
            f.write(body)
    return out


_STUB_DOORSTOP = (
    '[General]\nenabled = true\n'
    'target_assembly = BepInEx\\core\\BepInEx.Unity.IL2CPP.dll\n'
    '[Il2Cpp]\ncoreclr_path = dotnet\\coreclr.dll\ncorlib_dir = dotnet\n')


def _fake_vendor(td, build=BE_BUILD, commit=BE_COMMIT, drop=(), extra=(),
                 doorstop=_STUB_DOORSTOP, runtime=('dotnet/coreclr.dll',
                                                   'dotnet/System.Private.CoreLib.dll')):
    """A tree shaped like an unpacked BepInEx IL2CPP zip.

    It carries a real doorstop_config.ini and the two runtime files that ini
    names, because check_vendor follows the ini rather than a list in this
    file -- a stub that wrote `stub` there would make every doorstop case
    vacuous.
    """
    v = os.path.join(td, 'vendor', VENDOR_DIRNAME)
    for rel in runtime:
        p = os.path.join(v, *rel.split('/'))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, 'wb') as f:
            f.write(b'runtime stub\n')
    for rel in VENDOR_REQUIRED:
        if rel in drop:
            continue
        p = os.path.join(v, *rel.split('/'))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        body = b'stub\n'
        if rel == 'doorstop_config.ini':
            body = doorstop.encode()
        if rel.endswith('BepInEx.Core.dll') and build is not None:
            # A real SerString: the length byte, then the UTF-8. Writing the
            # bare text here would make the stub easier to read and would stop
            # it from being able to catch the '5' that is both a length and a
            # digit.
            raw = ('%s+%s' % (build, commit)).encode()
            body = b'\x01a\x00' + bytes([len(raw)]) + raw + b'\x00'
        with open(p, 'wb') as f:
            f.write(body)
    for rel in extra:
        p = os.path.join(v, *rel.split('/'))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, 'wb') as f:
            f.write(b'x')
    return v


def _stub_gate_cmd(passed=301, failed=0, notrun=0, report=True, fail_lines=0):
    """A command that prints what serve.py --selftest prints, and nothing else.

    The FAIL shape is `_T.check`'s: the name on one line, the detail indented
    by eight on the next. A stub that printed only the name could not tell a
    gate that keeps the detail from one that drops it.
    """
    body = []
    for i in range(fail_lines):
        body.append("print('  FAIL  stub case %d\\n        detail for %d')" % (i, i))
    for i in range(notrun):
        body.append("print('  NOT RUN  stub case %d\\n           no sampling "
                    "moment here')" % i)
    if report:
        tail = (', %d not run' % notrun) if notrun else ''
        body.append("print('\\ngui/serve.py verification: %d passed, %d failed%s')"
                    % (passed, failed, tail))
    return [sys.executable, '-c', '\n'.join(body) or 'pass']


def selftest():
    t = _T()

    print('\n[1] the version has to agree in three places')
    with tempfile.TemporaryDirectory() as td:
        csproj, plugin_cs, dll = _fake_repo(td)
        t.check('three agreeing versions read back as one',
                check_versions(dll, csproj, plugin_cs) == '3.0.0')

    with tempfile.TemporaryDirectory() as td:
        csproj, plugin_cs, dll = _fake_repo(td)
        with open(plugin_cs, 'w') as f:
            f.write(_STUB_PLUGIN_CS % '2.13.0')
        t.refuses('a Plugin.cs left on the old version refuses, and says why '
                  'it matters',
                  lambda: check_versions(dll, csproj, plugin_cs),
                  'ckf.hardmode.cfg')

    with tempfile.TemporaryDirectory() as td:
        csproj, plugin_cs, dll = _fake_repo(td)
        with open(csproj, 'w') as f:
            f.write(_STUB_CSPROJ % '3.1.0')
        with open(plugin_cs, 'w') as f:
            f.write(_STUB_PLUGIN_CS % '3.1.0')
        t.refuses('a DLL built before the bump refuses',
                  lambda: check_versions(dll, csproj, plugin_cs),
                  'built before the bump')

    with tempfile.TemporaryDirectory() as td:
        # The stamp inside the config document is a different number with a
        # different meaning, and looking for the bare string would find it.
        # The DLL here is built at 9.9.9 and carries "3.0.0" only inside that
        # document, which is not preceded by its SerString length byte.
        csproj, plugin_cs, dll = _fake_repo(
            td, version='9.9.9', dll_extra=b'{"_version": "3.0.0"}\n')
        with open(csproj, 'w') as f:
            f.write(_STUB_CSPROJ % '3.0.0')
        with open(plugin_cs, 'w') as f:
            f.write(_STUB_PLUGIN_CS % '3.0.0')
        t.refuses('a document _version of 3.0.0 does not stand in for an '
                  'assembly built at 3.0.0',
                  lambda: check_versions(dll, csproj, plugin_cs),
                  'built before the bump')

    print('\n[2] the config files come out of the live directory, and all of them ship')
    with tempfile.TemporaryDirectory() as td:
        cd = _fake_config(td)
        got, skipped = config_sources(cd)
        t.check('every name in CONFIG_FILES is found and mapped to the same '
                'path under BepInEx/config',
                len(got) == len(CONFIG_FILES)
                and all(os.path.isfile(p) for p, _ in got)
                and [d for _, d in got]
                == [CONFIG_IN_ZIP + r for r in CONFIG_FILES]
                and not skipped, (got, skipped))
        t.check('BepInEx.cfg, other plugins\' configs and the live .cfg are '
                'not shipped',
                not [d for _, d in got
                     if d.endswith(('BepInEx.cfg', 'ckf.datadump.cfg', CFG_NAME))],
                got)

    for _rel in CONFIG_FILES:
        with tempfile.TemporaryDirectory() as td:
            cd = _fake_config(td)
            os.remove(os.path.join(cd, *_rel.split('/')))
            t.refuses('a config directory missing %s refuses, by name' % _rel,
                      (lambda c=cd: config_sources(c)), _rel)

    with tempfile.TemporaryDirectory() as td:
        t.refuses('an absent config directory refuses and says how to name one',
                  lambda: config_sources(os.path.join(td, 'nope')), '--config')

    with tempfile.TemporaryDirectory() as td:
        cd = _fake_config(td)
        with open(os.path.join(cd, _serve().JOURNAL_NAME), 'w') as f:
            f.write('{}')
        t.refuses('a half-finished editor save refuses',
                  lambda: config_sources(cd), 'did not finish')

    with tempfile.TemporaryDirectory() as td:
        cd = _fake_config(td, extra=(
            'ckf.hardmode.d/WeaponModel.test.csv',
            'ckf.hardmode.d/ArmorModel.extra.TSV',
            'ckf.hardmode.d/late.rules.json',
            'ckf.hardmode.d/notes.txt',
            'ckf.hardmode.d/ArmorModel.csv.gui-new',
            'ckf.hardmode.d/_reference/gear-tiers.csv'))
        got, skipped = config_sources(cd)
        dests = [d for _, d in got]
        t.check('every other file the loader reads out of ckf.hardmode.d '
                'ships too, after the required ones',
                dests[len(CONFIG_FILES):] == [
                    CONFIG_IN_ZIP + 'ckf.hardmode.d/' + n for n in
                    ('ArmorModel.extra.TSV', 'WeaponModel.test.csv',
                     'late.rules.json')], dests)
        t.check('and everything the loader would not read is left out and '
                'named, a subdirectory included',
                skipped == ['ckf.hardmode.d/ArmorModel.csv.gui-new',
                            'ckf.hardmode.d/_reference/',
                            'ckf.hardmode.d/notes.txt'], skipped)

    with tempfile.TemporaryDirectory() as td:
        cd = _fake_config(td, extra=('ckf.hardmode.d/WeaponModel.test.csv',))
        sources, _sk = config_sources(cd)
        snap = snapshot_config(sources, os.path.join(td, 'snap'), b'rendered cfg\r\n')
        again, _sk = config_sources(snap)
        t.check('the snapshot holds every shipped file byte for byte, and the '
                'rendered .cfg rather than the live one',
                [d for _, d in again] == [d for _, d in sources]
                and all(read_bytes(a) == read_bytes(b)
                        for (a, _), (b, _) in zip(sources, again))
                and read_bytes(os.path.join(snap, CFG_NAME)) == b'rendered cfg\r\n'
                and not os.path.exists(os.path.join(snap, 'BepInEx.cfg')))

    with tempfile.TemporaryDirectory() as td:
        cd = _fake_config(td)
        v = _fake_vendor(td)
        rel = _fake_release_dir(td)
        dll = os.path.join(td, 'stub.dll')
        exe = os.path.join(td, 'stub.exe')
        for p in (dll, exe):
            with open(p, 'wb') as f:
                f.write(b'binary\n')
        members = collect(v, dll, exe, '3.0.0', cd, release_dir=rel)
        wrong = [r for r in CONFIG_FILES
                 if members.get(CONFIG_IN_ZIP + r) != _stub_config_bytes(r)]
        t.check('every config file is in the zip at its mapped path, '
                'byte-identical to the live copy', not wrong, wrong)
        _cfg = members.get('BepInEx/config/ckf.hardmode.cfg')
        t.check('the master switch lands in BepInEx/config with its version '
                'filled in and the key BepInEx binds, not the live file',
                _cfg is not None
                and b'CKF Hard Mode v3.0.0\r\n' in _cfg
                and b'\r\n[General]\r\n' in _cfg
                and b'\r\nEnabled = true\r\n' in _cfg,
                _cfg)
        t.check('and nothing else was dropped on the way in, nor picked up',
                members[PLUGIN_IN_ZIP] == b'binary\n'
                and members[EDITOR_IN_ZIP] == b'binary\n'
                and 'README.txt' in members
                and 'BepInEx/core/BepInEx.Core.dll' in members
                and 'BepInEx/config/BepInEx.cfg' not in members
                and 'BepInEx/config/ckf.datadump.cfg' not in members,
                sorted(k for k in members if not k.startswith('dotnet/')))

    with tempfile.TemporaryDirectory() as td:
        cd = _fake_config(td)
        v = _fake_vendor(td)
        rel = _fake_release_dir(td)
        dll = os.path.join(td, 'stub.dll')
        with open(dll, 'wb') as f:
            f.write(b'binary\n')
        os.remove(os.path.join(cd, 'ckf.hardmode.d', 'MonsterTypeModel.csv'))
        t.refuses('and collect refuses too, rather than writing a zip with a '
                  'hole in its config surface',
                  lambda: collect(v, dll, dll, '3.0.0', cd, release_dir=rel),
                  'ckf.hardmode.d/MonsterTypeModel.csv')

    with tempfile.TemporaryDirectory() as td:
        cd = _fake_config(td)
        sources, _sk = config_sources(cd)
        with open(os.path.join(cd, _serve().JOURNAL_NAME), 'w') as f:
            f.write('{}')
        t.refuses('a save that starts while the snapshot is being taken refuses',
                  lambda: snapshot_config(sources, os.path.join(td, 'snap'),
                                          b'cfg', cd), 'save started')

    print('\n[2b] every .json that ships parses, comments and trailing commas '
          'allowed')
    with tempfile.TemporaryDirectory() as td:
        cd = _fake_config(td)
        for rel, body in (('ckf.hardmode.json', '{"_version": "1.0.0"}'),
                          ('ckf.hardmode.rules.json',
                           '// a comment\n{"rules": [1, 2,], /* x */ }\n'),
                          ('ckf.hardmode.d/MissionPowerLevelModel.generated.json',
                           '{}')):
            with open(os.path.join(cd, *rel.split('/')), 'w') as f:
                f.write(body)
        t.check('the shipped JSON, written the way the engine reads it, passes',
                check_json(cd) is None)
        with open(os.path.join(cd, 'ckf.hardmode.d', 'late.rules.json'), 'w') as f:
            f.write('{"rules": [ oops ]}')
        t.refuses('an extra rules file that does not parse refuses, by name',
                  lambda: check_json(cd), 'late.rules.json')

    with tempfile.TemporaryDirectory() as td:
        cd = _fake_config(td)
        seen = {}
        v = _fake_vendor(td)
        dll = os.path.join(td, 'CKFHardMode.dll')
        with open(dll, 'wb') as f:
            f.write(b'MZ' + version_blob(csproj_version()) + b'\x00')
        with open(os.path.join(cd, DOC_NAME), 'w') as f:
            f.write('{"_version": "%s"}\n' % defaults_cs_doc_version())
        out = os.path.join(td, 'dist')
        os.makedirs(out)
        with open(os.path.join(out, EXE_NAMES[0]), 'wb') as f:
            f.write(b'exe')

        def _check(d):
            seen['check'] = d
            seen['listing'] = sorted(os.listdir(d))
            # Marks the snapshot's copy, so the zip can be shown to come
            # from the snapshot and not from a second read of the live file.
            with open(os.path.join(d, 'ckf.hardmode.selfcheck.csv'), 'ab') as f:
                f.write(b'#snap\n')

        def _gate(exe, **kw):
            seen['gate'] = kw.get('config_dir')
        try:
            z = build(out, v, dll, cd, skip_exe=True, echo=False,
                      gate_fn=_gate, check_fn=_check)
            with zipfile.ZipFile(z) as zf:
                shipped = dict((n, zf.read(n)) for n in zf.namelist()
                               if n.startswith(CONFIG_IN_ZIP))
        except Refused as e:
            z, shipped = None, {'refused': str(e)}
        t.check('a whole build checks and gates the snapshot, not the live '
                'directory, and the snapshot is gone afterwards',
                seen.get('check') and seen.get('check') == seen.get('gate')
                and os.path.dirname(seen['check']) != td
                and not os.path.exists(seen['check'])
                and CFG_NAME in seen.get('listing', ()), seen)
        t.check('and the zip carries the snapshot\'s bytes and the rendered .cfg',
                z is not None
                and all(shipped.get(CONFIG_IN_ZIP + r)
                        == read_bytes(os.path.join(cd, *r.split('/')))
                        + (b'#snap\n' if r == 'ckf.hardmode.selfcheck.csv' else b'')
                        for r in CONFIG_FILES)
                and shipped.get(CONFIG_IN_ZIP + CFG_NAME, b'').startswith(
                    b'## Settings file was created by plugin CKF Hard Mode v'
                    + csproj_version().encode()),
                sorted(shipped))

    print('\n[3] the document stamp and Defaults.DocVersion agree')
    with tempfile.TemporaryDirectory() as td:
        _fake_repo(td)
        cd = _fake_config(td)
        proj = os.path.join(td, 'mods', 'CKFHardMode')
        t.check('two files carrying the same stamp read back as one',
                check_doc_version(os.path.join(cd, DOC_NAME),
                                  os.path.join(proj, 'Defaults.cs'))
                == '3.0.0')

    with tempfile.TemporaryDirectory() as td:
        _fake_repo(td, doc_version='3.1.0')
        cd = _fake_config(td, doc_version='3.0.0')
        proj = os.path.join(td, 'mods', 'CKFHardMode')
        t.refuses('a document left behind the code refuses, naming both',
                  lambda: check_doc_version(os.path.join(cd, DOC_NAME),
                                            os.path.join(proj, 'Defaults.cs')),
                  'drifted apart')

    with tempfile.TemporaryDirectory() as td:
        _fake_repo(td)
        cd = _fake_config(td)
        proj = os.path.join(td, 'mods', 'CKFHardMode')
        doc = os.path.join(cd, DOC_NAME)
        with open(doc, 'w') as f:
            f.write('{"_version": "3.0.0",\n')
        t.refuses('a config document that is not JSON refuses rather than '
                  'shipping a file the mod cannot read',
                  lambda: check_doc_version(doc, os.path.join(proj, 'Defaults.cs')),
                  'not valid JSON')

    with tempfile.TemporaryDirectory() as td:
        _fake_repo(td)
        cd = _fake_config(td)
        proj = os.path.join(td, 'mods', 'CKFHardMode')
        with open(os.path.join(proj, 'Defaults.cs'), 'w') as f:
            f.write('namespace CKFHardMode { internal static class Defaults {} }')
        t.refuses('a Defaults.cs with no DocVersion refuses rather than '
                  'checking nothing',
                  lambda: check_doc_version(os.path.join(cd, DOC_NAME),
                                            os.path.join(proj, 'Defaults.cs')),
                  'no DocVersion string')

    t.check('the repo\'s own Defaults.cs carries a DocVersion to check against',
            bool(re.fullmatch(r'\d+\.\d+\.\d+', defaults_cs_doc_version())),
            DEFAULTS_CS)

    print('\n[3b] the config is validated before it ships')
    ok_teampl = _stub_teampl_cmd()
    t.check('a clean check_schema and a current mirror pass',
            check_config('x', _stub_schema_run(), ok_teampl) is None)
    t.refuses('a check_schema that did not finish refuses',
              lambda: check_config('x', _stub_schema_run(False, error='died'),
                                   ok_teampl), 'did not finish')
    t.refuses('any check_schema problem refuses and is listed, not only the '
              'classes a save blocks on',
              lambda: check_config('x', _stub_schema_run(problems=[
                  {'kind': 'UNKNOWN', 'message': 'fatigue.stray'}]), ok_teampl),
              'UNKNOWN  fatigue.stray')
    t.refuses('a stale Team PL mirror refuses',
              lambda: check_config('x', _stub_schema_run(),
                                   _stub_teampl_cmd(1, 'STALE')), 'STALE')
    t.refuses('a mirror check that exits 0 and prints nothing is not "current"',
              lambda: check_config('x', _stub_schema_run(),
                                   _stub_teampl_cmd(0, '')), 'exit 0')
    t.refuses('a mirror check that cannot be run refuses',
              lambda: check_config('x', _stub_schema_run(),
                                   [os.path.join(REPO, 'no-such-binary')]),
              'exit None')

    print('\n[4] the vendored BepInEx is the pinned build')
    with tempfile.TemporaryDirectory() as td:
        v = _fake_vendor(td)
        t.check('the pinned tree reads back as the pin',
                check_vendor(v) == (BE_BUILD, BE_COMMIT))

    # The fixture above only exercises the '5'-is-both-a-length-and-a-digit
    # bug while the pinned string happens to be 48..57 bytes long. Say so, so
    # that a future pin that loses the property fails here rather than
    # quietly turning the case above into a different test.
    _pin_len = len(('%s+%s' % (BE_BUILD, BE_COMMIT)).encode())
    t.check('the pinned version string is %d bytes, so its SerString length '
            'byte is an ASCII digit and the case above is the regression'
            % _pin_len, 0x30 <= _pin_len <= 0x39, _pin_len)

    t.check('a version-shaped string with no length byte in front of it is '
            'not read as the build',
            be_version(b'xx6.0.0-be.999+' + b'a' * 40 + b'yy') is None)
    _raw = ('9.9.9-be.1+' + 'b' * 40).encode()
    t.check('a properly prefixed string is read whole',
            be_version(b'\x00' + bytes([len(_raw)]) + _raw)
            == ('9.9.9-be.1', 'b' * 40))

    with tempfile.TemporaryDirectory() as td:
        t.refuses('an absent vendor tree refuses, and says where to get it',
                  lambda: check_vendor(os.path.join(td, 'vendor', VENDOR_DIRNAME)),
                  'builds.bepinex.dev')

    with tempfile.TemporaryDirectory() as td:
        v = _fake_vendor(td, build='6.0.0-be.786')
        t.refuses('a different BE build refuses, naming both',
                  lambda: check_vendor(v), '6.0.0-be.786')

    with tempfile.TemporaryDirectory() as td:
        v = _fake_vendor(td, commit='0' * 40)
        t.refuses('the pinned build number with a different commit refuses',
                  lambda: check_vendor(v), 'the pin is')

    with tempfile.TemporaryDirectory() as td:
        v = _fake_vendor(td, build=None)
        t.refuses('a core DLL with no version string refuses rather than '
                  'reading as unpinned',
                  lambda: check_vendor(v), 'cannot be established')

    with tempfile.TemporaryDirectory() as td:
        v = _fake_vendor(td, drop=('winhttp.dll',))
        t.refuses('a tree missing winhttp.dll refuses',
                  lambda: check_vendor(v), 'winhttp.dll')

    with tempfile.TemporaryDirectory() as td:
        v = _fake_vendor(td, extra=('BepInEx/config/ckf.hardmode.json',))
        t.refuses('a vendor tree carrying somebody\'s config refuses',
                  lambda: check_vendor(v), 'BepInEx/config/ckf.hardmode.json')

    with tempfile.TemporaryDirectory() as td:
        v = _fake_vendor(td, extra=('BepInEx/plugins/CKFDataDump.dll',))
        t.refuses('a vendor tree carrying a plugin refuses',
                  lambda: check_vendor(v), 'CKFDataDump.dll')

    # dotnet/ is 187 of the 232 files in the release and every other check
    # here passes without it. [measured, CKF-Hard-Mode-3.0.0.zip, 2026-09-04]
    with tempfile.TemporaryDirectory() as td:
        v = _fake_vendor(td, runtime=())
        t.refuses('a tree with no dotnet runtime refuses — it would extract, '
                  'install and not launch',
                  lambda: check_vendor(v), 'coreclr_path = dotnet/coreclr.dll')

    with tempfile.TemporaryDirectory() as td:
        v = _fake_vendor(td, runtime=('dotnet/coreclr.dll',))
        os.remove(os.path.join(v, 'dotnet', 'coreclr.dll'))
        t.refuses('an empty dotnet directory is not a runtime',
                  lambda: check_vendor(v), 'corlib_dir = dotnet')

    # Read out of the ini, not restated here: a build that moves the runtime
    # is followed, and a hand-edited ini is checked against what it says.
    with tempfile.TemporaryDirectory() as td:
        v = _fake_vendor(td, doorstop=_STUB_DOORSTOP.replace('dotnet', 'runtime6'))
        t.refuses('the refusal names the path the ini asks for, not one this '
                  'file hardcodes',
                  lambda: check_vendor(v), 'coreclr_path = runtime6/coreclr.dll')

    # Named on a path VENDOR_REQUIRED does not carry. Pointing it at
    # BepInEx.Unity.IL2CPP.dll and deleting that would be caught by the
    # required-file list instead, and the case would pass while asserting
    # nothing about the ini -- a fault reaching a different guard is not
    # coverage.
    with tempfile.TemporaryDirectory() as td:
        v = _fake_vendor(td, doorstop=_STUB_DOORSTOP.replace(
            'BepInEx\\core\\BepInEx.Unity.IL2CPP.dll',
            'BepInEx\\core\\Custom.Loader.dll'))
        t.refuses('and the assembly doorstop is told to load is checked too, '
                  'whatever it is called',
                  lambda: check_vendor(v), 'target_assembly = BepInEx/core/Custom.Loader.dll')

    # The parser, on the real file's shape: sections, backslashes, and the
    # comment lines BepInEx puts above every key. If this stopped finding
    # anything, every case above would pass by finding nothing to check.
    with tempfile.TemporaryDirectory() as td:
        v = _fake_vendor(td)
        got = doorstop_wants(v)
        t.check('the ini parser finds all three keys, so the cases above are '
                'not passing by reading an empty list',
                got == [('target_assembly', 'BepInEx/core/BepInEx.Unity.IL2CPP.dll'),
                        ('coreclr_path', 'dotnet/coreclr.dll'),
                        ('corlib_dir', 'dotnet')], got)
    with tempfile.TemporaryDirectory() as td:
        v = _fake_vendor(td, doorstop='# coreclr_path = dotnet\\nope.dll\n'
                                      + _STUB_DOORSTOP)
        t.check('a commented-out key is not read as a requirement',
                len(doorstop_wants(v)) == 3, doorstop_wants(v))

    print('\n[5] the gate')
    g = run_gate(_stub_gate_cmd(301, 0, 0))
    t.check('a clean run reads as 301 passed', g['ran'] and g['passed'] == 301
            and g['failed'] == 0, g)
    t.check('a clean run refuses nothing',
            gate('x', cmd=_stub_gate_cmd(301, 0, 0), echo=False)['passed'] == 301)

    t.refuses('a run with a failure refuses, and quotes the FAIL lines',
              lambda: gate('x', cmd=_stub_gate_cmd(299, 2, 0, fail_lines=2),
                           echo=False),
              'stub case 0')

    # The half that was missing on David's first Windows run. The name of the
    # frozen-teardown case is the same whether a process really survived, the
    # instrument could not look, or something unrelated matched -- only the
    # detail line says which.
    t.refuses('and quotes the DETAIL under each FAIL, not just its name',
              lambda: gate('x', cmd=_stub_gate_cmd(299, 2, 0, fail_lines=2),
                           echo=False),
              'detail for 1')

    g = run_gate(_stub_gate_cmd(299, 2, 2, fail_lines=2))
    t.check('a FAIL block stops at the next case rather than swallowing it',
            g['fails'] == ['FAIL  stub case 0\n        detail for 0',
                           'FAIL  stub case 1\n        detail for 1'], g['fails'])
    t.check('and the NOT RUN blocks carry their reasons too',
            len(g['lines']) == 2 and all('no sampling moment' in b
                                         for b in g['lines']), g['lines'])

    # _T prints every NOT RUN twice -- once in place with the reason on the
    # next line, once in the trailing summary as `<name> -- <reason>`. Keyed
    # on the whole block those are two different strings and a two-case run
    # prints four lines.
    g2 = run_gate([sys.executable, '-c',
                   "print('  NOT RUN  a case\\n           because reasons')\n"
                   "print('\\ngui/serve.py verification: 1 passed, 0 failed, "
                   "1 not run')\nprint('  NOT RUN  a case -- because reasons')"])
    t.check('a NOT RUN printed in place and again in the summary is one case',
            len(g2['lines']) == 1 and 'because reasons' in g2['lines'][0],
            g2['lines'])
    t.check('the report line is not read as a case',
            not any('verification:' in b for b in g['fails'] + g['lines']))

    with tempfile.TemporaryDirectory() as td:
        t.refuses('a refusal writes the whole run to a log and names it',
                  lambda: gate('x', cmd=_stub_gate_cmd(299, 2, 0, fail_lines=2),
                               echo=False, log_dir=td),
                  'selftest-failed.log')
        log = os.path.join(td, 'selftest-failed.log')
        t.check('and that log holds the command and every line of output',
                os.path.exists(log)
                and 'stub case 1' in read_text(log)
                and 'verification: 299 passed' in read_text(log),
                sorted(os.listdir(td)))

    with tempfile.TemporaryDirectory() as td:
        t.refuses('a suite that printed no report also gets its output logged',
                  lambda: gate('x', cmd=_stub_gate_cmd(report=False, fail_lines=1),
                               echo=False, log_dir=td),
                  'selftest-failed.log')
        t.check('even though there was no report line to parse',
                'stub case 0' in read_text(os.path.join(td,
                                                        'selftest-failed.log')))

    with tempfile.TemporaryDirectory() as td:
        gate('x', cmd=_stub_gate_cmd(301, 0, 0), echo=False, log_dir=td)
        t.check('a clean run leaves no failure log behind', os.listdir(td) == [],
                os.listdir(td))

    t.refuses('a suite that dies before printing its report refuses rather '
              'than reading as clean',
              lambda: gate('x', cmd=_stub_gate_cmd(report=False), echo=False),
              'printed no report line')

    t.refuses('a suite that prints FAIL lines and then dies still refuses',
              lambda: gate('x', cmd=_stub_gate_cmd(report=False, fail_lines=3),
                           echo=False),
              'printed no report line')

    t.refuses('a command that cannot be run at all refuses',
              lambda: gate('x', cmd=[os.path.join(REPO, 'no-such-binary')],
                           echo=False),
              'printed no report line')

    g = gate('x', cmd=_stub_gate_cmd(285, 0, 2), echo=False)
    t.check('NOT RUN does not refuse, and both lines are carried out',
            g['notrun'] == 2 and len(g['lines']) == 2, g['lines'])

    print('\n[6] the text files that are rendered, not copied')
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, 'README.txt.in')
        with open(p, 'w') as f:
            f.write('v@VERSION@ on BepInEx @BE_BUILD@ (@BE_COMMIT@)\n')
        out = render(p, '3.0.0')
        t.check('the placeholders are filled and the file is CRLF',
                out == ('v3.0.0 on BepInEx %s (%s)\r\n' % (BE_BUILD, BE_COMMIT)).encode(),
                out)
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, 'README.txt.in')
        with open(p, 'w') as f:
            f.write('already \r\n windows \r\n endings\r\n')
        t.check('a template already saved with CRLF is not doubled',
                render(p, '3.0.0').count(b'\r') == 3)
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, 'README.txt.in')
        with open(p, 'w') as f:
            f.write('v@VERSION@ built @BUILD_DATE@\n')
        t.refuses('a placeholder nothing fills refuses rather than shipping '
                  'the literal',
                  lambda: render(p, '3.0.0'), '@BUILD_DATE@')
    for name in ('README.txt', 'LICENSE-BepInEx.txt'):
        src = os.path.join(RELEASE_DIR, name + '.in')
        t.check('release/%s.in is on disk and renders' % name,
                os.path.exists(src) and len(render(src, '0.0.0')) > 500,
                src)
    # Guarded on the file being there, not because its absence is acceptable --
    # the case above already fails on that -- but because an unguarded render
    # raises out of selftest() and the run ends with no report line at all,
    # which is the one shape a verification suite must not fail in.
    _lic = os.path.join(RELEASE_DIR, 'LICENSE-BepInEx.txt.in')
    t.check('the licence header names the pinned build and its commit',
            os.path.exists(_lic)
            and all(s in render(_lic, '0.0.0').decode()
                    for s in (BE_BUILD, BE_COMMIT,
                              'LESSER GENERAL PUBLIC LICENSE')),
            _lic)
    # BepInEx rewrites this file on launch, so what ships has to be what
    # BepInEx would have written: CRLF, the version in the header comment, and
    # the one key it binds.
    _cfg = render(os.path.join(RELEASE_DIR, 'ckf.hardmode.cfg.in'), '9.9.9')
    t.check('the master switch renders with its version, its section and its '
            'one key',
            _cfg.startswith(b'## Settings file was created by plugin '
                            b'CKF Hard Mode v9.9.9\r\n')
            and b'\r\n[General]\r\n' in _cfg
            and b'\r\nEnabled = true\r\n' in _cfg
            and b'\n' not in _cfg.replace(b'\r\n', b''),
            _cfg)
    # A template added to release/ and not to TEMPLATES is rendered by nothing
    # and reaches no player, and nothing else here would notice.
    _orphans = sorted(set(n for n in os.listdir(RELEASE_DIR)
                          if n.endswith('.in'))
                      - set(n for n, _ in TEMPLATES))
    t.check('every template in release/ has a path in the zip', not _orphans,
            _orphans)

    print('\n[7] the zip')
    with tempfile.TemporaryDirectory() as td:
        members = {'b.txt': b'two', 'a/c.txt': b'three', 'a.txt': b'one'}
        p1 = write_zip(os.path.join(td, 'one.zip'), members)
        import time
        time.sleep(1.1)
        p2 = write_zip(os.path.join(td, 'two.zip'), members)
        t.check('two runs over the same inputs are byte-identical',
                read_bytes(p1) == read_bytes(p2))
        with zipfile.ZipFile(p1) as z:
            t.check('names are sorted and the tree is preserved',
                    z.namelist() == ['a.txt', 'a/c.txt', 'b.txt'], z.namelist())
            t.check('contents round-trip', z.read('a/c.txt') == b'three')
        p3 = write_zip(os.path.join(td, 'three.zip'),
                       dict(members, **{'a.txt': b'ONE'}))
        t.check('one changed byte changes the zip',
                read_bytes(p1) != read_bytes(p3))
        t.check('nothing is left behind by a completed write',
                not [n for n in os.listdir(td) if n.endswith('.part')],
                os.listdir(td))

    print('\n[8] the release refuses before it writes anything')
    with tempfile.TemporaryDirectory() as td:
        out = os.path.join(td, 'dist')
        t.refuses('a missing plugin DLL refuses',
                  lambda: build(out, os.path.join(td, 'vendor'),
                                os.path.join(td, 'nope.dll'),
                                _fake_config(td), echo=False),
                  'dotnet build -c Release')
        t.check('and wrote nothing to the output directory',
                not os.path.exists(out))

    return t.report()


# ---------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(
        description='Assemble the CKF Hard Mode player zip.')
    ap.add_argument('--out', default=os.path.join(REPO, 'dist'),
                    help='where the exe is built and the zip is written '
                         '(default: dist/)')
    ap.add_argument('--vendor',
                    default=os.path.join(REPO, 'vendor', VENDOR_DIRNAME),
                    help='the unpacked pinned BepInEx tree')
    ap.add_argument('--dll', default=DEFAULT_DLL,
                    help='the built CKFHardMode.dll')
    ap.add_argument('--config',
                    help='the BepInEx/config directory to package (default: '
                         'the one the editor edits, from gui/settings.json)')
    ap.add_argument('--skip-exe', action='store_true',
                    help='use the editor binary already in --out instead of '
                         'building one. The gate still runs against it.')
    ap.add_argument('--selftest', action='store_true',
                    help='prove every refusal in this file can fire')
    a = ap.parse_args(argv)

    if a.selftest:
        return selftest()
    try:
        build(a.out, a.vendor, a.dll,
              os.path.abspath(a.config) if a.config else default_config_dir(),
              skip_exe=a.skip_exe)
    except Refused as e:
        print('\nREFUSED: %s' % e, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
