"""Curated Gen 1 data: species, moves, and the type chart.

Base stats are the Gen 1 (Red/Blue/Yellow) values, which have a single
Special stat. Move type, power, and accuracy are also Gen 1 values. Secondary
effects (flinch, recoil, high crit rate, side-effect status) are out of scope.
The only status moves are Thunder Wave and Hypnosis.
"""

# name: (type, power, accuracy)
MOVES = {
    "Body Slam": ("Normal", 85, 100),
    "Slash": ("Normal", 70, 100),
    "Egg Bomb": ("Normal", 100, 75),
    "Flamethrower": ("Fire", 95, 100),
    "Fire Blast": ("Fire", 120, 85),
    "Surf": ("Water", 95, 100),
    "Hydro Pump": ("Water", 120, 80),
    "Thunderbolt": ("Electric", 95, 100),
    "Thunder": ("Electric", 120, 70),
    "Thunder Wave": ("Electric", 0, 100),
    "Razor Leaf": ("Grass", 55, 95),
    "Ice Beam": ("Ice", 95, 100),
    "Blizzard": ("Ice", 120, 90),
    "Low Kick": ("Fighting", 50, 90),
    "Sludge": ("Poison", 65, 100),
    "Earthquake": ("Ground", 100, 100),
    "Drill Peck": ("Flying", 80, 100),
    "Psychic": ("Psychic", 90, 100),
    "Hypnosis": ("Psychic", 0, 60),
    "Rock Slide": ("Rock", 75, 90),
    "Lick": ("Ghost", 20, 100),
}

# Status moves and the status they inflict.
STATUS_MOVES = {
    "Thunder Wave": "PAR",
    "Hypnosis": "SLP",
}

# name: (types, (hp, attack, defense, special, speed), moveset)
SPECIES = {
    "Venusaur": (["Grass", "Poison"], (80, 82, 83, 100, 80),
                 ["Razor Leaf", "Sludge", "Body Slam"]),
    "Charizard": (["Fire", "Flying"], (78, 84, 78, 85, 100),
                  ["Flamethrower", "Slash", "Earthquake"]),
    "Blastoise": (["Water"], (79, 83, 100, 85, 78),
                  ["Surf", "Ice Beam"]),
    "Jolteon": (["Electric"], (65, 65, 60, 110, 130),
                ["Thunderbolt", "Thunder Wave"]),
    "Snorlax": (["Normal"], (160, 110, 65, 65, 30),
                ["Body Slam", "Earthquake"]),
    "Alakazam": (["Psychic"], (55, 50, 45, 135, 120),
                 ["Psychic", "Thunder Wave"]),
    "Gengar": (["Ghost", "Poison"], (60, 65, 60, 130, 110),
               ["Thunderbolt", "Hypnosis", "Lick"]),
    "Starmie": (["Water", "Psychic"], (60, 75, 85, 100, 115),
                ["Surf", "Psychic", "Thunderbolt"]),
    "Tauros": (["Normal"], (75, 100, 95, 70, 110),
               ["Body Slam", "Earthquake", "Blizzard"]),
    "Exeggutor": (["Grass", "Psychic"], (95, 95, 85, 125, 55),
                  ["Psychic", "Egg Bomb", "Hypnosis"]),
    "Chansey": (["Normal"], (250, 5, 5, 105, 50),
                ["Ice Beam", "Thunderbolt", "Thunder Wave"]),
    "Rhydon": (["Ground", "Rock"], (105, 130, 120, 45, 40),
               ["Earthquake", "Rock Slide", "Body Slam"]),
    "Lapras": (["Water", "Ice"], (130, 85, 80, 95, 60),
               ["Hydro Pump", "Blizzard", "Body Slam"]),
    "Zapdos": (["Electric", "Flying"], (90, 90, 85, 125, 100),
               ["Thunder", "Drill Peck", "Thunder Wave"]),
    "Dragonite": (["Dragon", "Flying"], (91, 134, 95, 100, 80),
                  ["Body Slam", "Blizzard", "Thunder Wave"]),
    "Machamp": (["Fighting"], (90, 130, 80, 65, 55),
                ["Low Kick", "Rock Slide", "Earthquake"]),
    "Arcanine": (["Fire"], (90, 110, 80, 80, 95),
                 ["Fire Blast", "Body Slam"]),
}

# In Gen 1 the physical/special split is by move type.
SPECIAL_TYPES = {"Fire", "Water", "Grass", "Electric", "Ice", "Psychic",
                 "Dragon"}

# Gen 1 type chart: attacking type -> {defending type: multiplier}.
# Any pair not listed is 1x. Gen 1 quirks kept on purpose:
#   - Ghost moves have no effect on Psychic (the Gen 1 bug).
#   - Ice is neutral against Fire.
#   - Bug and Poison are super effective against each other.
TYPE_CHART = {
    "Normal": {"Rock": 0.5, "Ghost": 0},
    "Fire": {"Fire": 0.5, "Water": 0.5, "Grass": 2, "Ice": 2, "Bug": 2,
             "Rock": 0.5, "Dragon": 0.5},
    "Water": {"Fire": 2, "Water": 0.5, "Grass": 0.5, "Ground": 2,
              "Rock": 2, "Dragon": 0.5},
    "Electric": {"Water": 2, "Electric": 0.5, "Grass": 0.5, "Ground": 0,
                 "Flying": 2, "Dragon": 0.5},
    "Grass": {"Fire": 0.5, "Water": 2, "Grass": 0.5, "Poison": 0.5,
              "Ground": 2, "Flying": 0.5, "Bug": 0.5, "Rock": 2,
              "Dragon": 0.5},
    "Ice": {"Water": 0.5, "Grass": 2, "Ice": 0.5, "Ground": 2, "Flying": 2,
            "Dragon": 2},
    "Fighting": {"Normal": 2, "Ice": 2, "Poison": 0.5, "Flying": 0.5,
                 "Psychic": 0.5, "Bug": 0.5, "Rock": 2, "Ghost": 0},
    "Poison": {"Grass": 2, "Poison": 0.5, "Ground": 0.5, "Bug": 2,
               "Rock": 0.5, "Ghost": 0.5},
    "Ground": {"Fire": 2, "Electric": 2, "Grass": 0.5, "Poison": 2,
               "Flying": 0, "Bug": 0.5, "Rock": 2},
    "Flying": {"Electric": 0.5, "Grass": 2, "Fighting": 2, "Bug": 2,
               "Rock": 0.5},
    "Psychic": {"Fighting": 2, "Poison": 2, "Psychic": 0.5},
    "Bug": {"Fire": 0.5, "Grass": 2, "Fighting": 0.5, "Poison": 2,
            "Flying": 0.5, "Psychic": 2, "Ghost": 0.5},
    "Rock": {"Fire": 2, "Ice": 2, "Fighting": 0.5, "Ground": 0.5,
             "Flying": 2, "Bug": 2},
    "Ghost": {"Normal": 0, "Psychic": 0, "Ghost": 2},
    "Dragon": {"Dragon": 2},
}


def type_multiplier(move_type, defender_types):
    """Combined effectiveness of a move type against one or two types."""
    multiplier = 1.0
    for defender_type in defender_types:
        multiplier *= TYPE_CHART.get(move_type, {}).get(defender_type, 1)
    return multiplier
