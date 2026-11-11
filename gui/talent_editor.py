"""Joined talent editing views; native sheet targets remain native sheet edits."""
import player_balance as pb
import static_data
import talent_catalog as tc


POINTERS = {'JobNode': {'NodeEffect1Id': 'Effect', 'MatrixEffect1Id': 'MatrixEffect',
                       'NodeTalentTriggerEffect': 'Effect'},
            'Talent': {'SelfEffect': 'Effect', 'TargetEffect': 'Effect', 'MatrixEffect': 'MatrixEffect'}}
NODE_METADATA = {'JobVersion', 'JobId', 'DisplayCol', 'DisplayRow', 'NodeReq1', 'NodeReq2',
                 'NodeReq3', 'SubTree', 'SubQuad', 'ImplantClass', 'ImplantLevel', 'Locked',
                 'NodeTalent1Id', 'NodeTalentTriggerId', 'NodeTalentTriggerType',
                 'NodeTalentAdjustmentId', 'CarryItemClass', 'DescRule'}


def catalog(overlays, database, attribute_columns, attribute_always, talent_excluded, document=None, config_dir=None):
    result = {'pages': {}, 'error': None}
    if database is False:
        return result
    try:
        with static_data.StaticData(database) as source:
            tables = {t: {r[tc.KEYS[t + 'Model']]: r for r in source.read(t + 'Model')[1]}
                      for t in ('Job', 'JobNode', 'Talent', 'Effect', 'MatrixEffect')}
            icons = {col: sorted({r[col] for t, fields in pb.TEXT_FIELDS.items() if col in fields
                                  for r in tables[t].values() if r[col]})
                     for col in ('IconPng', 'IconAsset')}
            options = {t: [{'value': rid, 'label': rid + ' · ' + (r.get('TalentName') or r.get('EffectName') or t)}
                           for rid, r in sorted(rows.items(), key=lambda item: int(item[0]))]
                       for t, rows in tables.items() if t in ('Effect', 'MatrixEffect')}
            topology = dict(tables)
            if document is not None:
                import talent_tree
                removal = talent_tree.plan(document, source, config_dir)
                topology['JobNode'] = removal['nodes']
                topology['Talent'] = {rid: dict(r) for rid, r in tables['Talent'].items()}
                for rid, row in topology['Talent'].items():
                    for col in POINTERS['Talent']:
                        row[col] = str(int(pb.effective(document, 'Talent', row, col)))
            by_sheet = {(ov['table'].removesuffix('Model'), rel.split('.')[-2]): (rel, ov)
                        for rel, ov in overlays.items() if ov.get('catalogOrder', 100) < 100}
            for tag, job in tc.JOBS.items():
                nodes, parents, owners = tc.catalog({t + 'Model': r for t, r in topology.items()}, job)
                carry = {rid for rid, r in nodes.items() if int(r['CarryItemClass']) > 0}
                carry.update(r['SubTree'] for rid, r in nodes.items() if rid in carry and int(r['SubTree']) > 0)
                attributes = {rid for rid, r in nodes.items() if tc.is_attribute(r, {t + 'Model': v for t, v in tables.items()})} | carry
                root = tables['Job'][str(job)]['DefaultNode1']
                page = {'id': 'talents-' + tag, 'title': '', 'group': 'Talents', 'grids': [], 'talents': True}

                def grid(title, blocks, records):
                    g = {'key': title, 'table': blocks[0][0] if len(blocks)==1 else 'JobNode', 'title': title, 'joined': True,
                         'columns': [], 'advanced': [], 'rows': [], 'scrollWithPage': True,
                         'unpaginated': True, 'dynamicColumns': True, 'talents': True}
                    for table, heading in blocks:
                        sheet = by_sheet.get((table, tag))
                        names = [c['name'] for c in sheet[1]['columns'] if not c['control']][1:] if sheet else []
                        declared = pb.declarations(source, table)
                        names = list(dict.fromkeys(names + list(declared)))
                        first = (['BuyCost', 'IconPng', 'NodeEffect1Id', 'MatrixEffect1Id', 'NodeTalentTriggerEffect']
                                 if table == 'JobNode' else ['IconPng', 'SelfEffect', 'TargetEffect', 'MatrixEffect']
                                 if table == 'Talent' else ['IconAsset'])
                        names.sort(key=lambda n: first.index(n) if n in first else len(first))
                        for name in names:
                            if name not in declared:
                                continue
                            col = {'name': table + '.' + name, 'sourceColumn': name, 'sourceTable': table,
                                   'label': pb.label(name), 'group': heading, 'order': len(g['columns']),
                                   'metadata': name in (NODE_METADATA if table == 'JobNode' else pb.METADATA),
                                   'integer': 'INT' in declared[name].upper(), 'visibilityPolicy': 'nonzero'}
                            if table == 'Talent': col['baselinePlain'] = True
                            if table == 'JobNode' and name == 'BuyCost': col['plainBaseline'] = '1'
                            if table == 'JobNode' and name.startswith('Talent'): col['label'] = pb.label(name[6:])
                            if name in pb.TEXT_FIELDS.get(table, set()):
                                col.update(label='Icon', literal=True, always=True,
                                           options=[{'value': i, 'label': i} for i in icons[name]])
                            if name in POINTERS.get(table, {}):
                                target = POINTERS[table][name]
                                col['label'] = {'NodeEffect1Id':'Effect', 'MatrixEffect1Id':'Matrix effect',
                                                'NodeTalentTriggerEffect':'Trigger effect', 'SelfEffect':'Self effect',
                                                'TargetEffect':'Target effect', 'MatrixEffect':'Matrix effect'}[name]
                                col.update(always=True, options=[{'value': '0', 'label': '0 · None'}] + options[target])
                            if table == 'Effect' and title == 'Attributes':
                                col['defaultExcluded'] = name not in attribute_columns
                                if name in attribute_always:
                                    col['always'] = True
                            elif table == 'Effect':
                                col['defaultExcluded'] = name in talent_excluded
                            g['columns'].append(col)
                    for node_id, links, label in records:
                        row = {'id': node_id, 'name': label, 'baseline': {}, 'targets': {},
                               'nodeId': node_id if 'JobNode' in links and int(nodes[node_id]['SubTree']) > 0 else None,
                               'removalIds': [node_id]}
                        for col in g['columns']:
                            table, name = col['sourceTable'], col['sourceColumn']
                            rid = links.get(table)
                            if not rid:
                                continue
                            stock = tables[table][rid]
                            row['baseline'][col['name']] = stock[name]
                            target = {'table': table, 'id': rid, 'column': name}
                            users = owners.get(table + 'Model', {}).get(rid, [])
                            target['sharedWith'] = [nodes[n]['JobNodeName'] for n in users if n != node_id]
                            sheet = by_sheet.get((table, tag))
                            if sheet:
                                rel, ov = sheet
                                ci = next((i for i, c in enumerate(ov['columns']) if c['name'] == name), None)
                                ri = next((i for i, r in enumerate(ov['rows']) if r['cells'][0] == rid), None)
                                if ci is not None and ri is not None:
                                    target.update(overlay=rel, row=ri, ci=ci,
                                                  readOnly=not ov.get('writable') or not ov['editable'][ci])
                            if document is not None and table == 'JobNode' and name in removal['repairs'].get(rid, {}):
                                target.update(generated=removal['repairs'][rid][name], readOnly=True,
                                              readOnlyReason='Reconnected around a removed upgrade.')
                            if table == 'JobNode' and name == 'NodeTalentTriggerEffect':
                                tid = nodes[rid]['NodeTalentTriggerId']
                                if topology['Talent'].get(tid, {}).get('TalentIsMatrixOnly') == '1':
                                    col.setdefault('rowOptions', {})[node_id] = [{'value':'0', 'label':'0 · None'}] + options['MatrixEffect']
                            row['targets'][col['name']] = target
                        g['rows'].append(row)
                    return g

                regular, attribute_rows = [], []
                for rid in sorted(nodes, key=lambda n: tc.node_order(n, nodes)):
                    if rid == root:
                        continue
                    node = nodes[rid]
                    if rid in attributes:
                        links = {'JobNode': rid}
                        eid = tc.positive(node, 'NodeEffect1Id')
                        if eid:
                            links['Effect'] = eid
                        attribute_rows.append((rid, links, node['JobNodeName']))
                    else:
                        talents = parents[rid] or [None]
                        for tid in talents:
                            links = {'JobNode': rid}
                            if tid:
                                links['Talent'] = tid
                            regular.append((rid, links, node['JobNodeName'] +
                                            (' · ' + tables['Talent'][tid]['TalentName'] if len(talents) > 1 else '')))
                page['grids'].append(grid('Talents and upgrades', [('JobNode', 'Job node'), ('Talent', 'Talent')], regular))
                for table in ('Effect', 'MatrixEffect'):
                    records = []
                    for eid, users in owners[table + 'Model'].items():
                        if users and all(n in attributes for n in users):
                            continue
                        ordered = tc.effect_owners(table + 'Model', eid, users, nodes,
                                                  {t + 'Model': v for t, v in tables.items()})
                        records.append((eid, {table: eid}, ', '.join(dict.fromkeys(nodes[n]['JobNodeName'] for n in ordered))))
                    if records:
                        records.sort(key=lambda r: min(tc.node_order(n, nodes) for n in owners[table + 'Model'][r[0]]))
                        page['grids'].append(grid('Effects' if table == 'Effect' else 'Matrix effects', [(table, table)], records))
                attribute_rows.sort(key=lambda r: (r[0] in carry, (int(r[0]),) if r[0] in carry else tc.attribute_order(r[2])))
                page['grids'].append(grid('Attributes', [('Effect', 'Attribute effect'), ('JobNode', 'Job node')], attribute_rows))
                result['pages'][tag] = page
    except (ValueError, OSError, static_data.DataError) as exc:
        result['error'] = str(exc)
        result['pages'] = {}
    return result
