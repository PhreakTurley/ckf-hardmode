"""Explicit guarded transfer of legacy cyberware tuning to Workshop ownership."""
import argparse
import csv
import io
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import modkit
import player_balance as pb
import static_data


def transfer(config, database=None):
    root = Path(config).resolve()
    destination = root / pb.FILE
    if destination.exists():
        raise ValueError('Player tuning already exists; refusing to import legacy files again')
    legacy = root / 'ckf.hardmode.d'
    paths = [legacy / 'implants-global.json', legacy / 'RuleModel.csv']
    paths += sorted(legacy.glob('implants-slot*.csv'))
    paths += [legacy / 'cyberweapons-claws.csv', legacy / 'cyberweapons-lasers.csv']
    inputs = {p: modkit.state(p) for p in paths}
    preserved = {legacy / name: modkit.state(legacy / name)
                 for name in ['fatigue.json', 'EffectModel.limitbreak.csv']}
    document = pb.import_legacy(root)
    with static_data.StaticData(database) as source:
        pb.validate(document, source)
    outputs = {destination: pb.encode(document)}
    import implants
    import cyberweapons
    for path in paths:
        if path.name == 'implants-global.json':
            # The plugin accepts this neutral legacy document for old installs;
            # its loader no longer emits any implant multiplier rule.
            outputs[path] = pb.encode({'_version': '4.1.0', 'costMultiply': 1,
                                       'installTimeMultiply': 1, 'implantStressMultiply': 1})
            continue
        rows = pb.csv_rows(path)
        header = list(rows[0])
        for row in rows:
            if path.name == 'RuleModel.csv':
                if row['RuleId'] in ('22', '23'):
                    row['Value'] = ''
                    row['_comment'] = 'Surprised Bonus' if row['RuleId'] == '22' else 'Glancing Distance Limit'
                continue
            identities = implants.IMPLANT_IDENTITY if path.name.startswith('implants-') else cyberweapons.IDENTITY
            for col in header:
                if not col.startswith('_') and col not in identities:
                    row[col] = ''
        buffer = io.StringIO(newline='')
        writer = csv.DictWriter(buffer, fieldnames=header, lineterminator='\n')
        writer.writeheader(); writer.writerows(rows)
        outputs[path] = buffer.getvalue().encode('utf-8')
    expected = {p: modkit.state(p) for p in outputs}
    written = modkit.commit_files(outputs, expected, {**inputs, **preserved})
    for path, fingerprint in preserved.items():
        if modkit.state(path) != fingerprint:
            raise ValueError('Unrelated Hard Mode content moved during transfer: %s' % path)
    return {'written': written, 'preserved': {str(p): state[2] for p, state in preserved.items()}}


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--config', type=Path, required=True)
    ap.add_argument('--data', type=Path)
    args = ap.parse_args()
    print(pb.encode(transfer(args.config, args.data)).decode())
