# Static content and runtime evidence

`scripts/static_data.py` reads the developer-provided `Official/data.db` for
static content. The database stays outside Git and the player release. It is
opened read-only; tools never install it into the game or change live tuning
while reading it. Public source builds and normal editor use do not require
this maintainer database.

## Replace the database after a game patch

Close tools using the database, download the developer's new file, and replace
`D:\ckf-data-modding\Official\data.db`. No export or regeneration is needed
before reading it. Replace `Official/en-US.json` too when an updated locale is
available. Without that file, display labels show their locale keys; numeric
content does not come from the locale.

Run the source check:

```bat
cd /d "D:\ckf-data-modding"
python "D:\ckf-data-modding\scripts\static_data.py" --check
```

It prints the database path, SHA-256, current table/row counts, and checks the
declared column targets of the lever tools. Additional rows, columns, and
tables are read automatically. Missing required tables/columns, corrupt
databases, and incomplete reads fail by name. There is no automatic fallback
to an older CSV dump. Each read opens a fresh transaction; replacement during
a transaction refuses the result rather than mixing database versions.

Then run the existing validators against the live tuning:

```bat
python "D:\ckf-data-modding\scripts\validate_rules.py" --game "C:\Program Files (x86)\Steam\steamapps\common\Cyber Knights Flashpoint" --enabled-set --quiet
python "D:\ckf-data-modding\scripts\gear_classes.py" --check --game "C:\Program Files (x86)\Steam\steamapps\common\Cyber Knights Flashpoint"
python "D:\ckf-data-modding\scripts\cyberweapons.py" --check --game "C:\Program Files (x86)\Steam\steamapps\common\Cyber Knights Flashpoint"
python "D:\ckf-data-modding\scripts\implants.py" --check --game "C:\Program Files (x86)\Steam\steamapps\common\Cyber Knights Flashpoint"
python "D:\ckf-data-modding\scripts\consumables.py" --check --game "C:\Program Files (x86)\Steam\steamapps\common\Cyber Knights Flashpoint"
```

The validators use current database identities and columns, without comparing
against a previous static dump or a frozen row count. Sparse enemy overlays are
valid; when class levers are active, the validator checks whether those rules
actually reach weapons in the current effective enemy pointers.

After item additions or class/pointer changes, refresh consumable sheets:

```bat
python "D:\ckf-data-modding\scripts\consumables.py" --write --check --game "C:\Program Files (x86)\Steam\steamapps\common\Cyber Knights Flashpoint"
```

This adds blank rows, moves items to their current class, and refreshes generated
shipped comments. Existing adjustments are preserved at the same table/id/column;
refresh refuses if an adjustment would lose its target or declared lever. Reading
or replacing the database never writes tuning. Generators require explicit write
commands. Missing required columns, invalid pointers and malformed sheets remain
real errors requiring review.

## Names and numbers

Consumers use runtime model names. The shared reader translates SQL
`PetChassis`/`PetPrebuilt` to `DroneChassisModel`/`DronePrebuiltModel`, translates
their key columns, and handles the lowercase `CharacterLevel` and cosmetic
blendshape columns. Other SQL tables map to their `Model` names. Locale joins
provide display labels; computed combat properties and session fields are
never fabricated.

SQLite's declared `INTEGER` affinity permits fractional numeric storage.
For numeric values in those columns, the model view rounds to the nearest
integer, with ties to even; `REAL` fields retain their fractions. Text stored
under integer affinity remains text (for example, a door-type identifier).
Primary-key values must already be integral when numeric. The Python API's
`raw=True` view retains the original database values for inspection.

The reader's tests use independent synthetic databases. Static-data commands
accept `--data PATH`; `--dump PATH` remains a database-path alias for older command
lines. Static CSV directories are rejected. The mission-roster tool keeps `--dump` for
its runtime probes and uses a separate `--data` for static content. Maintainer
talent-catalog completion and the editor also accept `--data`. The editor
uses current official baselines and RuleModel reference rows, including newly
added rules, refreshing them on reload without rewriting `_shipped` metadata
or lever cells. A
selected but unreadable database shows unknown baselines and its error.
Installed editors without an official database retain the metadata mode.
Catalog completion and migration never run automatically when the database
changes. A frozen editor built under the checkout's `dist/` finds the same
`Official/` directory in the checkout; an installed copy can use
`--data "D:\ckf-data-modding\Official\data.db"` without another database copy.

## Keep the runtime probes

Game/Core rows, campaign history, generated missions, actual rewards, character
bars, AI traces, enums and constant names remain runtime evidence. Read their
captures explicitly; the static reader refuses runtime table requests.
`validate_rules.py --probes DIR` can add captured Game/Core tables without
letting the capture override official static tables. `talent_value.py --probes
DIR` reads `_id_constants.csv` there while its content comes from the database.

Use [Data Dump's instruments and sampling limits](../mods/CKFDataDump/README.md)
for those questions. A static database cannot establish what a hook observed
or how a particular campaign played out.
