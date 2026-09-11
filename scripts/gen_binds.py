#!/usr/bin/env python3
"""Generate mods/CKFHardMode/Plugin.Binds.g.cs from schema/*.schema.json.

Every schema field with "in": "cfg" becomes one row in a generated table:
section, key, CLR type, default value. Nothing else. In particular there is no
description argument, which is the whole point of the exercise: BepInEx writes a
"## <description>" block into ckf.hardmode.cfg for every bound key, so a
Config.Bind call that passes no description writes no prose. See gui-plan.md
section 3.2 -- the "# Setting type:" / "# Default value:" pair survives either
way, because those two strings are literals inside BepInEx.Core.dll.

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
    """Read every *.schema.json and return the cfg rows, sorted and checked."""
    paths = sorted(glob.glob(os.path.join(schema_dir, "*.schema.json")))
    if not paths:
        raise SchemaError("no *.schema.json under %s" % schema_dir)

    rows = []
    seen = {}
    for path in paths:
        name = os.path.basename(path)
        with open(path, "r", encoding="utf-8") as handle:
            schema = json.load(handle)

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

            rows.append(
                {
                    "section": section,
                    "key": key,
                    "clr": clr,
                    "literal": literal,
                    "schema": name,
                }
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
    /// Bind is still a real <c>ConfigFile.Bind</c> call made at the same point
    /// in startup as the hand-written call it replaced: BepInEx writes the file
    /// from the set of keys actually bound, and a key nothing binds is left in
    /// place as an orphan. Binding every key eagerly would change that, so this
    /// class does not do it.
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
