"""Pure battle logic: teams, stats, damage, round resolution. No sockets.

The server calls into a Battle object while holding game_lock, so nothing in
here does any locking or I/O. Randomness comes from an injectable
random.Random so tests can be deterministic.
"""

import random

import pokedex

LEVEL = 50
TEAM_SIZE = 3
ROUND_CAP = 50  # SOW 1.2: reaching this round with both sides alive is a DRAW
ROLES = ("player1", "player2")

STATUSES = ("OK", "PSN", "BRN", "PAR", "SLP", "FRZ", "FNT")
PAR_SKIP_CHANCE = 0.25
SLEEP_TURNS = (1, 3)


def other(role):
    return "player2" if role == "player1" else "player1"


def calc_hp(base):
    """Gen 1 HP at LEVEL with no DVs or stat exp."""
    return (base * 2 * LEVEL) // 100 + LEVEL + 10


def calc_stat(base):
    """Gen 1 non-HP stat at LEVEL with no DVs or stat exp."""
    return (base * 2 * LEVEL) // 100 + 5


class Pokemon:
    def __init__(self, species):
        types, base, moveset = pokedex.SPECIES[species]
        hp, attack, defense, special, speed = base
        self.species = species
        self.types = list(types)
        self.max_hp = calc_hp(hp)
        self.hp = self.max_hp
        self.stats = {
            "attack": calc_stat(attack),
            "defense": calc_stat(defense),
            "special": calc_stat(special),
            "speed": calc_stat(speed),
        }
        self.status = "OK"
        self.sleep_turns = 0
        self.moves = list(moveset)

    @property
    def fainted(self):
        return self.hp <= 0

    def effective_speed(self):
        speed = self.stats["speed"]
        return speed // 4 if self.status == "PAR" else speed

    def to_dict(self):
        """Full team entry (protocol_blueprint.md 3.2 Pokemon)."""
        moves = []
        for name in self.moves:
            move_type, power, accuracy = pokedex.MOVES[name]
            moves.append({"name": name, "type": move_type, "power": power,
                          "accuracy": accuracy})
        return {"species": self.species, "types": list(self.types),
                "hp": self.hp, "max_hp": self.max_hp,
                "stats": dict(self.stats), "status": self.status,
                "moves": moves}

    def summary(self):
        """Compact view (protocol_blueprint.md 3.3 ActiveSummary)."""
        return {"species": self.species, "hp": self.hp,
                "max_hp": self.max_hp, "status": self.status}


def generate_team(rng, size=TEAM_SIZE):
    """size random distinct species, each a fresh Pokemon."""
    names = rng.sample(sorted(pokedex.SPECIES), size)
    return [Pokemon(name) for name in names]


def calc_damage(attacker, defender, move_name, rng):
    """Simplified Gen 1 damage. Returns (damage, type multiplier).

    No critical hits. The physical/special split is by move type.
    """
    move_type, power, _ = pokedex.MOVES[move_name]
    multiplier = pokedex.type_multiplier(move_type, defender.types)
    if multiplier == 0:
        return 0, 0
    if move_type in pokedex.SPECIAL_TYPES:
        attack = attacker.stats["special"]
        defense = defender.stats["special"]
    else:
        attack = attacker.stats["attack"]
        defense = defender.stats["defense"]
    damage = ((2 * LEVEL // 5 + 2) * power * attack // defense) // 50 + 2
    if move_type in attacker.types:
        damage = damage * 3 // 2  # STAB 1.5x
    damage = int(damage * multiplier)
    damage = damage * rng.randint(217, 255) // 255
    return max(1, damage), multiplier


def effectiveness_text(multiplier):
    if multiplier > 1:
        return "It's super effective!"
    if 0 < multiplier < 1:
        return "It's not very effective..."
    return None


class Battle:
    """One game between player1 and player2."""

    def __init__(self, rng=None, teams=None):
        self.rng = rng or random.Random()
        if teams is None:
            teams = {role: generate_team(self.rng) for role in ROLES}
        self.teams = teams
        self.active = {role: 0 for role in ROLES}
        self.round = 1

    # ---- lookups -------------------------------------------------------

    def active_pokemon(self, role):
        return self.teams[role][self.active[role]]

    def has_move(self, role, move_name):
        return move_name in self.active_pokemon(role).moves

    def find_member(self, role, species):
        for index, mon in enumerate(self.teams[role]):
            if mon.species == species:
                return index
        return None

    def needs_switch(self, role):
        return self.active_pokemon(role).fainted

    def remaining(self):
        """Non-fainted Pokemon per side (the per-battle score)."""
        return {role: sum(1 for mon in self.teams[role] if not mon.fainted)
                for role in ROLES}

    def active_summaries(self):
        return {role: self.active_pokemon(role).summary() for role in ROLES}

    def team_summaries(self):
        return {role: [mon.summary() for mon in self.teams[role]]
                for role in ROLES}

    # ---- SWITCH --------------------------------------------------------

    def switch_error(self, role, species):
        """ERROR code for an invalid SWITCH target, or None if valid."""
        index = self.find_member(role, species)
        if index is None:
            return "INVALID_MOVE"
        if self.teams[role][index].fainted:
            return "FAINTED_POKEMON_SELECTED"
        return None

    def switch(self, role, species):
        self.active[role] = self.find_member(role, species)

    # ---- EVALUATE_ROUND ------------------------------------------------

    def turn_order(self):
        """Faster active Pokemon first; player1 wins speed ties."""
        speed1 = self.active_pokemon("player1").effective_speed()
        speed2 = self.active_pokemon("player2").effective_speed()
        if speed2 > speed1:
            return ["player2", "player1"]
        return ["player1", "player2"]

    def resolve_round(self, moves):
        """Run both locked-in moves. moves maps role -> move_name.

        Returns the ordered events list. HP can reach 0 here, but FNT is only
        marked by check_faint().
        """
        events = []
        for role in self.turn_order():
            attacker = self.active_pokemon(role)
            defender = self.active_pokemon(other(role))
            if attacker.fainted:
                continue  # knocked out earlier this round: move skipped
            if not self._can_act(attacker, events):
                continue
            self._use_move(attacker, defender, moves[role], events)
        return events

    def _can_act(self, mon, events):
        if mon.status == "SLP":
            mon.sleep_turns -= 1
            if mon.sleep_turns <= 0:
                mon.status = "OK"
                events.append("{} woke up!".format(mon.species))
            else:
                events.append("{} is fast asleep.".format(mon.species))
            return False
        if mon.status == "PAR" and self.rng.random() < PAR_SKIP_CHANCE:
            events.append("{} is fully paralyzed!".format(mon.species))
            return False
        return True

    def _use_move(self, attacker, defender, move_name, events):
        move_type, _, accuracy = pokedex.MOVES[move_name]
        used = "{} used {}!".format(attacker.species, move_name)
        if move_name in pokedex.STATUS_MOVES:
            self._use_status_move(attacker, defender, move_name, events)
            return
        multiplier = pokedex.type_multiplier(move_type, defender.types)
        if multiplier == 0:
            events.append("{} It doesn't affect {}...".format(
                used, defender.species))
            return
        if self.rng.randint(1, 100) > accuracy:
            events.append("{} But it missed!".format(used))
            return
        damage, multiplier = calc_damage(attacker, defender, move_name,
                                         self.rng)
        damage = min(damage, defender.hp)
        defender.hp -= damage
        events.append("{} {} lost {} HP.".format(used, defender.species,
                                                 damage))
        text = effectiveness_text(multiplier)
        if text:
            events.append(text)

    def _use_status_move(self, attacker, defender, move_name, events):
        _, _, accuracy = pokedex.MOVES[move_name]
        status = pokedex.STATUS_MOVES[move_name]
        used = "{} used {}!".format(attacker.species, move_name)
        if move_name == "Thunder Wave" and "Ground" in defender.types:
            events.append("{} It doesn't affect {}...".format(
                used, defender.species))
            return
        if defender.status != "OK":
            events.append("{} But it failed!".format(used))
            return
        if self.rng.randint(1, 100) > accuracy:
            events.append("{} But it missed!".format(used))
            return
        defender.status = status
        if status == "SLP":
            defender.sleep_turns = self.rng.randint(*SLEEP_TURNS)
            events.append("{} {} fell asleep!".format(used, defender.species))
        else:
            events.append("{} {} is paralyzed! It may be unable to move!"
                          .format(used, defender.species))

    # ---- CHECK_FAINT / CHECK_WIN_DRAW ----------------------------------

    def check_faint(self, events):
        """Mark fainted actives FNT. Returns the roles whose active fainted."""
        fainted = []
        for role in ROLES:
            mon = self.active_pokemon(role)
            if mon.fainted and mon.status != "FNT":
                mon.status = "FNT"
                mon.sleep_turns = 0
                events.append("{} fainted!".format(mon.species))
            if mon.fainted:
                fainted.append(role)
        return fainted

    def outcome(self):
        """(result, winner) if the game is decided, else None.

        Called after a round resolves, before the round counter advances.
        """
        remaining = self.remaining()
        out1 = remaining["player1"] == 0
        out2 = remaining["player2"] == 0
        if out1 and out2:
            return "DRAW", None
        if out1:
            return "WIN", "player2"
        if out2:
            return "WIN", "player1"
        if self.round >= ROUND_CAP:
            return "DRAW", None
        return None
