# Hire Everyone Workshop mod

`scripts/build_hire_everyone.py` prepares additive character availability for
the `HireEveryone` Modkit project and the requested local Workshop folder
`3841540859`. The builder does not run the game, open a save, activate a mod,
or submit anything to Steam.

## Scope and authoring

The explicit `HUB` and `STARTERS` declarations own the authored characters.
The builder checks that the authored Hub recruits still exist and that the
shipped combat starter roster matches `STARTERS`. Additional Hub candidates
appear as **Outside mod scope** and can stay outside the starting roster.
Underway Racer is authored.
Content and localization come from the official database and locale through
the [static reader](static-data.md).

The export reserves numeric content IDs `567000–567999` and appends
`_HireEveryone` to new string IDs. It keeps shipped references, including the
shared Hub and Origin group names. SQLite assigns its internal row IDs.
Start a new campaign for this namespace. Earlier test campaigns stored the
previous template and story node identifiers.

Hub characters receive separate starting-only Backstory templates. Their
new templates use BackstoryGroup 1. The shipped class sets the default starting
group. The Editor can assign any of the three groups to an included Hub recruit.

| Starting group | NewGame slot | Opening mission setup |
|---|---|---|
| Vanguard / Agent EX | 3 | Uses the shipped stealth group's deployment rows. Underway Racer starts here by default and receives `JobMem_Stealth` for story casting. |
| Hacker / Wireghost | 4 | Uses `PersonID_StartingHacker` for story casting |
| Other combat classes | 5 | Uses the shipped combat group's deployment rows |

The official origin groups `Post_Amnesia_TutorialSkipOrEnd` and
`Post_SynDebts_TutorialSkipOrEnd` give shipped slot 3 and 5 actors a
`CharAltStart` and a `CharacterStatus` row. The exporter adds the matching
pair for each included Hub recruit, using the chosen group in both origins.
The shipped slot 4 actors have no deployment pair. [measured]
`Official/data.db`, `BlockCondition` 717–734 and 849–866.

The clones preserve native class, cosmetics, implants, base trait fields,
identity and tags. Their initialization sets the native hired flag, runs the
starter's supporting cast and relationship setup, and queues their **Finish
Backstory** node. The prompt is eligible for the timeline and roster page
when the Origin sets `Origin_Completed`. A roster check uses the starter's
permanent actor ID. The deadline is staggered from four to seven turns after
the node is queued. At expiry the node opens the current conversation and
hands off to a roster prompt so the player can resume a dismissed dialogue.
Both entry points share the same completion flags.

The timeline skips active story nodes whose stored `ExpiresTurn` is `-1`.
[measured] Shipped `GameAssembly.dll` on Unity 6000.3.12f1,
`SaveManager.PopulateTimelineEvents` at RVA `0xF54EC6` and
`GameDataManager.BuildStoryNode` at RVA `0xAC0D8F`–`0xAC0E74`.

`scripts/hire_backstories.py` adapts each reviewed Hub conversation into two
choices. The timeline and roster use the **Finish Backstory** label. The
conversation opens with the merc's greeting. The trait choice leads to the
follow-up, with the Face question and the trust warning removed. The follow-up
choice plays the reply, applies its
effects, and closes the prompt. An interrupted conversation resumes from
its saved choice. Starter setup creates fixed contacts by their shipped
backstory and reuses existing contacts by identity. Opening an unfinished
conversation also checks for missing setup contacts. The exporter checks the
actors and interpolation targets in each choice and reply. The three Fireteam
Shadow Wolf options describe the contact by role. The chosen survivor is
created before their name appears in the reply. The exported English dialogue
and choice labels include starter-only copyedits. The shipped Hub conversations
handle later recruitment. Menu descriptions use the native backstory text when
available, otherwise the associated trait text.

The minimum active contact pool is Origami and Dr. Ashe. [measured] The shipped
`NewGameDataManager.CreateContacts` passes 1 to
`DataDb.ReadContactBackstorysNewGame` in `GameAssembly.dll`. In
`Official/data.db`, `ContactBackstory` 8 and 9 have both `NewGame=1` and
`Status=1`. The four Knight templates have no `ContactLink1/2`. The three Face
templates link three different contact pairs. See `Backstory` 9–12, 13, 15,
and 16. The starter stories try the native casting rules first. If a contact
role remains empty, they use one of the two guaranteed contacts.

| Starter backstory | Guaranteed fallback |
|---|---|
| Counter-Intel Turned Warden, Cybersword weapon developer, retired sniper | Origami |
| Rebuilt Cybersword, betrayed soldier, escaped Agent EX, cult Warmachine | Dr. Ashe |

Contact creation and cast recovery test the contact's tag through the contact
lookup. `HasCharacter` calls the player roster lookup, so the exporter uses
it for merc checks and uses `Tag` for contact checks. [measured] Shipped
`GameAssembly.dll`, `GameDataManager.EvaluatePreconditionBlockCondition` at
RVAs `0xAC5001`–`0xAC503F` and `0xAC418F`–`0xAC423A`. A shared identity is
reused through new-game setup, dialogue recovery, or a later Hub offer.
Wendigo's Ward War and starter contact templates, `ContactBackstory` 1058 and
5010, share `PersonID_NPC_Wendigo`. [measured] `Official/data.db`.
Molly's Hub setup also guards Brandt, whom her shipped setup creates outside
the two linked contacts. [measured] `Official/data.db`, `Block` 86 and
`BlockCondition` 557.

The shipped Vanguard Hub offer casts the Fabber during offer setup and
activates the contact on the matching choice. Backstory 2009 refers to
`PersonID_Recruit_UHUB_Vanguard_Fabber`, which has no row in `Tag`.
[measured] `Official/data.db`, `BlockCondition` 181 and 193, `StoryMatch`
290, `ContactBackstory` 2009, and `Tag`. The starter version uses a permanent
actor ID for both the Fabber's name and the choice effect.

Underway Racer's Fabber choice uses the shipped contact backstory and applies
its `ContactMeta` action to the contact's identity before the reply. Contact
creation is guarded by the same identity. [measured] `Official/data.db`,
`Block` 305812, `BlockCondition` group `Post_Recruit_DronePilot_Racer_Tag1`
and `ContactBackstory` 305801.

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

The **New Game event** column shows each Hub character's coverage. **Missing
event** identifies an authored entry whose shipped content needs review.
To support a character outside the mod's scope, add their reviewed trait and
follow-up block IDs to `CONVERSATIONS`, review their contact and casting
actions, and update the authored Hub roster. Save and export run the same
coverage checks on the selected roster.

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
hired flags, selected starter offers, starter-only activation, guarded contact
creation, path completion and choice checkpoints.

`review.json` records the current roster, input/output hashes and check results.
These are content checks. Starting setup, contact casting, recruitment, expiry
and duplicate suppression in the running game remain [unverified].

Review the generated setup before a live test. In both Origins, start with a
Hub character and look for **Finish Backstory** on the top timeline and on
the character page. Try the timeline entry for one starter and let another
reach its deadline. Check the resulting traits and contacts, confirm that
finishing clears the prompt, and hire a different Hub merc through their
ordinary offer.
