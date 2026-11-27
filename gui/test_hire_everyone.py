"""Exercise the Hire Everyone roster through normal Editor save/export paths."""
from pathlib import Path
from contextlib import closing
import json
import sqlite3
import shutil
import sys
import tempfile
import unittest

import serve
import build_hire_everyone as hire
from test_party_size import registered_project


class HireEveryoneTests(unittest.TestCase):
    def test_new_hub_entry_is_visible_and_marked_for_review(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / 'data.db'
            shutil.copy2(hire.DEFAULT_DB.parent / 'en-US.json', root / 'en-US.json')
            with hire.StaticData() as original, closing(sqlite3.connect(database)) as fixture:
                native_rows = hire.official_rows(original, ('Backstory', 'Block', 'BlockCondition'))
                native_offers, _ = hire.hire_backstories.hub_entries(native_rows)
                outside_scope = set(native_offers) - set(hire.HUB) | {4888}
                original.connection.backup(fixture)
                # Teach the fixture about one additional regular Hub offer.
                fixture.executescript("""
                    CREATE TEMP TABLE next_merc AS SELECT * FROM Backstory WHERE BackstoryId=4000;
                    UPDATE next_merc SET BackstoryId=4888, BackstoryGroup=4888;
                    INSERT INTO Backstory SELECT * FROM next_merc;
                    CREATE TEMP TABLE next_offer AS SELECT * FROM Block WHERE BlockId=91006;
                    UPDATE next_offer SET Id=384899901, BlockId=384899901, PostConditionGroup='Post_NewHub',
                        PreConditionGroup='Pre_NewHubNeedsReview';
                    INSERT INTO Block SELECT * FROM next_offer;
                    CREATE TEMP TABLE next_setup AS SELECT * FROM BlockCondition WHERE BlockConditionId=81;
                    UPDATE next_setup SET BlockConditionId=384899901, GroupId='Post_NewHub', ConditionValue2=4888;
                    INSERT INTO BlockCondition SELECT * FROM next_setup;
                """)
            result = hire.model(root, database, '')
            self.assertIsNone(result['error'], result)
            self.assertEqual({r['id'] for r in result['hub'] if r.get('backstoryIssue')}, outside_scope)
            self.assertFalse(next(r for r in result['hub'] if r['id'] == 4888)['editable'])
            self.assertNotIn('4888', result['document']['hub'])
            _, _, report = hire.build(database, result['document'])
            self.assertEqual(report['outsideStartingScope'], sorted(outside_scope))

    def test_original_saved_choices_load_with_racer_in_slot_three(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = {'format': 1, 'starters': {str(bid): False for bid in hire.STARTERS},
                        'hub': {str(bid): {'include': False, 'slot': 4} for bid in hire.ORIGINAL_HUB}}
            path = root / hire.FILE
            path.write_bytes(hire.encode(original))
            result = hire.model(root, hire.DEFAULT_DB, '')
            self.assertIsNone(result['error'], result)
            self.assertEqual(result['document']['hub'].pop('305800'), {'include': True, 'slot': 3})
            self.assertEqual(result['document'], original)
            self.assertEqual(json.loads(path.read_bytes()), original)

    def test_save_and_export_selected_groups(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / 'config'
            config.mkdir()
            (config / 'ckf.hardmode.cfg').write_text('[General]\nEnabled = false\n', encoding='utf-8')
            project = root / 'WorkshopContent/HireEveryone'
            (project / 'upload_content').mkdir(parents=True)
            workshop = registered_project(root, project, '1001')
            contract = 'CyberKnightsModkit_Data/StreamingAssets/config.json'
            (project.parent / 'config.json').write_bytes((hire.MODKIT / contract).read_bytes())
            app = serve.App({'configDirOverride': str(config), 'hireEveryoneProjectDir': str(project)},
                            'test', static_source=hire.DEFAULT_DB)
            loaded = app.api_model(editor=True)
            document = loaded['hireEveryone']['document']
            self.assertEqual(document['hub']['4000'], {'include': True, 'slot': 4})
            self.assertEqual(document['hub']['305800'], {'include': True, 'slot': 3})
            self.assertNotIn('305900', document['hub'])
            document['starters']['14'] = False
            document['hub']['4000']['slot'] = 5
            document['hub']['4003']['slot'] = 4
            document['hub']['4004']['include'] = False
            edits = {'hireEveryone': document}
            receipt = app.api_save(edits, expect=loaded['fingerprints'])
            self.assertTrue(receipt['ok'], receipt)
            self.assertEqual(hire.load(config), document)
            self.assertFalse(app.api_hire_export(loaded['fingerprints'])['ok'])
            receipt = app.api_hire_export(app.current_fingerprints(str(config)))
            self.assertTrue(receipt['ok'], receipt)
            prepared = workshop / '_data/data.sql'
            self.assertEqual(prepared.read_bytes(), (project / 'upload_content/_data/data.sql').read_bytes())
            with hire.StaticData(hire.DEFAULT_DB) as official, closing(sqlite3.connect(':memory:')) as selected:
                official.connection.backup(selected)
                selected.executescript(prepared.read_text(encoding='utf-8-sig'))
                deployed = selected.execute("""SELECT GroupId, ConditionValue FROM BlockCondition
                    WHERE ActorId = 'PCP_UHUB_Hacker' AND ConditionType = 'CharAltStart' ORDER BY GroupId""").fetchall()
                self.assertEqual(deployed, [('Post_Amnesia_TutorialSkipOrEnd', 99), ('Post_SynDebts_TutorialSkipOrEnd', 2)])
                pools = selected.execute('SELECT BackstoryId, NewGame FROM Backstory WHERE BackstoryId IN (?,?,?) ORDER BY BackstoryId',
                                         (hire.BASE, hire.BASE + 1, hire.BASE + 2)).fetchall()
                self.assertEqual(pools, [(hire.BASE, 5), (hire.BASE + 1, 4)])
                nodes = selected.execute("""SELECT StoryNodeId FROM StoryNode
                    WHERE StoryNodeId LIKE 'SN_Finish_%_HireEveryone' AND StoryNodeType='Root'""").fetchall()
                self.assertEqual({row[0] for row in nodes}, {hire.hire_backstories.node_id(bid)
                                 for bid in hire.HUB if bid != 4004})
                self.assertEqual(selected.execute("""SELECT GroupId, ConditionValue FROM BlockCondition
                    WHERE ActorId='PCP_DronePilot_Racer' AND ConditionType='CharAltStart'
                    ORDER BY GroupId""").fetchall(),
                    [('Post_Amnesia_TutorialSkipOrEnd', 98), ('Post_SynDebts_TutorialSkipOrEnd', 3)])
                self.assertEqual(selected.execute("""SELECT c.ActorId, c.ConditionKey
                    FROM Backstory s JOIN Block b ON b.GroupId=s.BlockGroup
                    JOIN BlockCondition c ON c.GroupId=b.PostConditionGroup
                    WHERE s.CharStoryId='PCP_DronePilot_Racer' AND s.NewGame=3
                    AND c.ConditionType='Tag'""").fetchall(),
                    [('PCP_DronePilot_Racer', 'ADD_JobMem_Stealth')])
                deserter = """SELECT BackstoryId, NewGame FROM Backstory
                    WHERE CharStoryId='PCP_DronePilot_Deserter'"""
                self.assertEqual(selected.execute(deserter).fetchall(), official.connection.execute(deserter).fetchall())
                racer_replies = selected.execute("""SELECT b.PreDialogPostCondition, p.ActorId, p.OptionId
                    FROM Block b JOIN BlockCondition p ON p.GroupId=b.PreConditionGroup
                    JOIN BlockCondition c ON c.GroupId=b.PreDialogPostCondition
                    WHERE b.GroupId='B_Finish_305800_Choices_HireEveryone' AND p.ConditionType='Tag'
                        AND c.ConditionType='ContactMeta' AND c.ActorId=p.ActorId AND c.OptionId=2
                    ORDER BY p.OptionId""").fetchall()
                identity = 'NTG_PersonID_Recruit_DronePilot_Racer_Fabber'
                self.assertEqual([(actor, option) for _, actor, option in racer_replies], [(identity, -1), (identity, 1)])
                for group, _, presence in racer_replies:
                    operations = selected.execute("""SELECT ConditionType, ConditionValue FROM BlockCondition
                        WHERE GroupId=? AND ConditionType IN ('AddCharacter', 'ContactMeta') ORDER BY JsonId""",
                        (group,)).fetchall()
                    self.assertEqual(operations, ([('AddCharacter', 305801)] if presence == -1 else [])
                                     + [('ContactMeta', 0)])
                self.assertEqual(selected.execute("SELECT BlockId FROM Block WHERE StoryNode1='ADD_SN_Hacker_LeftForDead'").fetchall(), [(91006,)])
                agent_node = 'SN_Finish_4012_HireEveryone'
                retry_node = 'SN_Finish_4012_Retry_HireEveryone'
                launch = 'B_Finish_4012_Launch_HireEveryone'
                self.assertEqual(selected.execute("""SELECT StoryNodeType, ExpirationTurns, ExpirationBlock,
                    ExpirationStoryNode, PauseMode FROM StoryNode WHERE StoryNodeId=?""", (agent_node,)).fetchone(),
                    ('Root', 4, launch, retry_node, 0))
                self.assertEqual(selected.execute("""SELECT StoryNodeId, ChoiceMeta, EventType, EventId FROM Block
                    WHERE StoryNodeId IN (?,?) ORDER BY ChoiceMeta DESC""", (agent_node, retry_node)).fetchall(),
                    [(agent_node, 5, 'Group', launch), (retry_node, 4, 'Group', launch)])
                reply = selected.execute("""SELECT BlockId, EventType, EventId, Dialog, StoryNode1, StoryNode2, PostConditionGroup
                    FROM Block WHERE GroupId = ? AND PreDialogPostCondition IN
                    (SELECT GroupId FROM BlockCondition WHERE ConditionKey = ?)""",
                    ('B_Finish_4012_Choices_HireEveryone', 'ADD_Finish_4012_Choice_91258_HireEveryone')).fetchall()
                self.assertEqual(len(reply), 1)
                block, kind, target, dialog, removal, retry_removal, effects = reply[0]
                self.assertEqual((kind, target, removal, retry_removal),
                                 ('Event', '', 'DEL_' + agent_node, 'DEL_' + retry_node))
                self.assertTrue(dialog)
                self.assertTrue(567000 <= block <= 567999)
                self.assertEqual(selected.execute('SELECT ConditionValue FROM BlockCondition WHERE GroupId=? AND ConditionType=?',
                                                  (effects, 'Item')).fetchone(), (3606,))
                locale = json.loads((workshop / '_data/en-US.json').read_bytes())
                self.assertTrue(locale[f'BlockDesc.{block}_Female'])
                fabber = 'NCP_Finish_4003_Contact_2009_HireEveryone'
                fabber_setup = selected.execute("""SELECT b.GroupId, b.BlockId, b.PreConditionGroup, c.ActorId
                    FROM Block b JOIN BlockCondition c ON c.GroupId=b.PostConditionGroup
                    WHERE c.ConditionType='AddCharacter' AND c.ConditionValue=2009
                    AND b.GroupId IN ('B_Finish_4003_Setup_HireEveryone','B_Finish_4003_Launch_HireEveryone')
                    ORDER BY b.BlockId""").fetchall()
                self.assertEqual([row[0] for row in fabber_setup],
                                 ['B_Finish_4003_Setup_HireEveryone', 'B_Finish_4003_Launch_HireEveryone'])
                for _, _, guard, actor in fabber_setup:
                    self.assertEqual(actor, fabber)
                    self.assertIn((fabber, 'Tag_Gambler', -1), selected.execute("""
                        SELECT ActorId, ConditionKey, OptionId FROM BlockCondition
                        WHERE GroupId=? AND ConditionType='Tag'""", (guard,)).fetchall())
                self.assertEqual(selected.execute("""SELECT EventId FROM Block
                    WHERE GroupId='B_Finish_4003_Launch_HireEveryone' ORDER BY BlockId DESC LIMIT 1""").fetchone(),
                    ('B_Finish_4003_Prompts_HireEveryone',))
                self.assertEqual(selected.execute("""SELECT b.InterpolateActorId,c.ActorId,c.ConditionValue
                    FROM Block b JOIN BlockCondition c ON c.GroupId=b.PostConditionGroup
                    WHERE b.GroupId='B_Finish_4003_Choices_HireEveryone' AND c.ConditionType='CharacterStatus'""").fetchall(),
                    [(fabber, fabber, 1)])
                for bid, tag in ((4012, 'PersonID_Recruit_Agent_Escaped_Son'), (4016, 'PersonID_NCP_Judge')):
                    guards = selected.execute("""SELECT b.GroupId, p.ConditionType, p.OptionId, p.ConditionKey
                        FROM Block b JOIN BlockCondition p ON p.GroupId=b.PreConditionGroup
                        JOIN BlockCondition c ON c.GroupId=b.PostConditionGroup AND c.ConditionType='AddCharacter'
                        WHERE p.ActorId=? AND b.GroupId IN (?,?) ORDER BY b.BlockId""",
                        ('NTG_' + tag, f'B_Finish_{bid}_Setup_HireEveryone', f'B_Finish_{bid}_Launch_HireEveryone')).fetchall()
                    self.assertEqual(guards, [(f'B_Finish_{bid}_{stage}_HireEveryone', 'Tag', -1, tag)
                                              for stage in ('Setup', 'Launch')])
                self.assertEqual(selected.execute("""SELECT p.ConditionType,p.ActorId,p.ConditionKey,p.OptionId
                    FROM Block b JOIN BlockCondition p ON p.GroupId=b.PreConditionGroup
                    JOIN BlockCondition c ON c.GroupId=b.PostConditionGroup AND c.ConditionType='AddCharacter'
                    WHERE b.GroupId='B_Hub_19_Setup_HireEveryone' AND c.ConditionValue=5010""").fetchone(),
                    ('Tag', 'NTG_PersonID_NPC_Wendigo', 'PersonID_NPC_Wendigo', -1))
                self.assertEqual(selected.execute("""SELECT p.ConditionType,p.ActorId,p.ConditionKey,p.OptionId
                    FROM Block b JOIN BlockCondition p ON p.GroupId=b.PreConditionGroup
                    JOIN BlockCondition c ON c.GroupId=b.PostConditionGroup AND c.ConditionType='AddCharacter'
                    WHERE b.GroupId='B_Hub_35_LinkedSetup_HireEveryone' AND c.ConditionValue=5022""").fetchone(),
                    ('Tag', 'NTG_PersonID_NPC_Brandt', 'PersonID_NPC_Brandt', -1))
                self.assertEqual(selected.execute("""SELECT EventId FROM Block WHERE GroupId='B_Hub_35_Setup_HireEveryone'
                    AND EventType='Group'""").fetchone(), ('B_Hub_35_LinkedSetup_HireEveryone',))
                minimum = set(selected.execute("""
                    SELECT ContactBackstoryId,ContactStoryId FROM ContactBackstory WHERE NewGame=1 AND Status=1
                """))
                self.assertEqual(minimum, {(8, 'NCP_Origami'), (9, 'NCP_Ashe')})
                knight_choices = selected.execute('SELECT ContactLink1, ContactLink2 FROM Backstory WHERE NewGame=1').fetchall()
                face_choices = selected.execute('SELECT ContactLink1, ContactLink2 FROM Backstory WHERE NewGame=2').fetchall()
                self.assertEqual((len(knight_choices), len(face_choices)), (4, 3))
                for bid, fallback_id in {4005: 8, 4006: 9, 4008: 9, 4009: 8, 4012: 9, 305100: 9}.items():
                    actor, = [actor for cid, actor in minimum if cid == fallback_id]
                    fallback = selected.execute("""SELECT b.PreConditionGroup,c.ActorId,c.ConditionKey FROM Block b
                        JOIN BlockCondition c ON c.GroupId=b.PostConditionGroup
                        WHERE b.GroupId LIKE ? AND c.ConditionType='Tag'""",
                        (f'B_Finish_{bid}_Fallback_%_HireEveryone',)).fetchall()
                    self.assertEqual(len(fallback), 1)
                    guard, target, tag = fallback[0]
                    self.assertEqual(target, actor)
                    self.assertEqual(selected.execute("""SELECT ActorId,ConditionKey,OptionId FROM BlockCondition
                        WHERE GroupId=? AND ConditionType='Tag'""", (guard,)).fetchone(),
                        ('NTG_' + tag.removeprefix('ADD_'), tag.removeprefix('ADD_'), -1))
                    self.assertTrue(selected.execute("""SELECT 1 FROM Block
                        WHERE GroupId=? AND EventType='Group' AND EventId LIKE ?""",
                        (f'B_Finish_{bid}_Launch_HireEveryone', f'B_Finish_{bid}_Resolve_%_HireEveryone')).fetchone())
                for original, contact, name in ((91276, 2011, 'Raven'), (91277, 2012, 'Kelsen'), (91278, 2013, 'Ryka')):
                    variants = selected.execute("""SELECT BlockId, Dialog, PreDialogPostCondition, PostConditionGroup
                        FROM Block WHERE GroupId='B_Finish_4013_Choices_HireEveryone'
                        AND PreDialogPostCondition IN (SELECT GroupId FROM BlockCondition WHERE ConditionKey=?)""",
                        (f'ADD_Finish_4013_Choice_{original}_HireEveryone',)).fetchall()
                    self.assertEqual(len(variants), 2)
                    for option, speech, before, after in variants:
                        self.assertTrue(any(name in value for key, value in locale.items()
                                            if key.startswith(f'Dialog.{speech}.')))
                        self.assertFalse(any(name in value for key, value in locale.items()
                                             if key == f'BlockDesc.{option}' or key.startswith(f'BlockDesc.{option}_')))
                        self.assertIsNone(selected.execute("""SELECT 1 FROM BlockCondition WHERE GroupId=?
                            AND ConditionType='AddCharacter'""", (after,)).fetchone())
                    self.assertEqual(selected.execute("""SELECT backstory.ContactBackstoryId
                        FROM BlockCondition c JOIN ContactBackstory backstory ON
                        (c.ConditionValue = -1 AND backstory.BackstoryGroup = c.ConditionValue2)
                        OR backstory.ContactBackstoryId = c.ConditionValue
                        WHERE c.GroupId IN (?,?) AND c.ConditionType='AddCharacter'""",
                        (variants[0][2], variants[1][2])).fetchall(), [(contact,)])
                all_dialogue = [line for key, line in locale.items() if key.startswith(('Dialog.', 'BlockDesc.'))]
                self.assertTrue(any("when you're hacking" in line for line in all_dialogue))
                self.assertTrue(any('spinal cord' in line for line in all_dialogue))
                self.assertFalse(any('�' in line or '<style=DIalog' in line for line in all_dialogue))
                for bid in hire.HUB:
                    if bid == 4004:
                        continue
                    intro = selected.execute("""SELECT BlockId,ActorId,Dialog FROM Block
                        WHERE GroupId=? AND EventType='Choice' AND EventId=?""",
                        (f'B_Finish_{bid}_Prompts_HireEveryone', f'B_Finish_{bid}_Traits_HireEveryone')).fetchone()
                    self.assertEqual(intro[1], '')
                    self.assertNotIn(f'BlockDesc.{intro[0]}', locale)
                    self.assertTrue(locale[f'Dialog.{intro[2]}.567000'].startswith('Before we go any further'))
                    followup, = selected.execute('SELECT Dialog FROM Block WHERE GroupId=?',
                                                 (f'B_Finish_{bid}_Followup_HireEveryone',)).fetchone()
                    lines = [line for key, line in locale.items() if key.startswith(f'Dialog.{followup}.')]
                    quips = {row[0] for row in selected.execute('SELECT QuipType FROM Dialog WHERE GroupId=?', (followup,))}
                    self.assertTrue(lines)
                    self.assertTrue(quips.isdisjoint({'Recruit_Global_FaceThink', 'Recruit_Global_DefineTrust'}))
                    self.assertTrue(any(line.startswith("Further define this merc's Backstory") for line in lines)
                                    or 'Recruit_Global_Define2' in quips)
                    self.assertFalse(any(line.startswith('What do you think, {1}?') or 'trust is our baseline' in line
                                         for line in lines))
                    if bid == 305800:
                        self.assertTrue(any("there's more to the story" in line for line in lines))
                        self.assertFalse(any('crooked bookies' in line for line in lines))
                    if bid == 4012:
                        self.assertTrue(locale[f'Dialog.{followup}.567001_Female'].startswith("I've got one more question"))
                        self.assertTrue(locale[f'Dialog.{followup}.567002'].startswith("Further define this merc's Backstory"))


UI = r'''
setTimeout(async function () {
  function ck(name, ok) {if (!ok) throw new Error(name);console.log('PASS '+name);}
  SEL='hire-everyone'; render();
  const panel=$('#panel');
  const control=(field,id)=>panel.find(n=>n.getAttribute('data-hire-'+field)===String(id))[0];
  ck('both shipped rosters render', panel.textContent.includes('Shipped Starters')
    && panel.textContent.includes('Shipped Underworld Hub')
    && panel.find(n=>n.getAttribute('data-hire-include')).length===MODEL.hireEveryone.starters.length+MODEL.hireEveryone.hub.length);
  ck('the shipped Hacker defaults to the Hacker/Wireghost group', control('group',4000).value==='4');
  ck('Racer defaults to the Vanguard / Agent EX group', control('group',305800).value==='3'
    && control('include',305800).checked && control('story',305800).textContent==='Finish Backstory');
  ck('unreviewed Hub candidates are outside scope', control('story',4888).textContent==='Outside mod scope'
    && MODEL.hireEveryone.hub.filter(r=>!r.editable).every(r =>
      control('story',r.id).textContent==='Outside mod scope' && control('include',r.id).disabled));
  const group=control('group',4000);
  group.value='5'; group.fire('change');
  const hub=control('include',4003);
  hub.checked=false;hub.fire('change');
  const starter=control('include',14);
  starter.checked=false;starter.fire('change');
  ck('group selector and both checkboxes enter the save payload', buildEdits().hireEveryone.hub['4000'].slot===5
    && !buildEdits().hireEveryone.hub['4003'].include && !buildEdits().hireEveryone.starters['14']);
  ck('deployment labels follow the draft', control('group',4003).disabled
    && panel.textContent.includes('Deploys in both Origin openers') && panel.textContent.includes('Outside starting roster'));
  ck('export requires saving pending edits', panel.querySelector('#send-hire').disabled);
  acceptModel(MODEL);
  const calls=[];
  api=async function (path, body) {calls.push([path,body]);return {ok:true,next:'Exported.'};};
  await panel.querySelector('#send-hire').listeners.click[0]();
  ck('standalone export sends saved fingerprints', calls.length===2 && calls[1][0]==='/api/hire-export'
    && CKF.deepEqual(calls[1][1].fingerprints, MODEL.fingerprints));
  process.exit(0);
},0);
'''


if __name__ == '__main__':
    if '--ui' in sys.argv:
        settings = serve.load_settings()
        settings['hireEveryoneProjectDir'] = str(hire.UPLOADER)
        app = serve.App(settings, 'test', static_source=hire.DEFAULT_DB)
        model = app.api_model(editor=True)
        model['hireEveryone']['hub'].append({'id': 4888, 'name': 'New Hub Merc', 'backstory': 'New Hub Merc',
            'job': 'Hacker', 'defaultSlot': 4, 'editable': False, 'backstoryIssue': 'No reviewed New Game event'})
        sys.exit(serve.selftest_dom(model, UI))
    unittest.main()
