"""Resolve existing Steam installations without publishing or editing Steam state."""
import json
from pathlib import Path
import re


def require_steam_install(workshop):
    """A manually created directory is not an installed Steam Workshop item."""
    workshop = Path(workshop)
    appid, itemid = workshop.parent.name, workshop.name
    if not appid.isdecimal() or not itemid.isdecimal():
        raise ValueError(f"Expected workshop/content/<appid>/<itemid>: {workshop}")
    manifest = workshop.parents[2] / f"appworkshop_{appid}.acf"
    try:
        content = manifest.read_text(encoding='utf-8-sig')
        tokens, offset = [], 0
        pattern = re.compile(r'\s+|//[^\r\n]*|"((?:\\.|[^"\\])*)"|([{}])')
        while offset < len(content):
            match = pattern.match(content, offset)
            if not match:
                raise ValueError('Invalid Steam manifest token')
            if match.group(1) is not None or match.group(2):
                tokens.append((match.group(1), match.group(2)))
            offset = match.end()
        index = 0

        def object_value(nested=False):
            nonlocal index
            result = {}
            while index < len(tokens):
                text, brace = tokens[index]
                index += 1
                if brace == '}':
                    if not nested:
                        raise ValueError('Unexpected closing brace')
                    return result
                if brace or index >= len(tokens) or text in result:
                    raise ValueError('Missing or duplicate key/value')
                value, delimiter = tokens[index]
                index += 1
                if delimiter == '{':
                    result[text] = object_value(True)
                elif delimiter:
                    raise ValueError('Missing value')
                else:
                    result[text] = value
            if nested:
                raise ValueError('Unclosed object')
            return result

        root = object_value()['AppWorkshop']
        if not isinstance(root, dict):
            raise ValueError('AppWorkshop is not an object')
        if root.get('appid', appid) != appid:
            raise ValueError('Steam manifest belongs to another game')
        installed = root.get('WorkshopItemsInstalled', {})
        if not isinstance(installed, dict):
            raise ValueError('WorkshopItemsInstalled is not an object')
    except (OSError, KeyError, ValueError) as exc:
        raise ValueError(f"Could not establish Steam installation from {manifest}: {exc}") from exc
    if itemid not in installed or not isinstance(installed[itemid], dict):
        raise ValueError(f"Steam has not registered Workshop item {itemid} as installed. "
                         "Subscribe to your own item and let Steam finish downloading before exporting. "
                         "Creating its folder or copying SQL alone does not register it.")
    return {'manifest': str(manifest), 'appid': appid, 'itemid': itemid}


def local_install_target(mod, state):
    """Use the uploader's selected folder, with matching item/game and registration."""
    mod = Path(mod)
    metadata = mod.parent / (mod.name + '.workshop.json')
    inputs = {metadata: state(metadata)}
    document = json.loads(metadata.read_text(encoding='utf-8-sig'))
    itemid = document.get('publishedfileid')
    folder = document.get('steamModFolder')
    if not isinstance(itemid, str) or not re.fullmatch(r'[1-9][0-9]*', itemid):
        raise ValueError('The Modkit project needs a published Workshop item before local installation.')
    if not isinstance(folder, str) or not folder.strip() or not Path(folder).is_absolute():
        raise ValueError('Set the Steam Mod folder in Modkit once before exporting for local testing.')
    workshop = Path(folder).resolve()
    if (workshop.name != itemid or workshop.parent.name != '1021210'
            or workshop.parents[1].name.lower() != 'content'
            or workshop.parents[2].name.lower() != 'workshop'):
        raise ValueError('The Steam Mod folder must be workshop/content/1021210/' + itemid + '.')
    if not workshop.is_dir():
        raise ValueError('The selected Workshop item has not been downloaded: ' + str(workshop))
    manifest = workshop.parents[2] / 'appworkshop_1021210.acf'
    inputs[manifest] = state(manifest)
    require_steam_install(workshop)
    for path, expected in inputs.items():
        if state(path) != expected:
            raise ValueError('Local installation input changed: ' + str(path))
    return workshop, inputs
