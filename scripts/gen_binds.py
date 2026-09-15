#!/usr/bin/env python3
"""Generate mods/CKFHardMode/Plugin.Binds.g.cs from schema/*.schema.json.

Every schema field with "in": "cfg" becomes one row in a generated table:
section, key, CLR type, default value. Nothing else. In particular there is no
description argument, which is the whole point of the exercise: BepInEx writes a
"## <description>" block into ckf.hardmode.cfg for every bound key, so a
Config.Bind call that passes no description writes no prose. See gui-plan.md
section 3.2 -- the "# Setting type:" / "# Default value:" pair survives either
way, because those two strings are literals inside BepInEx.Core.dll.

ONE BIND PER SLICE, CHECKED BOTH WAYS. A slice is a schema file declaring
targets.cfg; its toggle is that file's one "in": "cfg" field. The two sets are
compared in both directions and a mismatch is a non-zero exit from --check AND
from a plain run, never a silently smaller table:

  a slice with no key   a schema declaring targets.cfg and no "in": "cfg" field.
                        Its toggle would not exist and the slice could not be
                        turned off.
  a key with no slice   an "in": "cfg" field in a schema that declares no
                        targets.cfg. BepInEx would write a key into
                        ckf.hardmode.cfg that gates nothing.
  two keys in one slice one toggle per slice is the rule; a second key in the
                        same schema means two gates for one file.
  a dangling enable.cfg an "enable": {"cfg": ...} naming a key no schema
                        declares as a field. check_schema.py counts such a key
                        as declared (check_schema.py:235-237) but never looks
                        for it on disk, so nothing else reports it.

Output is deterministic: rows are sorted by (section, key) with an ordinal
sort, so the same schema directory always produces a byte-identical file.

Usage:
    python3 scripts/gen_binds.py [--schema DIR] [--out FILE]

Stdlib only.
"""

import argparse
import glob
import json
import os
import sys

# schema "type" -> the CLR type Config.Bind is called with.
#
# stringList is a comma-separated string in the .cfg (SCHEMA-FORMAT.md), so its
# CLR type is string; the splitting happens in the subsystem, not in Bind.
# floatOrNaN is a float whose NaN value carries a meaning, likewise not Bind's
# business. Anything not listed here is a hard error rather than a guess.
CLR_TYPES = {
    "bool": "bool",
    "int": "int",
    "float": "float",
    "floatOrNaN": "float",
    "string": "string",
    "stringList": "string",
}

# The one file this generator emits binds for. A schema naming any other file
# in targets.cfg is a defect, not a second output.
CFG_FILE = "ckf.hardmode.cfg"

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_SCHEMA_DIR = os.path.join(REPO_ROOT, "schema")
DEFAULT_OUT = os.path.join(REPO_ROOT, "mods", "CKFHardMode", "Plugin.Binds.g.cs")


class SchemaError(Exception):
    pass


def cs_string(value):
    """A C# string literal for a Python str."""
    out = ['"']
    for ch in value:
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        elif ord(ch) < 0x20:
            out.append("\\u%04x" % ord(ch))
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def cs_default(clr, value, where):
    """A C# literal of type `clr` for a JSON default."""
    if clr == "bool":
        if not isinstance(value, bool):
            raise SchemaError("%s: bool default is %r" % (where, value))
        return "true" if value else "false"

    if clr == "int":
        # bool is a subclass of int in Python; reject it explicitly.
        if isinstance(value, bool) or not isinstance(value, int):
            raise SchemaError("%s: int default is %r" % (where, value))
        return str(value)

    if clr == "float":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise SchemaError("%s: float default is %r" % (where, value))
        text = repr(float(value))
        if text in ("inf", "-inf", "nan"):
            raise SchemaError(
                "%s: non-finite float default %r has no C# literal" % (where, value)
            )
        return text + "f"

    if clr == "string":
        if not isinstance(value, str):
            raise SchemaError("%s: string default is %r" % (where, value))
        return cs_string(value)

    raise SchemaError("%s: no literal form for CLR type %s" % (where, clr))


def collect(schema_dir):
    """Read every *.schema.json and return the cfg rows, sorted and checked.

    Also called by scripts/gen_cfg_template.py, which emits the OTHER file this
    key set defines -- release/ckf.hardmode.cfg.in, the .cfg the zip ships.
    The two generators share this function on purpose: the slice/key
    correspondence is checked once, so the C# table and the shipped .cfg cannot
    come to disagree about which keys exist. Each row therefore carries the
    schema "type" and the raw JSON "default" as well as the C# literal, because
    the .cfg needs BepInEx's spelling of both and not C#'s.
    """
    paths = sorted(glob.glob(os.path.join(schema_dir, "*.schema.json")))
    if not paths:
        raise SchemaError("no *.schema.json under %s" % schema_dir)

    rows = []
    seen = {}
    slices = []          # schema files declaring targets.cfg, in read order
    cfg_fields = {}      # schema file -> [Section.Key, ...] declared in it
    enable_cfg = {}      # schema file -> the enable.cfg key it names, if any
    for path in paths:
        name = os.path.basename(path)
        with open(path, "r", encoding="utf-8") as handle:
            schema = json.load(handle)

        target_cfg = (schema.get("targets") or {}).get("cfg")
        if target_cfg:
            if target_cfg != CFG_FILE:
                raise SchemaError(
                    "%s: targets.cfg is %r; this generator emits binds for %s "
                    "only" % (name, target_cfg, CFG_FILE)
                )
            slices.append(name)
        cfg_fields[name] = []
        ek = (schema.get("enable") or {}).get("cfg")
        if ek:
            enable_cfg[name] = ek

        for index, field in enumerate(schema.get("fields", [])):
            if field.get("in") != "cfg":
                continue

            where = "%s fields[%d]" % (name, index)
            dotted = field.get("path")
            if not isinstance(dotted, str) or dotted.count(".") != 1:
                raise SchemaError(
                    "%s: cfg path must be Section.Key, got %r" % (where, dotted)
                )
            section, key = dotted.split(".", 1)
            if not section or not key:
                raise SchemaError("%s: empty section or key in %r" % (where, dotted))

            schema_type = field.get("type")
            if schema_type not in CLR_TYPES:
                raise SchemaError(
                    "%s (%s): unsupported cfg type %r" % (where, dotted, schema_type)
                )
            clr = CLR_TYPES[schema_type]

            if "default" not in field:
                raise SchemaError("%s (%s): no default" % (where, dotted))
            literal = cs_default(clr, field["default"], "%s (%s)" % (where, dotted))

            if dotted in seen:
                raise SchemaError(
                    "%s declared twice: %s and %s" % (dotted, seen[dotted], name)
                )
            seen[dotted] = name
            cfg_fields[name].append(dotted)

            rows.append(
                {
                    "section": section,
                    "key": key,
                    "clr": clr,
                    "literal": literal,
                    "schema": name,
                    "type": schema_type,
                    "default": field["default"],
                }
            )

    # ---- the slice set and the key set, compared in both directions.
    #
    # Both halves are defects in the schema directory, not states a player can
    # reach, so they stop the run rather than producing a table that is quietly
    # missing a toggle or quietly carrying a spare one.
    problems = []
    for name in slices:
        keys = cfg_fields[name]
        if not keys:
            problems.append(
                "%s declares targets.cfg but no \"in\": \"cfg\" field: the slice "
                "has no key and could not be turned off" % name
            )
        elif len(keys) > 1:
            problems.append(
                "%s declares targets.cfg and %d cfg keys (%s): one toggle per "
                "slice" % (name, len(keys), ", ".join(sorted(keys)))
            )
    for name in sorted(cfg_fields):
        if cfg_fields[name] and name not in slices:
            problems.append(
                "%s declares cfg key(s) %s but no targets.cfg: the key has no "
                "slice and would gate nothing"
                % (name, ", ".join(sorted(cfg_fields[name])))
            )
    for name in sorted(enable_cfg):
        if enable_cfg[name] not in seen:
            problems.append(
                "%s: enable.cfg names %r, which no schema declares as a field. "
                "check_schema.py counts it as declared and never looks for it "
                "on disk" % (name, enable_cfg[name])
            )
    if problems:
        raise SchemaError(
            "slice set and key set disagree:\n  " + "\n  ".join(problems)
        )

    rows.sort(key=lambda row: (row["section"], row["key"]))
    return rows


HEADER = """// <auto-generated>
//
//   Plugin.Binds.g.cs
//
//   GENERATED by scripts/gen_binds.py from schema/*.schema.json.
//   Do not hand-edit. Change the schema and re-run:
//
//       python3 scripts/gen_binds.py
//
//   One row per schema field with "in": "cfg" -- section, key, CLR type and
//   default. There is deliberately NO description argument. BepInEx writes a
//   "## <description>" block into ckf.hardmode.cfg for every bound key, so
//   binding without a description is what keeps the prose out of the file
//   (docs/gui-plan.md section 3.2). The "# Setting type:" and
//   "# Default value:" pair still appears: those two strings are literals
//   inside BepInEx.Core.dll with no public switch, and are out of scope.
//
//   The prose itself now lives in the schema's `doc` arrays, rendered into
//   docs/config-reference.md.
//
//   ONE KEY PER SLICE. A slice is a schema file declaring targets.cfg; its
//   toggle is that file's one "in": "cfg" field. gen_binds.py compares the two
//   sets in both directions and refuses to write this file if they disagree --
//   a slice with no key, a key with no slice, two keys in one slice, or an
//   enable.cfg naming a key no schema declares as a field.
//
//   THE COUNT BELOW IS THE COUNT IN ckf.hardmode.cfg. Slices.Init binds every
//   row of this table (Slices.cs) and Plugin.Load calls it ABOVE the
//   master-switch bail-out, so BepInEx writes a line for all of them on any
//   launch, including one where the mod is switched off.
//
//   CORRECTION, 2026-09-13. This paragraph used to read "THE COUNT BELOW IS NOT
//   THE COUNT IN ckf.hardmode.cfg. This table is a declaration; a key reaches
//   the file only when something calls Bind for it, and Plugin.cs:161 is the
//   only call site. Every other key here is declared and unbound, so BepInEx
//   writes no line for it and schema/check_schema.py reports it MISSING until a
//   caller exists and the game has been launched." It was true when written and
//   is false now: Slices.cs was added and Plugin.cs no longer binds anything
//   directly. It is quoted rather than deleted because it is the shape of claim
//   that goes stale silently -- a statement about what some other file does, in
//   a generated header nobody re-reads.
//
//   CITATIONS HERE NAME A MEMBER, NOT A LINE. The quoted paragraph above cited
//   Plugin.cs:161, and that citation was stale within hours of being written
//   because the line moved. A member name survives every edit to its file that
//   does not rename it, and a rename makes the citation fail loudly under grep
//   instead of silently pointing at whatever now occupies the line.
//
// </auto-generated>

using System;
using System.Collections.Generic;
using BepInEx.Configuration;

namespace CKFHardMode
{
    /// <summary>
    /// The single declaration of every key in ckf.hardmode.cfg.
    ///
    /// A subsystem binds through <see cref="Bind{T}"/> rather than calling
    /// <c>ConfigFile.Bind</c> itself, so the section, key, type and default
    /// are stated once, here, and match the schema by construction.
    ///
    /// Bind is a real <c>ConfigFile.Bind</c> call, and every row of
    /// <see cref="All"/> now gets one: <c>Slices.Init</c> walks the table at
    /// startup (Slices.cs) and binds each key, so BepInEx writes the whole file
    /// rather than whichever keys a subsystem happened to reach.
    ///
    /// CORRECTION, 2026-09-13. This paragraph used to end "BepInEx writes the
    /// file from the set of keys actually bound, and a key nothing binds is
    /// left in place as an orphan. Binding every key eagerly would change that,
    /// so this class does not do it." The first sentence still holds; the last
    /// one is reversed. Eager binding is now the point of the table, because a
    /// toggle a player cannot see in ckf.hardmode.cfg is a toggle they cannot
    /// use, and binding under the master-switch bail-out would have left a
    /// fresh install with Enabled = false carrying no [Slices] lines at all.
    /// The orphan rule is unchanged and is why the count matters: a key this
    /// table stops declaring stays in the file until someone deletes the line.
    ///
    /// The one call site is the <c>Binds.Bind</c> in <c>Slices.Init</c>.
    /// </summary>
    internal static class Binds
    {
        /// <summary>One declared cfg key. See <see cref="Def{T}"/> for the value.</summary>
        internal abstract class Def
        {
            internal readonly string Section;
            internal readonly string Key;

            protected Def(string section, string key)
            {
                Section = section;
                Key = key;
            }

            /// <summary>"Section.Key", the form used in the .cfg and the schema.</summary>
            internal string Id { get { return Section + "." + Key; } }

            /// <summary>The CLR type this key's default was declared with.</summary>
            internal abstract Type ValueType { get; }
        }

        /// <summary>A declared cfg key of a known type.</summary>
        internal sealed class Def<T> : Def
        {
            internal readonly T Default;

            internal Def(string section, string key, T defaultValue)
                : base(section, key)
            {
                Default = defaultValue;
            }

            internal override Type ValueType { get { return typeof(T); } }
        }

"""

FOOTER = """
        private static readonly Dictionary<string, Def> ById = BuildIndex();

        private static Dictionary<string, Def> BuildIndex()
        {
            var map = new Dictionary<string, Def>(All.Length, StringComparer.Ordinal);
            foreach (var def in All)
                map[def.Id] = def;
            return map;
        }

        /// <summary>
        /// Bind one declared key and return its entry.
        ///
        /// A key the table does not declare, or one asked for at the wrong type,
        /// is a defect in this file or in the caller -- not a configuration the
        /// player can reach. It logs and throws rather than handing back
        /// default(T), because a wrong-typed default that silently works is
        /// exactly the class of bug AGENTS.md section 3 is about: the caller
        /// would read a plausible number and have no way to tell it apart from
        /// a real one.
        /// </summary>
        internal static ConfigEntry<T> Bind<T>(ConfigFile config, string section, string key)
        {
            if (config == null) throw new ArgumentNullException("config");

            var id = section + "." + key;

            Def def;
            if (!ById.TryGetValue(id, out def))
                throw Fail("Binds: \\"" + id + "\\" is not declared in Plugin.Binds.g.cs. "
                         + "Add it to the matching schema/*.schema.json and re-run "
                         + "scripts/gen_binds.py.");

            var typed = def as Def<T>;
            if (typed == null)
                throw Fail("Binds: \\"" + id + "\\" is declared " + def.ValueType.Name
                         + " but was requested as " + typeof(T).Name + ".");

            // No description argument. See the header.
            return config.Bind(section, key, typed.Default);
        }

        /// <summary>Bind one declared key and return its value.</summary>
        internal static T Value<T>(ConfigFile config, string section, string key)
        {
            return Bind<T>(config, section, key).Value;
        }

        private static Exception Fail(string message)
        {
            // Plugin.Log is assigned first thing in Plugin.Load, but this can be
            // reached from a test harness where it is not.
            if (Plugin.Log != null) Plugin.Log.LogError(message);
            return new InvalidOperationException(message);
        }
    }
}
"""


def render(rows):
    lines = [HEADER]
    lines.append("        /// <summary>Every key in ckf.hardmode.cfg, %d of them.</summary>\n"
                 % len(rows))
    lines.append("        internal static readonly Def[] All =\n        {\n")

    # Column-align the literals so a diff of this file reads as a table.
    section_w = max(len(cs_string(row["section"])) for row in rows)
    key_w = max(len(cs_string(row["key"])) for row in rows)
    clr_w = max(len(row["clr"]) for row in rows)

    previous = None
    for row in rows:
        if previous is not None and row["section"] != previous:
            lines.append("\n")
        previous = row["section"]
        lines.append(
            "            new Def<%s>(%s %s %s),\n"
            % (
                row["clr"].ljust(clr_w),
                (cs_string(row["section"]) + ",").ljust(section_w + 1),
                (cs_string(row["key"]) + ",").ljust(key_w + 1),
                row["literal"],
            )
        )

    lines.append("        };\n")
    lines.append(FOOTER)
    return "".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Generate Plugin.Binds.g.cs from schema/*.schema.json."
    )
    parser.add_argument("--schema", default=DEFAULT_SCHEMA_DIR,
                        help="directory of *.schema.json (default: %(default)s)")
    parser.add_argument("--out", default=DEFAULT_OUT,
                        help="file to write (default: %(default)s)")
    parser.add_argument("--check", action="store_true",
                        help="do not write; exit 1 if --out is missing or stale")
    args = parser.parse_args(argv)

    try:
        rows = collect(args.schema)
    except SchemaError as err:
        sys.stderr.write("gen_binds: %s\n" % err)
        return 2

    text = render(rows)

    if args.check:
        try:
            with open(args.out, "r", encoding="utf-8", newline="") as handle:
                current = handle.read()
        except IOError:
            sys.stderr.write("gen_binds: %s does not exist\n" % args.out)
            return 1
        if current != text:
            sys.stderr.write("gen_binds: %s is stale; re-run without --check\n" % args.out)
            return 1
        sys.stdout.write("gen_binds: %s is up to date (%d cfg key(s)).\n"
                         % (args.out, len(rows)))
        return 0

    directory = os.path.dirname(os.path.abspath(args.out))
    if directory and not os.path.isdir(directory):
        os.makedirs(directory)

    # newline="\n" so the output does not pick up the host's line ending.
    with open(args.out, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)

    sys.stdout.write("gen_binds: wrote %s (%d cfg key(s) from %s).\n"
                     % (args.out, len(rows), args.schema))
    return 0


if __name__ == "__main__":
    sys.exit(main())
