# Hire Everyone Workshop mod

`scripts/build_hire_everyone.py` prepares additive character availability for
the `HireEveryone` Modkit project and the requested local Workshop folder
`3841540859`. The builder does not run the game, open a save, activate a mod,
or submit anything to Steam.

## Scope and authoring

The explicit `HUB` and `STARTERS` declarations own the included characters.
The builder checks them against the available Hub recruitment blocks and the
combat starter rows in the current `Official/data.db`; a changed roster refuses
preparation until reviewed. Content and localization come from the official
database and locale through the [static reader](static-data.md).

Hub characters receive separate starting-only Backstory templates. Their
original templates and Hub recruitment blocks are untouched. The new templates
use BackstoryGroup 1 and these NewGame slots, as specified by David:

| Classes | Slot |
|---|---|
| Hacker, Wireghost | 4 |
| Vanguard, Agent EX | 3 |
| Other combat classes | 5 |

The clones preserve native class, cosmetics, implants, base trait fields,
identity and tags. Their new initialization blocks copy the native recruitment
setup without creating the main character again, translate its temporary actor
reference to the permanent identity, and invoke the existing casting group when
one is referenced. They set the native recruitment's hired flag. Hacker and
Wireghost initialization also adds `PersonID_StartingHacker`, the tag present
on the native starting hackers. Menu descriptions use the native backstory text
when available, otherwise the associated backstory trait's localized text.
The builder does not translate choices in recruitment conversations into
additional starting variants.

The existing combat starters receive new Hub entries in their respective class
groups. These use the original Backstory ID, a HasCharacter condition against
the character's identity tag, distinct hired/cooldown states, and new recruitment
nodes. The offer exposes recruit, delay and decline choices, using the native
60-turn offer and 360-turn rejection cooldown values. Candidate setup creates
linked contacts only when their identity is absent, then invokes the original
backstory block group. Hiring uses the native Recruit/TempStoryId cleanup shape;
declining uses Purge and the cooldown node.

Faces and the player's Cyber Knight are outside the authored recruitment scope.
The four unfinished native Hub entries gated by `Pre_AlwaysFail` are outside the
available roster and are not enabled by this mod.

## Prepare and install

Requires the official database/locale and the installed Cyber Knights Mod
Uploader, including its parser DLL and schema. From `cmd.exe`:

```bat
cd /d "D:\ckf-data-modding"
python "D:\ckf-data-modding\scripts\build_hire_everyone.py" --selftest
python "D:\ckf-data-modding\scripts\build_hire_everyone.py"
python "D:\ckf-data-modding\scripts\build_hire_everyone.py" --install
```

Preparation creates local generated artifacts under `ckf-hire-everyone/`:
`source_data/stories.manifest`, `source_data/hire-everyone.json`,
`prepared/_data/data.sql`, `prepared/_data/en-US.json`, and `review.json`.
The maintained authoring source is the builder, not these generated files.

`--install` also writes those parser sources into the existing Modkit project,
and the verified SQL/locale into its `upload_content/_data` and the specified
Workshop item's `_data`. It does not register a manually created directory with
Steam, alter Workshop metadata, or edit mod activation settings. Destination
mtime/hash guards and readback verification use `gui/modkit.py:commit_files`.

## Validation and first game test

The installed Data Parser produces the delivered SQL and locale. The verifier
applies that SQL to an in-memory copy of Official content, rejects updates and
deletes, compares every native row unchanged, checks the exact additions and
localization, validates content links, and checks repeat application. Independent
policy checks verify class slots, cloned character fields, original Hub entries,
new starter coverage and existing-character guards. Selftests also require
native writes, a wrong slot and a removed duplicate guard to fail.

`review.json` records the current roster, input/output hashes and check results.
These are content checks. Starting setup, contact casting, recruitment, expiry
and duplicate suppression in the running game remain [unverified].

Review the generated setup before testing: its AddCharacter, Tag, StoryMatch,
Recruit and Purge actions write campaign state. For a live test, activate the
locally installed mod, inspect all three starting pools, start with a Hub
character, and check that the same character is absent from Hub offers. Recruit
an unselected original starter and check name, traits, contacts, hire/decline,
cooldown and reload behavior. Include a Hacker/Wireghost in an origin that uses
the starting-hacker identity, and a Hub character whose setup casts contacts.
