"""Presentation ownership; authoring targets, switches and exports stay unchanged."""

MOD_OWNERS = [
    {'id': 'player-balance', 'title': 'Player Balance', 'catalogFirst': True},
    {'id': 'enemy-balance', 'title': 'Enemy Balance'},
    {'id': 'hard-mode', 'title': 'Hard Mode'},
    {'id': 'party-size', 'title': 'Party Size Mod', 'standalone': 'partySize', 'selection': 'party-size'},
    {'id': 'contact-breaks', 'title': 'Faster Contact Limit Breaks', 'standalone': 'contactBreaks', 'selection': 'contact-breaks'},
    {'id': 'hire-everyone', 'title': 'Hire Everyone Mod', 'standalone': 'hireEveryone', 'selection': 'hire-everyone'},
]
ROW_OWNERS = {'Player Balance': 'player-balance', 'Enemy Balance': 'enemy-balance', 'Hard Mode': 'hard-mode'}
OWNER_TITLES = {owner['id']: owner['title'] for owner in MOD_OWNERS}


def section_owner(section):
    owners = {'player-balance' if sub.startswith('Talents') else
              'enemy-balance' if sub == 'EnemyArmor' else 'hard-mode'
              for sub in section['subsystems']}
    if len(owners) != 1:
        raise ValueError('Split the mixed-mod navigation section: ' + section['id'])
    return owners.pop()


def catalog_pages(pages):
    """Partition mixed reference pages without dropping rows, columns or headings."""
    result = []
    for page in pages:
        grids = {}
        for grid in page['grids']:
            rows = {}
            for row in grid['rows']:
                # A player weapon remains here even when an enemy shares its row
                # or an intrinsic field is read-only under another mod's control.
                owner = 'player-balance' if grid['table'] == 'Weapon' else ROW_OWNERS[row.get('owner', 'Player Balance')]
                rows.setdefault(owner, []).append(row)
            for owner, records in rows.items():
                grids.setdefault(owner, []).append(dict(grid, rows=records))
            if not grid['rows']:
                grids.setdefault('player-balance', []).append(grid)
        if not grids:
            grids['player-balance'] = []
        for owner in ('player-balance', 'enemy-balance', 'hard-mode'):
            if owner not in grids:
                continue
            pid = page['id'] if owner == 'player-balance' else owner + '-' + page['id']
            # The former Player Balance category is now the owning-mod heading.
            # Other mods' Rules pages sit directly below their own mod heading.
            group = None if page['group'] in ROW_OWNERS and ROW_OWNERS[page['group']] != owner else page['group']
            result.append(dict(page, id=pid, owner=owner, ownerTitle=OWNER_TITLES[owner],
                               ownershipReference=owner != 'player-balance', group=group, grids=grids[owner]))
    return result
