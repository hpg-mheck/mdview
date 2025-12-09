"""Tests for the user preferences loader."""

from pathlib import Path

import pytest

from mdview.preferences import DEFAULT_PREFERENCES, PreferencesError, load_preferences


def test_load_preferences_applies_precedence(tmp_path: Path) -> None:
    system_config = tmp_path / "system.conf"
    system_config.write_text(
        """
        [ui]
        theme = light
        wrap_column = 72

        [pager]
        command = less -F
        follow_stdin = yes

        [rendering]
        normalize_newlines = false
        link_handling = footnote
        syntax_highlighting = false

        [files]
        default_paths = /etc/mdview/docs, /opt/mdview
        trust_remote = true
        """,
        encoding="utf-8",
    )

    user_config = tmp_path / "user.conf"
    user_config.write_text(
        """
        [ui]
        wrap_column = 10

        [pager]
        command = more

        [rendering]
        link_handling = strip

        [files]
        default_paths = /home/user/docs
        trust_remote = false
        """,
        encoding="utf-8",
    )

    prefs = load_preferences(
        user_config_path=user_config, system_config_path=system_config
    )

    assert prefs.theme == "light"
    assert prefs.wrap_column == 10
    assert prefs.pager_command == "more"
    assert prefs.follow_stdin is True
    assert prefs.normalize_newlines is False
    assert prefs.link_handling == "strip"
    assert prefs.syntax_highlighting is False
    assert prefs.default_paths == (Path("/home/user/docs"),)
    assert prefs.trust_remote is False


def test_preferences_default_to_built_ins_when_missing() -> None:
    prefs = load_preferences(
        user_config_path=Path("/nonexistent/user/config"),
        system_config_path=Path("/nonexistent/system/config"),
    )

    assert prefs == DEFAULT_PREFERENCES


def test_invalid_boolean_values_raise_preferences_error(tmp_path: Path) -> None:
    user_config = tmp_path / "user.conf"
    user_config.write_text(
        """
        [pager]
        follow_stdin = sometimes
        """,
        encoding="utf-8",
    )

    with pytest.raises(PreferencesError):
        load_preferences(user_config_path=user_config, system_config_path=user_config)


def test_user_config_is_created_from_stock_when_requested(tmp_path: Path) -> None:
    user_config = tmp_path / "config" / "mdview.conf"
    stock_config = Path("resources/stock-config/mdview.conf")

    prefs = load_preferences(
        user_config_path=user_config,
        system_config_path=tmp_path / "system.conf",
        create_missing_user_config=True,
        stock_config_path=stock_config,
    )

    assert user_config.exists()
    assert user_config.read_text(encoding="utf-8") == stock_config.read_text(
        encoding="utf-8"
    )
    assert (user_config.stat().st_mode & 0o777) == 0o600
    assert prefs == DEFAULT_PREFERENCES


def test_wrap_column_must_not_be_negative(tmp_path: Path) -> None:
    system_config = tmp_path / "system.conf"
    system_config.write_text(
        """
        [ui]
        wrap_column = -1
        """,
        encoding="utf-8",
    )

    with pytest.raises(PreferencesError):
        load_preferences(system_config_path=system_config)
