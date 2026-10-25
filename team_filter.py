"""
Favourite / ignored team matching for Live Priority mode.

Favourites are stored by full team name (valorant.favourite_team_names) so
"Gen.G" never matches "Gen.G Academy". Anything matching an ignore pattern —
in either team name or the match's event name — never triggers LIVE mode.
"""

import re

import state
import teams

DEFAULT_IGNORED = [
    "Academy", "Game Changers", "GC", "Young",
    # Game Changers / academy rosters whose names don't say so
    "KOI Fénix", "KCORP Blue Stars", "BBL PCIFIC", "Cubert", "2Game",
    "Catnappers", "MVSK Treasure", "Exsouls Violet", "ChemicaL Violet",
    "HyperSpeed Golden", "ASIAN SUPERTEAM", "Alliance Angels", "ZER0 STRAYS",
]


def _vcfg() -> dict:
    return state.cfg.get("valorant", {})


def ignored_patterns() -> list[str]:
    patterns = _vcfg().get("ignored_teams")
    return list(DEFAULT_IGNORED) if patterns is None else [p for p in patterns if p.strip()]


def is_ignored(name: str, event: str = "") -> bool:
    """True if the team name or event name contains an ignore pattern as a whole word/phrase."""
    for pat in ignored_patterns():
        rx = re.compile(rf"(?<!\w){re.escape(pat.strip())}(?!\w)", re.IGNORECASE)
        if (name and rx.search(name)) or (event and rx.search(event)):
            return True
    return False


def favourite_names() -> list[str]:
    """Favourite full names; falls back to migrating legacy tag favourites."""
    v = _vcfg()
    if "favourite_team_names" in v:
        return [n for n in v["favourite_team_names"] if n.strip()]
    custom = state.cfg.get("team_tags", {})
    by_tag: dict[str, list[str]] = {}
    for name, tag in {**teams.TEAM_TAGS, **custom}.items():
        by_tag.setdefault(tag.upper(), []).append(name)
    names: list[str] = []
    for tag in v.get("favourite_teams", []):
        for name in by_tag.get(tag.strip().upper(), []):
            if not is_ignored(name) and name not in names:
                names.append(name)
    return names


def is_favourite_match(match: dict) -> bool:
    """Should this live match put the clock in LIVE mode (ignoring the priority toggle)?"""
    t1, t2 = match.get("team1") or "", match.get("team2") or ""
    event = match.get("match_event") or ""
    if is_ignored(t1, event) or is_ignored(t2, event):
        return False
    favourites = {n.strip().casefold() for n in favourite_names()}
    if not favourites:
        return True
    return t1.strip().casefold() in favourites or t2.strip().casefold() in favourites
