"""Structural tree checks and prerequisite repair for Workshop node removal.

Reachability is a graph check from the class's declared default nodes. It does
not claim how the game evaluates multiple prerequisite slots during purchase.
"""
import csv
import io

import player_balance as pb
import talent_catalog as tc

REQUIREMENTS = ('NodeReq1', 'NodeReq2', 'NodeReq3')
DEFAULTS = tuple('DefaultNode%d' % i for i in range(1, 5))


def effective_nodes(doc, source, config_dir=None, overlay_bytes=None):
    nodes = {r['JobNodeId']: dict(r) for r in source.read('JobNodeModel')[1]}
    if config_dir:
        from pathlib import Path
        for tag in tc.JOBS:
            rel = 'ckf.hardmode.d/JobNodeModel.%s.csv' % tag
            raw = (overlay_bytes or {}).get(rel)
            path = Path(config_dir) / rel
            if raw is None and path.exists():
                raw = path.read_bytes()
            if raw is None:
                continue
            for row in csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))):
                if row['JobNodeId'] in nodes:
                    nodes[row['JobNodeId']].update({k: v for k, v in row.items()
                                                  if k in nodes[row['JobNodeId']] and v and not k.startswith('_')})
    for rid, fields in doc['tables'].get('JobNode', {}).items():
        for col, value in fields.items():
            if col in pb.TEXT_FIELDS['JobNode']:
                nodes[rid][col] = value or nodes[rid][col]
            else:
                parsed = pb.adjustment(value)
                if parsed:
                    op, number = parsed
                    base = float(nodes[rid][col])
                    nodes[rid][col] = str(round(number if op == 'set' else base + number if op == 'add' else base * number))
    return nodes


def plan(doc, source, config_dir=None, overlay_bytes=None):
    nodes = effective_nodes(doc, source, config_dir, overlay_bytes)
    jobs = {r['JobId']: r for r in source.read('JobModel')[1] if r['JobId'] in set(map(str, tc.JOBS.values()))}
    requested = doc.get('removedJobNodes', [])
    if not isinstance(requested, list) or any(not isinstance(n, str) or n not in nodes for n in requested):
        raise ValueError('Removed job nodes must be existing node ids.')
    if len(set(requested)) != len(requested):
        raise ValueError('Removed job nodes contain duplicate ids.')
    removed = set(requested)
    for rid in removed:
        if nodes[rid]['JobId'] not in jobs:
            raise ValueError('JobNode %s is outside the editable classes.' % rid)
        if int(nodes[rid]['SubTree']) <= 0 or jobs[nodes[rid]['JobId']]['DefaultNode1'] == rid:
            raise ValueError('Only upgrade nodes can be removed: JobNode %s.' % rid)
    repairs = {}

    def predecessors(rid, visiting):
        if rid not in removed:
            return [rid] if int(rid) > 0 else []
        if rid in visiting:
            raise ValueError('Removed prerequisite cycle at JobNode %s.' % rid)
        out = []
        for col in REQUIREMENTS:
            out += predecessors(nodes[rid][col], visiting | {rid})
        return list(dict.fromkeys(out))

    for rid, row in nodes.items():
        if rid in removed:
            continue
        old = [row[c] for c in REQUIREMENTS]
        if any(n in removed for n in old):
            new = list(dict.fromkeys(p for n in old for p in predecessors(n, set())))
            if len(new) > len(REQUIREMENTS):
                raise ValueError('Removing these nodes gives JobNode %s more than three prerequisites.' % rid)
            new += ['0'] * (len(REQUIREMENTS) - len(new))
            repairs[rid] = {c: v for c, v, was in zip(REQUIREMENTS, new, old) if v != was}
            row.update(repairs[rid])
    default_repairs = {}
    for jid, job in jobs.items():
        changed = {c: '0' for c in DEFAULTS if job[c] in removed}
        if changed:
            default_repairs[jid] = changed
    problems = []
    # David's policy: only NEW structural faults block tuning. Recompute the
    # shipped graph from this exact database, without a hand-maintained allowlist.
    shipped = {r['JobNodeId']: r for r in source.read('JobNodeModel')[1]}
    exemptions = {}
    for jid, job in jobs.items():
        stock = {rid: r for rid, r in shipped.items() if r['JobId'] == jid}
        reached = {job[c] for c in DEFAULTS if job[c] in stock}
        while True:
            extra = {rid for rid, row in stock.items() if any(row[c] in reached for c in REQUIREMENTS)} - reached
            if not extra: break
            reached |= extra
        exemptions[jid] = stock.keys() - reached
    for jid, job in jobs.items():
        if job['Enabled'] == '0':
            continue
        active = {rid: r for rid, r in nodes.items() if r['JobId'] == jid and rid not in removed}
        reached = {job[c] for c in DEFAULTS if job[c] in active}
        bad_refs = [(rid, c, row[c]) for rid, row in active.items() for c in REQUIREMENTS
                    if int(row[c]) > 0 and row[c] not in active]
        for rid, c, target in bad_refs:
            if shipped[rid]['JobId'] != jid or shipped[rid][c] != target:
                problems.append('JobNode %s.%s points outside its enabled tree: %s' % (rid, c, target))
        while True:
            extra = {rid for rid, row in active.items() if any(row[c] in reached for c in REQUIREMENTS)} - reached
            if not extra:
                break
            reached |= extra
        missing = sorted(active.keys() - reached - exemptions[jid], key=int)
        if missing:
            problems.append('%s: unreachable JobNodes %s' % (job['JobName'], ', '.join(missing)))
    return {'removed': sorted(removed, key=int), 'repairs': repairs,
            'defaultRepairs': default_repairs, 'problems': problems, 'nodes': nodes}


def validate(doc, source, config_dir=None, overlay_bytes=None):
    result = plan(doc, source, config_dir, overlay_bytes)
    if result['problems']:
        raise ValueError('Talent tree validation failed: ' + '; '.join(result['problems']))
    return result


def sql(doc, source, config_dir=None):
    result = validate(doc, source, config_dir)
    statements = []
    for table, key, updates in (('JobNode', 'JobNodeId', result['repairs']),
                                ('Job', 'JobId', result['defaultRepairs'])):
        for rid, fields in updates.items():
            statements.append('UPDATE "%s" SET %s WHERE "%s"=%d;' %
                              (table, ', '.join('"%s"=%d' % (c, int(v)) for c, v in fields.items()), key, int(rid)))
    if result['removed']:
        statements.append('DELETE FROM "JobNode" WHERE "JobNodeId" IN (%s);' % ','.join(result['removed']))
    return statements
