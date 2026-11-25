"""Shipped localization bindings for the editor's active cyberware preview."""

import re


# TalentModel.Describe and DescribeMatrix place these fields in locale arguments.
FIELDS = {
    'ap': 'ApCost', 'range': 'Range', 'aoe': 'RangeAoE', 'mode': 'WeaponMode',
    'pure': 'PureDamage', 'ballistic': 'BallisticDamage', 'physical': 'PhysicalDamage',
    'tokenDuration': 'TokenDuration', 'teamLimit': 'TeamTurnMaxUses', 'turnLimit': 'TurnMaxUses',
}
FIRING_MODES = ('NA', 'SS', 'SA', 'BF', 'FA', 'Melee', 'Shotgun', 'DualSMG',
                'PistolsOrRevolvers', 'Revolver', 'DualPistols', 'CyberClaws')
# EffectModel.DescribeAsList uses localized modifiers. The signed value is
# passed through unless the localized debuff text supplies its own sign.
EFFECTS = {
    'MeleeAttack': ('AccuracyMelee.Buff', 'AccuracyMelee.Debuff'),
    'RangedAttack': ('AccuracyRanged.Buff', 'AccuracyRanged.Debuff'),
    'AccuracyDrone': ('AccuracyDrone.Buff', 'AccuracyDrone.Debuff'),
    'CritRate': ('Critical',), 'CritRateStealth': ('CriticalStealthRate',),
    'CritRateStreak': ('CriticalStreak',), 'CritVulnerable': ('CriticalVulnerablity',),
    'CritMultiBase': ('CriticalDamage',), 'CritMultiStealth': ('CriticalDamageStealth',),
    'PureDamageBallistic': ('PureDamageBuff', 'PureDamageDebuff'),
    'PureDamageMelee': ('PureDamageBuff.Melee', 'PureDamageDebuff.Melee'),
    'PhysicalDamage': ('PhysicalDamageBuff', 'PhysicalDamageDebuff'),
    'BallisticDamage': ('BallisticDamageBuff', 'BallisticDamageDebuff'),
    'DroneDamage': ('DroneDamageBuff', 'DroneDamageDebuff'),
    'PhysicalArmor': ('PhysicalArmorBuff', 'PhysicalArmorDebuff'),
    'BallisticArmor': ('BallisticArmorBuff', 'BallisticArmorDebuff'),
    'PureArmor': ('PureArmorBuff', 'PureArmorDebuff'),
    'Evasion': ('Evasion.Buff', 'Evasion.Debuff'),
    'DetectRangeReduction': ('DetectRangeReduction', 'DetectRangeReduction.Debuff'),
    'RecoilBonus': ('Recoil.Buff', 'Recoil.Debuff'),
    'RecoilRate': ('RecoilRate.Buff', 'RecoilRate.Debuff'),
    'MoveSpeed': ('MoveSpeed.Buff', 'MoveSpeed.Debuff'),
    'Invulnerable': ('Invulnerable',), 'Silent': ('Silent',),
    'InitBonus': ('InitiativeBuff', 'InitiativeDebuff'),
    'ActionPoints': ('ActionPoints.Buff', 'ActionPoints.Debuff'),
    'MovePoints': ('MovePoints.Buff', 'MovePoints.Debuff'),
    'StressRes': ('StressRes.Buff', 'StressRes.Debuff'),
    'WoundRes': ('WoundRes.Buff', 'WoundRes.Debuff'),
}
MATRIX_EFFECTS = {
    'ActionPoints': ('AP.Buff', 'AP.Debuff'),
    'IoPercent': ('IOPercent.Buff',),
    'DeckShield': ('Shield.Buff', 'Shield.Debuff'),
}
HEALING = {
    1: ('HealsHp',), 2: ('HealsArmor', 'HealsArmorNegative'), 3: ('HealsStress',),
    4: ('HealsRecoil',), 10: ('DamageOverTime',), 14: ('DroneDamageOverTime',),
    15: ('ReduceHealth', 'ReduceHealth.Debuff'),
}


def localized(value):
    if isinstance(value, dict):
        return {key: localized(text) for key, text in value.items() if isinstance(text, str)}
    if isinstance(value, str):
        return re.sub(r'<(?:/?(?:b|i|nobr|color|style))(?:=[^<>]+)?>', '', value)
    return None


def presentation(locale):
    def rules(prefix, mapping):
        return {field: [localized(locale.get(prefix + key)) for key in keys]
                for field, keys in mapping.items()}

    return {
        'fields': FIELDS,
        'effectRules': rules('Job.Effects.', EFFECTS),
        'matrixRules': rules('Job.MatrixEffects.', MATRIX_EFFECTS),
        'healingRules': rules('Job.Effects.', HEALING),
        'modes': [locale.get('Gear.Weapon.FiringMode.' + mode, '') for mode in FIRING_MODES],
        'units': {'ActionPoints': 10, 'MovePoints': 10},
        'absolute': ['DetectRangeReduction', 'RecoilRate'],
        'absoluteDebuffs': ['Evasion'],
        'healingColumns': ['EffectHealType', 'Heals'],
        'weaponCritColumn': 'CritMultiBase',
        'weaponStealthCritColumn': 'CritMultiStealth',
        'specialColumns': ['SpecialCode', 'MoveSpeedDebuff', 'MoveSpeedMitigate', 'Stunned'],
        'specialText': {key: localized(locale.get('Job.Effects.' + key)) for key in (
            'SpecialCodes.InvisibleWhileNotMoving', 'SpecialCodes.MoveSpeedMitigation', 'MoveSpeed.Debuff',
            'Stunned', 'StunChance', 'StunImmune', 'StunResist')},
        'limits': [localized(locale.get('Job.Talents.Active.' + key)) for key in
                   ('GlobalMaxUsePerTurn', 'MaxUsePerTurn')],
    }


def talent_preview(locale, name, group, key, matrix, has_target, has_self, tokens, weapon):
    """Describe the joined fields read by each placeholder in the stock template."""
    self_only = has_self and not has_target and not tokens
    if matrix:
        duration, main = 'MatrixDuration', 'matrix effect'
    elif tokens:
        duration, main = 'TokenDuration', 'target effect'
    elif self_only:
        duration, main = 'SelfDuration', 'self effect'
    else:
        duration, main = 'TargetEffectDuration', 'target effect'
    text = localized(locale.get(key))
    # The installed English locale has the drone buff wording, but omits this
    # key. Mark the sibling template as a preview when rendering it.
    fallback = None
    if not text and key == 'Job.Talents.Active.FriendBuff.PetDrone.ReduceHP':
        fallback = localized(locale.get('Job.Talents.Active.FriendBuff.PetDrone'))
    return {
        'name': name, 'group': group, 'text': text, 'fallback': fallback, 'matrix': matrix,
        'durationColumn': duration, 'mainEffect': group + ' ' + main, 'selfEffect': group + ' self effect',
        'weapon': weapon,
    }
