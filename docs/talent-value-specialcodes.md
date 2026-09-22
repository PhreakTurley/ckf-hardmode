# Talent-value model: tally economy and special codes

Use this page when changing or interpreting the Security Tally, corpse-disposal,
device-disable, or `EffectSpecialCode` branches in `scripts/talent_value.py`.
The script is authoritative for constants and formulas; its module docstring is
authoritative for inputs, output, and the general value unit (VU).

- Code names come from `_id_constants.csv`, class `EffectSpecialCode`.
- Quoted game text is from `StreamingAssets/Locales/en-US.json` (`Job.Effects.SpecialCodes.<Name>`).
- **Output snapshots.** Talent values and ratios below record one script run.
  Re-run the script against the current `sheets/raw` before relying on them.

## Units

VU is one point of Accuracy, Crit, Move Speed or Kinetic Dmg% held for one combat turn. Security Tally is a second named unit on top of VU. Everything stealth-related is priced in tally.

| Constant | Value | Meaning |
|---|---|---|
| `TALLY` | 17.0 | VU per 1 Security Tally avoided or removed |
| `CORPSE_TALLY` | 5 | Tally avoided by one whole-corpse removal |
| `CORPSE` | derived | `CORPSE_TALLY × TALLY − AP × Dissolve's ApCost` (`calibrate`) |
| `DEVICE_TALLY` | calibrated | Tally avoided per device disable, solved so the median device-disable talent sits at `DEVICE_TARGET` × the base median |
| `DEVICE_TARGET` | 1.15 | |
| `DEVICE_EXT` | 0.3 | Each disable turn after the first, relative to the first |
| `RANGE_REF` | 15.0 | Reference range in metres |
| `RANGE_W` | 0.25 | Value change per 100% of `RANGE_REF` |
| `TYPICAL`, `TYPICAL_USES` | calibrated | Median value and median uses of a scored base talent ("a typical talent") |

- **Tally drives the stealth economy.** Raising `TALLY` raises everything priced in tally. Because `DEVICE_TALLY` is solved against a target, the device-disable family stays put and everything else moves relative to it.
- **Range.** Range applies once, centrally, to every tally-derived accumulator (`corpse`, `disable`, `linecrawl`, `BioMimic`, `BioTheft`, `heal5`, `NoReport`):

  ```
  rangef = 1 + RANGE_W × (Range / RANGE_REF − 1)
  ```

  Self-target talents have no `Range` and get 1.00.
- **Crashkit is Jamkit.** No talent row is named Crashkit. The tutorial strings call the Vanguard's Jamkit (node 12020, talent 1200) "Crashkit".

## Tally-family output snapshot

Ratios are value per point against the base-talent median (last recorded: 51.3 VU per point).

| node | talent | Range | rangef | value | ratio |
|---|---|---|---|---|---|
| 5020 | Line Crawler | 12 m | 0.95 | 115.8 | 2.13x |
| 5360 | Signal Grift | 5 m | 0.83 | 99.6 | 1.83x |
| 2080 | Ash Protocol | 8 m | 0.88 | 85.5 | 1.57x |
| 19040 | Skipjack | 15 m | 1.00 | 81.7 | 1.50x |
| 13140 | Packet Loss | 25 m | 1.17 | 76.0 | 1.40x |
| 16020 | Dissolve | 3 m | 0.80 | 72.1 | 1.32x |
| 160 | Security Scramble | 18 m | 1.05 | 65.0 | 1.19x |
| 19140 | Security Siphon | 15 m | 1.00 | 60.3 | 1.11x |
| 12020 | Jamkit | 12 m | 0.95 | 55.6 | 1.02x |
| 13220 | Prank | 25 m | 1.17 | 46.7 | 0.86x |
| 12080 | Bodybag | 12 m | 0.95 | 46.7 | 0.86x |
| 19160 | Radio Silence | 18 m | 1.05 | 40.9 | 0.75x |
| 13180 | Faked Vitals | 6 m | 0.85 | 37.3 | 0.68x |
| 12040 | K-Protocol | 5 m | 0.83 | 26.3 | 0.48x |
| 16080 | Bio-Mimic | self | 1.00 | 26.3 | 0.48x |
| 2320 | Overheat | 15 m | 1.00 | 23.0 | 0.42x |

- **Dissolve.** Its value is `(4 × TALLY − 30) × 1.90 uses`, so `TALLY = 14.7` would put it at 1.00x. At 17 the corpse family sits above average.
- **Overheat.** Its 2 AP cost is charged in full, which is why it sits at 0.42x.
- **`DEVICE_TALLY`.** The last recorded calibration gave 1.88.

## Special-code weights in `P['SC']`

Codes priced as a fraction of a finished talent (2, 13, 29, 82) add the talent's own AP back before taking the fraction. So "half a Crashkit" means half of Jamkit's net value.

| Code | Name | Constant | Meaning | Talents carrying it |
|---|---|---|---|---|
| 1 | Disorient | `DISORIENT = 0.10` | Fraction of a stun turn, per turn held | Disorient |
| 2 | BioMimic | `BIOMIMIC = 0.5` | Fraction of one finished device disable | Bio-Mimic |
| 3 | EnemyShootsOwn | `SHOOTSOWN = 1.5` | Multiples of a stun turn, per turn held | Brain Worm |
| 4 | IncreaseInjuryOrStress | `INJURY = 1.0` | Negative VU per % chance, per use | Life-Hack, Reknit (both score negative) |
| 9 | CannotHearMovement | `DEAF` (calibrated) | Solved so the median talent carrying it sits at the base median | White-Noise, Thrown Bullet |
| 11 | LineCrawlerDisable | `LINECRAWL = 0.5` | A bounced disable relative to a deliberate one | Line Crawler |
| 12 | DualSMGStreak | `STREAK_REQ = 0.5` | Multiplier on the whole effect, for the two-SMG requirement | Aimlock |
| 13 | BioTheft | `BIOTHEFT = 0.5` | Stealth half, as a fraction of a finished disable. The corpse half is a 0.5 `CORPSE_SHARE` | Signal Grift |
| 18 | SkipOverwatch | `SKIPOVERWATCH = 10.0` | VU per use (one avoided reaction shot) | Cover Me |
| 19 / 23 / 24 | Convert…FullAuto, AttackDualWeapon | `WEAPON_CONV = 0.75` | Fraction of the AP these generate, discounted for the weapon lock | Fanning, Gun Kata, Twin Iron |
| 20 | ReloadRevolverFree | `FREERELOAD = 1/6` | Share of a reload returned per attack | Fingertrick |
| 21 | AlwaysGlancing | `GLANCING = 10.0` | % damage added to the attack | Called Shot |
| 27 | InvisibleWhileNotMoving | `BLEND = 2.0` | VU per turn held | Blend |
| 29 | SecurityPriorityDispatch | `DISPATCH = 0.75` | Multiples of a typical talent, per use | Prank |
| 72 | CyberWeaponAccuracy | `CYBERACC = 1.0` | Plain accuracy; the weapon lock comes from `MASTERY` | Laser Master 3 / 4 |
| 74 | CyberWeaponDamage | `CYBERDMG74 = 1.0` × `CYBERDMG` × class share | Cybernetic weapon damage | No player node uses it |
| 79 | BlockSecurityReports | `NOREPORT = 2.0` | Tally avoided per use | Radio Silence |
| 82 | SpectralStartConnection | `SPECTRAL = 1.5` | Multiples of a typical talent, per use | Skipjack |

### Line Crawler bounce

- One bounce attempt fires at the start of each turn after the first. A 1-turn cast never bounces.
- A bounce inherits the debuff's remaining duration, and bounces do not bounce again.
- At the shipped 3-turn duration and `SpecialValue` 50%:

  ```
  turn 2  50% × a 2-turn disable
  turn 3  50% × a 1-turn disable
          × LINECRAWL 0.5 (neither target nor timing is chosen)
  ```

- The count comes from the live duration, so the Line Crawler 6 duration upgrade earns its extra bounce automatically.

### Cyber mastery chains

`Claw Master`, `Laser Master`, `Pulse Gen Master`, `Blast Radius` and `Metabolize` are roots with `NodeTalent1Id = -1`, so there is no talent row for their nodes to modify. A root listed in `MASTERY` is scored like a travel node, at that root's share:

```
MASTERY = {2040: 0.50,    # Claw Master
           2100: 0.25,    # Laser Master
           2140: 0.25}    # Pulse Gen Master
```

- **What a chain node scores.**
  - `TalentDamage` becomes a permanent % damage bonus (`TalentDamage × COMBAT × share`).
  - `NodeTalentTriggerEffect` is scored as a permanent effect at the same share.
- **What stays unscored.** Modifiers that need a base talent (`MaxCharges`, `TalentAp`, `RechargeTurns`) stay unvalued and flagged.
- **Roots with no share.** `Blast Radius` (7220) and `Metabolize` (16200) have no share and score `no-base`.

Output against the upgrade median (last recorded: 21.7):

| Node | Scores | Value | Ratio |
|---|---|---|---|
| Claw Master 4 / 5 / 6 | +10% dmg each | 25.0 | 1.15x |
| Claw Master 1 / 2 / 3 | recharge, charge, AP | — | unscored |
| Laser Master 1 | +10% dmg | 12.5 | 0.58x |
| Laser Master 2 | +15% dmg | 18.8 | 0.86x |
| Laser Master 3 / 4 | +5% cyber acc | 6.2 | 0.29x |
| Laser Master 5 | heal type 15 | 0.2 | 0.01x |
| Laser Master 6 | +1 charge | — | unscored |
| Pulse Gen Master 4 / 5 / 6 | +10% dmg each | 12.5 | 0.58x |
| Pulse Gen Master 1 / 8 | heal type 15 | 0.6 | 0.03x |
| Pulse Gen Master 2 / 3 / 7 | recharge, AP | — | unscored |

### Inputs derived by the script

- **AP printers.** `ATTACK_AP` and `RELOAD_AP` are read from `WeaponModel` medians per weapon class (`WEAP` in the script).
  - Fanning and Gun Kata: `Revolver.ReloadSize` (6) shots × `Revolver.ActionPoints` (20 stored).
  - Twin Iron: 2 × 20.
  - Fingertrick's reload: `Revolver.ReloadActionPoints`.
- **`TalentDamage` on upgrades** is a percentage multiplier on the talent's own damage ("gains +{0}% Damage"), applied across every shot.
- **Will (`AttWill`)** reads "+1% Cybernetic Weapon Dmg per 1 Will, +2% Stress Res per 1 Will, +1% Built-In Armor per 2 Will". It is split in two:
  - The armour half stays in `W()` as `0.5 × DEF`.
  - The cyber-damage half is scored in `effect_parts` as `CYBERDMG × class share × points`, where the class share is 1.0 for `CYBER_JOBS = {2}` (Warmachine) and `CYBER_OFF = 0.25` for everyone else.
  - The job is passed through to `effect_parts`, so an attribute on a talent effect gets the right class share.
- **`ArmorCrit`** is weighted 1.0 per point, tag A.

## Known model gaps

- `TALLY = 17` leaves Dissolve at 1.32x rather than 1.00x; 14.7 would give
  1.00x in the recorded run.
- `Blast Radius` and `Metabolize` need a `MASTERY` share to be scored.

These are gaps in the valuation model, not claims about the game's mechanics or
recommendations for talent balance.
