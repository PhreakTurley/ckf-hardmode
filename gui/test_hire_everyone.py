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
                original.connection.backup(fixture)
                # Teach the fixture about one additional regular Hub offer.
                fixture.executescript("""
                    CREATE TEMP TABLE next_merc AS SELECT * FROM Backstory WHERE BackstoryId=4000;
                    UPDATE next_merc SET BackstoryId=4888, BackstoryGroup=4888;
                    INSERT INTO Backstory SELECT * FROM next_merc;
                    CREATE TEMP TABLE next_offer AS SELECT * FROM Block WHERE BlockId=91006;
                    UPDATE next_offer SET Id=384899901, BlockId=384899901, PostConditionGroup='Post_NewHub';
                    INSERT INTO Block SELECT * FROM next_offer;
                    CREATE TEMP TABLE next_setup AS SELECT * FROM BlockCondition WHERE BlockConditionId=81;
                    UPDATE next_setup SET BlockConditionId=384899901, GroupId='Post_NewHub', ConditionValue2=4888;
                    INSERT INTO BlockCondition SELECT * FROM next_setup;
                """)
            result = hire.model(root, database, '')
            self.assertIsNone(result['error'], result)
            self.assertEqual({r['id'] for r in result['hub'] if r.get('backstoryIssue')}, {4888})
            self.assertFalse(next(r for r in result['hub'] if r['id'] == 4888)['editable'])
            self.assertNotIn('4888', result['document']['hub'])

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
                    self.assertIn((fabber, -1), selected.execute("""SELECT ActorId, OptionId FROM BlockCondition
                        WHERE GroupId=? AND ConditionType='HasCharacter'""", (guard,)).fetchall())
                self.assertEqual(selected.execute("""SELECT EventId FROM Block
                    WHERE GroupId='B_Finish_4003_Launch_HireEveryone' ORDER BY BlockId DESC LIMIT 1""").fetchone(),
                    ('B_Finish_4003_Prompts_HireEveryone',))
                self.assertEqual(selected.execute("""SELECT b.InterpolateActorId,c.ActorId,c.ConditionValue
                    FROM Block b JOIN BlockCondition c ON c.GroupId=b.PostConditionGroup
                    WHERE b.GroupId='B_Finish_4003_Choices_HireEveryone' AND c.ConditionType='CharacterStatus'""").fetchall(),
                    [(fabber, fabber, 1)])
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
                    self.assertEqual(selected.execute("""SELECT ActorId,OptionId FROM BlockCondition
                        WHERE GroupId=? AND ConditionType='HasCharacter'""", (guard,)).fetchone(),
                        ('NTG_' + tag.removeprefix('ADD_'), -1))
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
  ck('reviewed and missing New Game events are labeled separately', control('story',4000).textContent==='Finish Backstory'
    && control('story',4888).textContent==='Missing event' && control('include',4888).disabled);
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
