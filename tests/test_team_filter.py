import team_filter as tf


def m(t1, t2, event=""):
    return {"team1": t1, "team2": t2, "match_event": event}


def test_default_ignore_patterns(cfg):
    for name in ["Gen.G Academy", "Gen.G Global Academy", "ROSO GC", "EDward Gaming Young",
                 "Cubert Game Changers"]:
        assert tf.is_ignored(name), name
    for name in ["Gen.G", "Paper Rex", "Gucci Crew"]:
        assert not tf.is_ignored(name), name


def test_ignore_matches_whole_words_only(cfg):
    assert not tf.is_ignored("Youngblood")         # 'Young' only as a whole word
    assert tf.is_ignored("Team Young")


def test_event_name_can_ignore_match(cfg):
    assert tf.is_ignored("Gen.G", "VCT 2026: Game Changers Championship")
    assert not tf.is_ignored("Gen.G", "VCT 2026: Pacific Stage 2")


def test_configured_ignore_list_replaces_defaults(cfg):
    cfg["valorant"] = {"ignored_teams": ["Violet"]}
    assert tf.is_ignored("Exsouls Violet")
    assert not tf.is_ignored("Gen.G Academy")


def test_favourite_by_full_name_not_tag(cfg):
    cfg["valorant"] = {"favourite_team_names": ["Gen.G"]}
    assert tf.is_favourite_match(m("Gen.G", "Paper Rex"))
    assert tf.is_favourite_match(m("paper rex", "gen.g"))
    assert not tf.is_favourite_match(m("Gen.G Global Academy", "Team Liquid Academy"))
    assert not tf.is_favourite_match(m("Sentinels", "Paper Rex"))


def test_ignored_opponent_blocks_even_favourite(cfg):
    cfg["valorant"] = {"favourite_team_names": ["Gen.G"]}
    assert not tf.is_favourite_match(m("Gen.G", "Gen.G Academy"))
    assert not tf.is_favourite_match(m("Gen.G", "Paper Rex", "Game Changers Championship"))


def test_empty_favourites_means_all_non_ignored(cfg):
    cfg["valorant"] = {"favourite_team_names": []}
    assert tf.is_favourite_match(m("Sentinels", "Paper Rex"))
    assert not tf.is_favourite_match(m("Sentinels Academy", "Paper Rex"))


def test_legacy_tags_migrate_to_names_without_academy_collisions(cfg):
    cfg["valorant"] = {"favourite_teams": ["GEN", "T1", "GE", "TL", "NOPE"]}
    names = tf.favourite_names()
    assert set(names) == {"Gen.G", "T1", "Global Esports", "Team Liquid"}
    assert tf.is_favourite_match(m("Gen.G", "Paper Rex"))
    assert not tf.is_favourite_match(m("Gen.G Academy", "T1 Academy"))


def test_legacy_migration_ignored_once_names_key_exists(cfg):
    cfg["valorant"] = {"favourite_teams": ["GEN"], "favourite_team_names": ["Fnatic"]}
    assert tf.favourite_names() == ["Fnatic"]
