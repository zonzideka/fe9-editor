#!/usr/bin/env python3
"""User-rules configuration for FE9 promoted class caps mod.

Per CLAUDE.md authoritative rules:
  1. HP=80 only for: Lord/Hero (JID_HERO), General, Berserker, DragonMaster (M+F)
  2. Lck=80 for ALL promoted classes
  3. Str/Mag/Skl/Spd/Def/Res: current+10 (no upper limit)
  4. Exception: Valkyrie (Mist) and Queen (Elincia) — HP and 6 mains all = 60, Lck=80
"""

# --- Promoted human classes (mainstream) ---
# All get: Lck=80, 6 mains +10, HP unchanged unless in HP80 set.
PROMOTED_HUMAN = {
    1:  'JID_HERO',              # Lord / Hero (Ike, Boyd promote here)
    2:  'JID_HERO_G',            # Greil (NPC, dies ch4)
    5:  'JID_SWORDMASTER',
    6:  'JID_SWORDMASTER/F',
    9:  'JID_HALBERDIER',
    10: 'JID_HALBERDIER/F',
    12: 'JID_WARRIOR',
    14: 'JID_SNIPER',
    16: 'JID_GENERAL',
    25: 'JID_PALADIN_S',
    26: 'JID_PALADIN_L',
    27: 'JID_PALADIN_A',
    28: 'JID_PALADIN_B',
    29: 'JID_PALADIN_S/F',
    30: 'JID_PALADIN_L/F',
    31: 'JID_PALADIN_A/F',
    32: 'JID_PALADIN_B/F',
    33: 'JID_TIAMAT/F',          # Tanith / Marcia variant
    34: 'JID_UNUSED0/F',
    36: 'JID_FALCONKNIGHT/F',    # Marcia, Tanith
    40: 'JID_DRAGONMASTER',      # Haar (male)
    41: 'JID_DRAGONMASTER/F',    # Jill (female)
    51: 'JID_SAGE_F',
    52: 'JID_SAGE_W',
    53: 'JID_SAGE_T',
    54: 'JID_SAGE',
    55: 'JID_SAGE_F/F',
    56: 'JID_SAGE_W/F',
    57: 'JID_SAGE_T/F',
    58: 'JID_SAGE/F',
    59: 'JID_SAGE_R_F',
    60: 'JID_SAGE_R_W',
    61: 'JID_SAGE_R_T',
    62: 'JID_SAGE_S_F',
    63: 'JID_SAGE_S_W',
    64: 'JID_SAGE_S_T',
    66: 'JID_BISHOP',
    67: 'JID_BISHOP/F',
    71: 'JID_ASSASSIN',
    72: 'JID_ASSASSIN/F',
    74: 'JID_BERSERKER',
    105: 'JID_SAGE_R',
    106: 'JID_SAGE_S',
    108: 'JID_SAGE_R/F',
    109: 'JID_SAGE_S/F',
    114: 'JID_BKNIGHT',          # Black Knight / Zelgius (boss class but promoted-tier)
}

# HP=80 list (overrides default HP-unchanged):
HP80_INDICES = {
    1,   # JID_HERO (Lord/Hero)
    2,   # JID_HERO_G (treat as Hero variant)
    16,  # JID_GENERAL
    74,  # JID_BERSERKER
    40,  # JID_DRAGONMASTER (Haar)
    41,  # JID_DRAGONMASTER/F (Jill)
}

# Valkyrie/Queen exception (all 7 stats except Lck = 60)
EXCEPTION_60 = {
    37: 'JID_FALCONKNIGHT_E/F',  # Queen (Elincia)
    69: 'JID_VALKYRIE/F',        # Valkyrie (Mist)
}

# --- Laguz transformed forms (= "promoted" Laguz) ---
# Apply same +10 main / Lck=80 rule. Untransformed (BEAST_L, BIRD_*, DRAGON_*) are bases.
PROMOTED_LAGUZ = {
    88: 'JID_LION',
    89: 'JID_TIGER',
    90: 'JID_CAT',
    91: 'JID_CAT/F',
    92: 'JID_BLACKDRAGON',
    93: 'JID_WHITEDRAGON',
    94: 'JID_REDDRAGON',
    95: 'JID_REDDRAGON/F',
    96: 'JID_HAWK',
    97: 'JID_CROW',
    98: 'JID_HERON',
    99: 'JID_HERON_W',
    100: 'JID_HERON_W/F',
    111: 'JID_HAWK_TIB',          # Tibarn
    113: 'JID_CROW_NES',          # Naesala
}

# --- Indices to NEVER touch ---
# Base classes, non-combat templates, Ashnard boss
SKIP_INDICES = set(range(115)) - set(PROMOTED_HUMAN) - set(EXCEPTION_60) - set(PROMOTED_LAGUZ)
# Explicitly:
#   Base: 0,3,4,7,8,11,13,15, 17-24, 35,38,39, 43-50, 65,68,70,73
#   Untransformed Laguz: 75-87, 110, 112
#   Non-combat templates: 101-104, 107
#   Ashnard: 42

# --- Patch derivation function ---
def derive_new_caps(idx, current_caps):
    """Return new 8-byte caps tuple (HP, Str, Mag, Skl, Spd, Lck, Def, Res),
       or None to skip this entry."""
    HP, ST, MA, SK, SP, LK, DF, RS = current_caps
    if idx in SKIP_INDICES:
        return None
    if idx in EXCEPTION_60:
        return (60, 60, 60, 60, 60, 80, 60, 60)
    # Promoted (human or laguz)
    new_HP = 80 if idx in HP80_INDICES else HP
    new_ST = ST + 10
    new_MA = MA + 10
    new_SK = SK + 10
    new_SP = SP + 10
    new_LK = 80
    new_DF = DF + 10
    new_RS = RS + 10
    # Cap to byte
    def b(x): return min(255, max(0, x))
    return (b(new_HP), b(new_ST), b(new_MA), b(new_SK), b(new_SP), b(new_LK), b(new_DF), b(new_RS))
