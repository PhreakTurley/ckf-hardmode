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
new templates use BackstoryGroup 1. The shipped class sets the default starting
group. The Editor can assign any of the three groups to an included Hub recruit.

| Starting group | NewGame slot | Opening mission setup |
|---|---|---|
| Vanguard / Agent EX | 3 | Uses the shipped stealth group's deployment rows |
| Hacker / Wireghost | 4 | Uses `PersonID_StartingHacker` for story casting |
| Other combat classes | 5 | Uses the shipped combat group's deployment rows |

The official origin groups `Post_Amnesia_TutorialSkipOrEnd` and
`Post_SynDebts_TutorialSkipOrEnd` give shipped slot 3 and 5 actors a
`CharAltStart` and a `CharacterStatus` row. The exporter adds the matching
pair for each included Hub recruit, using the chosen group in both origins.
The shipped slot 4 actors have no deployment pair. [measured]
`Official/data.db`, `BlockCondition` 717–734 and 849–866.

The clones preserve native class, cosmetics, implants, base trait fields,
identity and tags. Their new initialization blocks copy the native recruitment
setup without creating the main character again, translate its temporary actor
reference to the permanent identity, and invoke the existing casting group when
one is referenced. They set the native recruitment's hired flag. Menu descriptions
use the native backstory text when available, otherwise the associated backstory
trait's localized text.
The builder does not translate choices in recruitment conversations into
additional starting variants.

Selected combat starters receive new Hub entries in their respective class
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

In the Editor, open **Hire Everyone Mod**. Use **Include in Underworld Hub**
for shipped combat starters. For Hub recruits, use **Include at New Game** and
choose a **Starting group**. Save persists the roster in
`BepInEx/config/ckf.hire-everyone.json`. The default roster includes every
supported character with class-based groups. Use **Export Hire Everyone to
Modkit** to build and install the saved roster locally. Export uses the
[Workshop project and Steam registration checks](../gui/README.md#export-workshop-mods-to-modkit-uploader).

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
policy checks verify selected groups, cloned character fields, origin deployment,
hired flags, selected starter offers and existing-character guards.

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
