# Tally economy and EffectSpecialCode weights — talent_value.py

How the model turns Security Tally, corpse disposal, device disables and the
`EffectSpecialCode` mechanics into VU. Every number below is a named entry in `P`
(or `P['SC']`) in `scripts/talent_value.py`; change the number, re-run, done.

Constant names come from `sheets/raw/_id_constants.csv` class `EffectSpecialCode`.
Quoted text is verbatim from `StreamingAssets/Locales/en-US.json`
(`Job.Effects.SpecialCodes.<Name>`).

---

## 1. The unit chain

VU is still "1 point of Accuracy / Crit / Move Speed / Kinetic Dmg% held for one
combat turn". Tally now hangs off it as a second named unit, and everything
stealth-flavoured is quoted in tally rather than in VU directly.

```
TALLY        = 17.0   VU per 1 Security Tally avoided or removed      <- the dial
CORPSE_TALLY = 5      tally avoided by one whole-corpse removal
CORPSE       = 55.0   derived: CORPSE_TALLY * TALLY - AP cost of Dissolve
DEVICE_TALLY = 1.88   tally avoided per device disable                <- calibrated
DEVICE_TARGET= 1.15   what DEVICE_TALLY is solved for: the median Crashkit-family
                      talent sits at 1.15x the median scored base talent
DEVICE_EXT   = 0.30   each disable turn after the first, relative to the first
RANGE_REF    = 15.0   reference Range in metres for DEVICE-target talents
RANGE_W      = 0.25   value change per 100% of RANGE_REF
```

**What changed from before.** `CORPSE` used to be the primary number, solved each run
so Dissolve landed on the median base talent, with tally falling out of it. That is
now inverted: `TALLY` is stated, `CORPSE` falls out. `TALLY = 12.0` is exactly the
value the old calibration implied, so Dissolve, Ash Protocol, Bodybag, Faked Vitals
and K-Protocol have not moved. Raising `TALLY` now raises the whole stealth economy
together instead of only the corpse talents.

**Range.** Everything quoted in tally is range-sensitive, so `rangef` is applied once, centrally,
to every tally-derived accumulator: `corpse`, `disable`, `linecrawl`, `BioMimic`, `BioTheft`,
`heal5` (the tally heal) and `NoReport`. Reaching a corpse at 3 m is not the same offer as
reaching a device at 25 m.

    rangef = 1 + RANGE_W * (Range/RANGE_REF - 1)

which is the convention the upgrade path already uses when a node adds `TalentRange`. Self-target
talents (Bio-Mimic, Blend) have no `Range` and come out at 1.00.

**Naming note.** There is no `Crashkit` row. The tutorial strings call the Vanguard's
**Jamkit** (node 12020, talent 1200) "Crashkit"; the DB name is Jamkit.

## 2. Where the tally family lands

Base median = 51.3 VU per point. Ratios are per-point against that median.

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
| 12020 | Jamkit / Crashkit | 12 m | 0.95 | 55.6 | 1.02x |
| 13220 | Prank | 25 m | 1.17 | 46.7 | 0.86x |
| 12080 | Bodybag | 12 m | 0.95 | 46.7 | 0.86x |
| 19160 | Radio Silence | 18 m | 1.05 | 40.9 | 0.75x |
| 13180 | Faked Vitals | 6 m | 0.85 | 37.3 | 0.68x |
| 12040 | K-Protocol | 5 m | 0.83 | 26.3 | 0.48x |
| 16080 | Bio-Mimic | self | 1.00 | 26.3 | 0.48x |
| 2320 | Overheat | 15 m | 1.00 | 23.0 | 0.42x |

`DEVICE_TALLY` is solved so the **median** of the plain disable talents equals 1.15x the base
median; Range then spreads them. Because it is solved against a target, raising `TALLY` does not
move the disable family — it moves everything quoted in tally *relative* to them: corpse
disposal, K-Protocol, Radio Silence, Bio-Mimic and Signal Grift all rise together while
`DEVICE_TALLY` falls to compensate (2.67 -> 1.88 when TALLY went 12 -> 17).

`TALLY = 17.0` puts Dissolve at 1.32x. Dissolve's value is `(4 x TALLY - 30) x 1.90` uses, so
**TALLY = 14.7** would land it exactly on the base median if that is what you want; 17 leaves the
corpse family deliberately above average.

## 3. The codes

`SC[...]` weights, with what the game text says and where the talent landed.
Codes quoted as a fraction of something finished (2, 13, 29, 82) add the talent's own
AP back before the fraction, so "half a Crashkit" means half Crashkit's *net* value.

| code | name | knob | meaning | result |
|---|---|---|---|---|
| 1 | Disorient | `DISORIENT = 0.10` | fraction of a stun turn, per turn held | Disorient 33.9 (0.62x) |
| 2 | BioMimic | `BIOMIMIC = 0.5` | fraction of one finished device disable | Bio-Mimic 26.3 (0.48x) |
| 3 | EnemyShootsOwn | `SHOOTSOWN = 1.5` | multiples of a stun turn, per turn held | Brain Worm 133.4 (2.45x) |
| 4 | IncreaseInjuryOrStress | `INJURY = 1.0` | negative VU per % chance, per use, at MoveSpeed's 1/point | Life-Hack −108.7, Reknit −135.7 |
| 9 | CannotHearMovement | `DEAF = 20.6` | **calibrated** so the median talent carrying it sits at the base median | White-Noise 77.7 (1.43x), Thrown Bullet 31.2 (0.57x) |
| 11 | LineCrawlerDisable | `LINECRAWL = 0.5` | a bounced disable, relative to a deliberate one; see below | Line Crawler 115.8 (2.13x) |
| 12 | DualSMGStreak | `STREAK_REQ = 0.5` | multiplier on the whole effect, for the carry-2-SMGs requirement | Aimlock 182.8 (3.36x) |
| 13 | BioTheft | `BIOTHEFT = 0.5` | stealth half, as a fraction of a finished disable; the corpse half is a 0.5 `CORPSE_SHARE` | Signal Grift 98.0 (1.80x) |
| 18 | SkipOverwatch | `SKIPOVERWATCH = 10.0` | VU per use, one avoided reaction shot | Cover Me 22.6 (0.42x) |
| 19/23/24 | Convert…FullAuto, AttackDualWeapon | `WEAPON_CONV = 0.75` | fraction of the AP these print, discounted for the weapon lock | Fanning 148.7, Gun Kata 180.1, Twin Iron 14.8 |
| 20 | ReloadRevolverFree | `FREERELOAD = 1/6` | share of a reload returned per attack | Fingertrick 38.8 (0.71x) |
| 21 | AlwaysGlancing | `GLANCING = 10.0` | % damage added to the attack | Called Shot 16.6 (0.30x) |
| 27 | InvisibleWhileNotMoving | `BLEND = 2.0` | VU per turn held | Blend 22.1 (0.40x) |
| 29 | SecurityPriorityDispatch | `DISPATCH = 0.75` | multiples of a typical talent, per use | Prank 46.7 (0.86x) |
| 72 | CyberWeaponAccuracy | `CYBERACC = 1.0` | plain accuracy; the weapon lock is carried by `MASTERY` | Laser Master 3 / 4, 6.2 each (0.29x upg) |
| 74 | CyberWeaponDamage | `CYBERDMG = 0.5`, class-scaled | Cybernetic Weapon Dmg, as a fraction of plain damage | no player node reaches it today; wired |
| 79 | BlockSecurityReports | `NOREPORT = 2.0` | tally avoided per use | Radio Silence 17.8 (0.33x) |
| 82 | SpectralStartConnection | `SPECTRAL = 1.5` | multiples of a typical talent, per use | Skipjack 81.7 (1.50x) |

"A typical talent" = `TYPICAL` / `TYPICAL_USES`, the median value and median uses of a
scored base talent, both solved each run alongside `DEVICE_TALLY` and `DEAF`.

### How the Line Crawler bounce is counted

One bounce attempt fires at the start of each turn **after the first**, so a 1-turn cast can
never bounce and a 2-turn cast bounces at most once. A bounce inherits whatever duration the
original debuff has left, and bounces do not bounce again. At the shipped 3-turn duration
and `SpecialValue` 50%:

```
turn 2  50% x a 2-turn disable
turn 3  50% x a 1-turn disable
        x LINECRAWL 0.5, because you pick neither the target nor the timing
```

That is 0.58 of a deliberate disable on top of its own 3-turn cast, landing Line Crawler at
2.13x rather than the 4.43x a naive "50% x 3 turns" reading gave. The count comes off the
live duration, so the Line Crawler 6 duration upgrade earns its extra bounce attempt
automatically (+81.8 VU, up from +40.9 before the duration was counted).

### Cyber mastery chains

`Claw Master`, `Laser Master`, `Pulse Gen Master`, `Blast Radius` and `Metabolize` are roots with
`NodeTalent1Id = -1`: there is no talent row to modify, so their whole chains used to score
`no-base`. They are permanent passives on whatever the implant grants, so a root listed in
`MASTERY` is now scored like a travel node, at that root's share of full value.

```
MASTERY = {2040: 0.50,    # Claw Master
           2100: 0.25,    # Laser Master
           2140: 0.25}    # Pulse Gen Master
```

A node's `TalentDamage` becomes a permanent % damage bonus (`TalentDamage x COMBAT x share`) and
its `NodeTalentTriggerEffect` is scored as a permanent effect, both at the root's share — nothing
is exempt, so Laser Master's cyber accuracy takes the same flat 25% its damage does. Modifiers
that need a base talent to attach to (`MaxCharges`, `TalentAp`, `RechargeTurns`) stay unvalued
and flagged.

| node | scores | value | vs upgrade median (21.7) |
|---|---|---|---|
| Claw Master 4 / 5 / 6 | +10% dmg each | 25.0 | 1.15x |
| Claw Master 1 / 2 / 3 | recharge, charge, AP | — | unscored, no base talent |
| Laser Master 1 | +10% dmg | 12.5 | 0.58x |
| Laser Master 2 | +15% dmg | 18.8 | 0.86x |
| Laser Master 3 / 4 | +5% cyber acc | 6.2 | 0.29x |
| Laser Master 5 | heal type 15 | 0.2 | 0.01x |
| Laser Master 6 | +1 charge | — | unscored, no base talent |
| Pulse Gen Master 4 / 5 / 6 | +10% dmg each | 12.5 | 0.58x |
| Pulse Gen Master 1 / 8 | heal type 15 | 0.6 | 0.03x |
| Pulse Gen Master 2 / 3 / 7 | recharge, AP | — | unscored, no base talent |

`Blast Radius` (7220, grenades) and `Metabolize` (16200, combat drugs) have no share and still
score `no-base`.

### Two things that are now programmatic

**AP printers.** `ATTACK_AP` and `RELOAD_AP` used to be hand-entered stored-AP numbers.
They are now read from `WeaponModel` medians per weapon class: Fanning and Gun Kata are
`Revolver.ReloadSize` (6) shots at `Revolver.ActionPoints` (20 stored) = 120, Twin Iron
is 2 x 20 = 40, Fingertrick's reload is `Revolver.ReloadActionPoints` (20). The derived
tables reproduce the old hand-entered numbers exactly, so a weapon rebalance now flows
through instead of going stale.

**`TalentDamage` upgrades.** `Job.Adjustments.PureDmg` reads "gains +{0}% Damage", so a
node's `TalentDamage` is now a percentage multiplier on the talent's own damage. That
retires the 15 `unvalued: damage?` flags, and any talent with a shot multiplier gets the
bonus applied across all its shots automatically.

**Cybernetic weapon stats.** `CYBERDMG = 0.5` is the one place Cybernetic Weapon Damage is
priced: half of plain damage. It feeds both `EffectSpecialCode 74` and the **Will** attribute,
whose game text reads "+1% Cybernetic Weapon Dmg per 1 Will, +2% Stress Res per 1 Will, +1%
Built-In Armor per 2 Will".

Will is also class-scaled, the way `AttStrong` already was:

```
CYBER_JOBS = {2}        # Warmachine
CYBER_OFF  = 0.25       # the same damage for every other class
```

`AttWill` is therefore split in two. The +1% Built-In Armor per 2 Will stays in `W()` as
`0.5 x DEF`, since armour does not care who is wearing it. The +1% Cybernetic Weapon Dmg per Will
moved into `effect_parts` next to `AttStrong`, where the job is known, and scores
`CYBERDMG x cyber_share x points`: **2.5 VU per Will point for Warmachine, 0.625 for everyone
else**. That dropped 80 off-class travel nodes by 1.88 VU each and left Warmachine's 12 untouched;
the travel median moved 16.0 -> 15.9.

Attributes only ever appear on travel-node effects in the shipped data (92 `AttWill`, 65
`AttStrong`, 83 `AttFast`, 94 `AttTech`, plus one `AttTech` on a talent effect), and travel nodes
always knew their job. `value()` now threads the job through to `effect_parts` anyway, so a future
patch that puts one of these on a talent effect gets the right class share instead of silently
taking the off-class one.

Cyberweapon **accuracy** (code 72) is scored as plain accuracy at 1.0 per point and takes its
discount from the mastery share alone — Laser Master's 5% is laser-only, so it gets the same flat
25% its damage nodes get, and is no longer double-discounted.

**Other change:** `ArmorCrit` moved from 0.3 to **1.0 per point**, tag A, per your note
that it should weigh like Accuracy. That also moves Twin Iron and Aimlock.

## 4. Open questions

### Settled

- **Line Crawler bounce** — off-by-one fixed, bounces inherit remaining duration, and
  `LINECRAWL = 0.5`. 4.43x -> 2.13x.
- **`NOREPORT = 2`** — one blocked security report is worth 2 tally. Radio Silence
  −5.9 -> 17.8 (0.33x).
- **`INJURY` stays at 1.0** and healing stays where it is. Reknit −135.7 and Life-Hack
  −108.7 are the model reporting that these talents pay a mission-level cost for a
  combat-turn benefit; the outlier is the finding, not a bug to tune away.
- **Twin Iron stays at 0.27x.** Converting 4 AP of attacks into the 3 AP it costs, under a
  two-weapon requirement, really is worth about nothing past its `ArmorCrit` 15.

### Still open

1. **`TALLY = 17` leaves Dissolve at 1.32x, not 1.00x.** 14.7 is the value that lands it on the
   median. 17 was carried through as given; say the word and it moves.
2. **Overheat** is settled: its 2 AP is charged in full, which is the whole reason it sits at
   0.42x rather than alongside Jamkit.
3. **`Blast Radius` and `Metabolize`** still score `no-base`; they need a share to be scored.
