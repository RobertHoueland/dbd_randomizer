"""Pure, GUI-independent catalog and loadout logic."""

from __future__ import annotations

import html
import random
import re
from dataclasses import dataclass, replace

ROLES = ("survivor", "killer")
POOL_KINDS = ("characters", "perks", "items", "addons")


def plain_text(value: str, tunables: dict | None = None) -> str:
    """Render upstream text safely, using the highest perk tier when tuning is available."""

    def tuning(match):
        key = match.group(1).rsplit(".", 1)[-1].casefold()
        values = (tunables or {}).get(key)
        if isinstance(values, list) and values and isinstance(values[-1], (int, float)):
            return str(values[-1])
        # Don't invent a number when upstream tuning is missing or has an unknown shape.
        return "[in-game value]"

    value = re.sub(r"\{Tunable\.([^}]+)\}", tuning, value)
    value = re.sub(r"\{Input\.ActivatableButton([12])\}", r"Active Ability Button \1", value)
    value = value.replace("{Input.UseItem}", "Use Item")
    value = re.sub(r"<(?:br\s*/?|/li|/p)>", "\n", value, flags=re.I)
    value = re.sub(r"<li>", "• ", value, flags=re.I)
    value = re.sub(r"<[^>]+>", "", value)
    value = re.sub(r"\{Keyword\.([^}]+)\}", r"\1", value)
    value = re.sub(r"\{[^}]+\}", "[in-game value]", value)
    return html.unescape(value).strip()


@dataclass(frozen=True)
class Entry:
    id: str
    name: str
    role: str
    description: str = ""
    item_type: str = ""
    parents: tuple[str, ...] = ()
    power: str = ""
    event: str = ""


@dataclass(frozen=True)
class Catalog:
    characters: tuple[Entry, ...]
    perks: tuple[Entry, ...]
    items: tuple[Entry, ...] = ()
    addons: tuple[Entry, ...] = ()

    @classmethod
    def from_payload(cls, payload: dict) -> Catalog:
        groups = []
        for kind in POOL_KINDS:
            raw = payload.get(kind, {} if kind in ("items", "addons") else None)
            if not isinstance(raw, dict):
                raise ValueError(f"Invalid {kind} response: expected an object.")
            entries = []
            for key, item in raw.items():
                if not isinstance(item, dict):
                    raise ValueError(f"Invalid {kind} entry.")
                # Only equipment that can be brought into a trial belongs in the pool.
                # Exclude killer powers, quest/perk-created items and retired add-ons.
                if kind == "items" and not (
                    item.get("type") == "item"
                    and item.get("role") == "survivor"
                    and item.get("bloodweb") == 1
                ):
                    continue
                if kind == "addons" and (
                    item.get("bloodweb") != 1
                    # Unscoped killer add-ons (Blight Serum) are event-only, not
                    # ordinary power add-ons. Never guess their compatibility.
                    or (item.get("role") == "killer" and item.get("parents") == [])
                ):
                    continue
                role, name = item.get("role"), item.get("name")
                if role not in ROLES or not isinstance(name, str) or not name.strip():
                    raise ValueError(f"Invalid {kind} name or role.")
                description = item.get("description", item.get("bio", "")) or ""
                if not isinstance(description, str):
                    raise ValueError("Invalid description.")
                tunables = item.get("tunables")
                item_type = item.get("item_type") or ""
                parents = item.get("parents", [])
                power = (item.get("item") or "") if kind == "characters" else ""
                event = item.get("event") if kind == "items" else ""
                if event is None:
                    event = ""
                if not isinstance(event, str):
                    raise ValueError("Invalid item event.")
                if not isinstance(item_type, str) or not isinstance(power, str):
                    raise ValueError("Invalid equipment type or character power.")
                if not isinstance(parents, list) or not all(
                    isinstance(parent, str) and parent for parent in parents
                ):
                    raise ValueError("Invalid add-on parents.")
                if kind == "items" and not item_type:
                    raise ValueError("Missing item type.")
                if kind == "addons" and (
                    (role == "survivor" and not item_type) or (role == "killer" and not parents)
                ):
                    raise ValueError("Missing add-on compatibility information.")
                entries.append(
                    Entry(
                        str(key),
                        name.strip(),
                        role,
                        plain_text(description, tunables if isinstance(tunables, dict) else None),
                        item_type,
                        tuple(parents),
                        power,
                        event.strip(),
                    )
                )
            for role in ROLES if kind in ("characters", "perks") else ():
                if sum(entry.role == role for entry in entries) < (4 if kind == "perks" else 1):
                    raise ValueError(f"The catalog has too few {role} {kind}.")
            groups.append(
                tuple(sorted(entries, key=lambda entry: (entry.name.casefold(), entry.id)))
            )
        return cls(*groups)

    def pool(self, kind: str, role: str, excluded: set[str] | None = None) -> tuple[Entry, ...]:
        if role not in ROLES or kind not in POOL_KINDS:
            raise ValueError("Unknown role or pool.")
        return tuple(
            e for e in getattr(self, kind) if e.role == role and e.id not in (excluded or set())
        )

    def default_exclusions(self, kind: str, role: str) -> set[str]:
        """Event items stay available for opt-in, but never enter a fresh pool."""
        return {entry.id for entry in self.pool(kind, role) if kind == "items" and entry.event}

    def compatible_addons(
        self, parent: Entry, excluded: set[str] | None = None
    ) -> tuple[Entry, ...]:
        # Killer add-ons reference power IDs, not character IDs. Survivor add-ons
        # match an item type, with an optional parent list narrowing that match.
        return tuple(
            addon
            for addon in self.pool("addons", parent.role, excluded)
            if (
                parent.power in addon.parents
                if parent.role == "killer"
                else bool(parent.item_type)
                and addon.item_type == parent.item_type
                and (not addon.parents or parent.id in addon.parents)
            )
        )


@dataclass(frozen=True)
class Loadout:
    role: str
    character: Entry
    perks: tuple[Entry, ...]
    seed: str
    item: Entry | None = None
    addons: tuple[Entry, ...] = ()
    include_equipment: bool = False

    def text(self) -> str:
        perks = "\n".join(f"  {i}. {perk.name}" for i, perk in enumerate(self.perks, 1))
        text = f"Dead by Daylight · {self.role.title()}\n{self.character.name}\n{perks}"
        if self.include_equipment:
            if self.item:
                text += f"\nItem: {self.item.name}"
            text += "\nAdd-ons: " + (", ".join(a.name for a in self.addons) or "None")
        return text


def roll(
    catalog: Catalog,
    role: str,
    seed: str,
    excluded_characters: set[str] | None = None,
    excluded_perks: set[str] | None = None,
    previous: Loadout | None = None,
    locks: frozenset[int] = frozenset(),
    *,
    include_equipment: bool = False,
    excluded_items: set[str] | None = None,
    excluded_addons: set[str] | None = None,
) -> Loadout:
    """Slots: character 0, perks 1–4, item 5, add-ons 6–7."""
    if any(slot not in range(8) for slot in locks):
        raise ValueError("Invalid lock slot.")
    if locks and (previous is None or previous.role != role):
        raise ValueError("Generate a build for this role before locking slots.")
    equipment_locks = locks & {5, 6, 7}
    if equipment_locks:
        if not include_equipment or not previous.include_equipment:
            raise ValueError("Enable equipment before locking it.")
        if 5 in locks and (role != "survivor" or previous.item is None):
            raise ValueError("There is no item to lock.")
        if any(slot - 6 >= len(previous.addons) for slot in locks if slot >= 6):
            raise ValueError("There is no add-on to lock.")
        if locks & {6, 7}:
            locks = locks | {5 if role == "survivor" else 0}
    characters = catalog.pool("characters", role, excluded_characters)
    perks = catalog.pool("perks", role, excluded_perks)
    if not characters:
        raise ValueError("Select at least one character in the selection pool.")
    if len(perks) < 4:
        raise ValueError("Select at least four perks in the selection pool.")
    locked_perks = {slot: previous.perks[slot - 1] for slot in locks if 1 <= slot <= 4}
    if any(perk not in perks for perk in locked_perks.values()):
        raise ValueError("A locked perk is excluded. Unlock it or include it in the pool.")
    if 0 in locks and previous.character not in characters:
        raise ValueError("The locked character is excluded. Unlock it or include it in the pool.")
    # Keep rolls reproducible for the same inputs without touching global RNG state.
    rng = random.Random(seed)
    character = previous.character if 0 in locks else rng.choice(characters)
    # Remove locked perks before sampling so they cannot appear again in an unlocked slot.
    available = [p for p in perks if p not in locked_perks.values()]
    selected = iter(rng.sample(available, 4 - len(locked_perks)))
    result = tuple(locked_perks[i] if i in locked_perks else next(selected) for i in range(1, 5))
    build = Loadout(role, character, result, seed)
    return with_equipment(
        catalog, build, include_equipment, excluded_items, excluded_addons, rng=rng,
        previous=previous, locks=locks,
    )


def with_equipment(
    catalog: Catalog,
    build: Loadout,
    enabled: bool,
    excluded_items: set[str] | None = None,
    excluded_addons: set[str] | None = None,
    *,
    rng: random.Random | None = None,
    previous: Loadout | None = None,
    locks: frozenset[int] = frozenset(),
) -> Loadout:
    """Change equipment without rerolling or revalidating the displayed core slots."""
    rng = rng if rng is not None else random.Random(build.seed)
    role, character = build.role, build.character
    item = None
    addons = ()
    if enabled:
        if role == "survivor":
            # None means the default pool; an explicit set is a customized pool.
            if excluded_items is None:
                excluded_items = catalog.default_exclusions("items", role)
            items = catalog.pool("items", role, excluded_items)
            if not items:
                raise ValueError(
                    "Select at least one item in the selection pool, or turn off items and add-ons."
                )
            if 5 in locks:
                if previous is None or previous.item not in items:
                    raise ValueError(
                        "The locked item is excluded. Unlock it or include it in the pool."
                    )
                item = previous.item
            else:
                item = rng.choice(items)
        elif not character.power:
            raise ValueError(
                "This killer has no power data. Refresh the roster or turn off items and add-ons."
            )
        compatible = catalog.compatible_addons(item or character, excluded_addons)
        # A sparse pool (or an item with no add-ons) is valid; don't duplicate add-ons
        # or reject the build just to fill both slots.
        locked = {slot - 6: previous.addons[slot - 6] for slot in locks if slot >= 6}
        if any(addon not in compatible for addon in locked.values()):
            raise ValueError("A locked add-on is excluded or incompatible. Unlock it first.")
        if locked and max(locked) >= len(compatible):
            raise ValueError("Include another compatible add-on or unlock the second add-on slot.")
        available = [addon for addon in compatible if addon not in locked.values()]
        selected = iter(rng.sample(available, min(2, len(compatible)) - len(locked)))
        addons = tuple(
            locked[index] if index in locked else next(selected)
            for index in range(min(2, len(compatible)))
        )
    return replace(build, item=item, addons=addons, include_equipment=enabled)
