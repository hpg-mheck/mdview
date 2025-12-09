"""User preferences loader for mdview."""

import configparser
import os
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Mapping, Optional, Tuple


class PreferencesError(Exception):
    """Raised when user preferences cannot be loaded or parsed."""


@dataclass(frozen=True)
class Preferences:
    """Container for mdview user preferences."""

    theme: str = "auto"
    wrap_column: int = 0
    pager_command: str = ""
    follow_stdin: bool = False
    normalize_newlines: bool = True
    link_handling: str = "inline"
    syntax_highlighting: bool = True
    default_paths: Tuple[Path, ...] = ()
    trust_remote: bool = False


DEFAULT_PREFERENCES = Preferences()

_DEFAULT_USER_RELATIVE = Path("mdview") / "mdview.conf"
_DEFAULT_SYSTEM_CONFIG = Path("/etc/mdview/mdview.conf")
_VALID_LINK_HANDLING = {"inline", "footnote", "strip"}


def resolve_config_paths(
    *,
    environ: Optional[Mapping[str, str]] = None,
    user_config_path: Optional[Path] = None,
    system_config_path: Optional[Path] = None,
) -> Tuple[Path, Path]:
    """Resolve user and system configuration paths.

    Args:
        environ: Environment mapping used to resolve ``XDG_CONFIG_HOME``.
        user_config_path: Optional override for the user configuration path.
        system_config_path: Optional override for the system configuration
            path.

    Returns:
        Tuple containing the user and system configuration paths in that
        order.
    """

    environment = os.environ if environ is None else environ
    user_path = user_config_path
    if user_path is None:
        base = environment.get("XDG_CONFIG_HOME")
        config_home = Path(base) if base else Path.home() / ".config"
        user_path = config_home / _DEFAULT_USER_RELATIVE

    system_path = system_config_path if system_config_path else _DEFAULT_SYSTEM_CONFIG
    return Path(user_path), Path(system_path)


def load_preferences(
    *,
    environ: Optional[Mapping[str, str]] = None,
    user_config_path: Optional[Path] = None,
    system_config_path: Optional[Path] = None,
    create_missing_user_config: bool = False,
    stock_config_path: Optional[Path] = None,
) -> Preferences:
    """Load preferences from the system and user configuration files.

    Args:
        environ: Environment mapping used to resolve ``XDG_CONFIG_HOME``.
        user_config_path: Optional override for the user configuration path.
        system_config_path: Optional override for the system configuration
            path.
        create_missing_user_config: When ``True``, create the user
            configuration file from the stock skeleton when it is missing.
        stock_config_path: Optional override for the stock configuration used
            during user configuration creation.

    Returns:
        A populated :class:`Preferences` instance.

    Raises:
        PreferencesError: If configuration files cannot be read, parsed, or
            created.
    """

    user_path, system_path = resolve_config_paths(
        environ=environ,
        user_config_path=user_config_path,
        system_config_path=system_config_path,
    )

    if create_missing_user_config:
        _ensure_user_config(user_path, stock_config_path=stock_config_path)

    config = configparser.ConfigParser(interpolation=None)
    config.optionxform = str.lower

    _read_config_file(config, system_path)
    _read_config_file(config, user_path)

    return _build_preferences(config, DEFAULT_PREFERENCES)


def _read_config_file(parser: configparser.ConfigParser, path: Path) -> None:
    if not path.exists():
        return

    if not path.is_file():
        raise PreferencesError(f"Preferences path is not a file: '{path}'")

    try:
        with path.open("r", encoding="utf-8") as handle:
            parser.read_file(handle)
    except (OSError, configparser.Error) as error:
        raise PreferencesError(
            f"Failed to read preferences file '{path}': {error}"
        ) from error


def _build_preferences(
    parser: configparser.ConfigParser, defaults: Preferences
) -> Preferences:
    prefs = defaults

    prefs = _merge_ui_section(parser, prefs)
    prefs = _merge_pager_section(parser, prefs)
    prefs = _merge_rendering_section(parser, prefs)
    prefs = _merge_files_section(parser, prefs)

    return prefs


def _merge_ui_section(
    parser: configparser.ConfigParser, prefs: Preferences
) -> Preferences:
    if parser.has_option("ui", "theme"):
        prefs = replace(prefs, theme=parser.get("ui", "theme").strip())

    if parser.has_option("ui", "wrap_column"):
        raw_value = parser.get("ui", "wrap_column")
        try:
            wrap_column = int(raw_value)
        except ValueError as error:
            raise PreferencesError("wrap_column must be an integer") from error
        if wrap_column < 0:
            raise PreferencesError("wrap_column cannot be negative")
        prefs = replace(prefs, wrap_column=wrap_column)

    return prefs


def _merge_pager_section(
    parser: configparser.ConfigParser, prefs: Preferences
) -> Preferences:
    if parser.has_option("pager", "command"):
        prefs = replace(prefs, pager_command=parser.get("pager", "command").strip())

    if parser.has_option("pager", "follow_stdin"):
        prefs = replace(
            prefs,
            follow_stdin=_parse_bool(parser.get("pager", "follow_stdin")),
        )

    return prefs


def _merge_rendering_section(
    parser: configparser.ConfigParser, prefs: Preferences
) -> Preferences:
    if parser.has_option("rendering", "normalize_newlines"):
        prefs = replace(
            prefs,
            normalize_newlines=_parse_bool(
                parser.get("rendering", "normalize_newlines")
            ),
        )

    if parser.has_option("rendering", "link_handling"):
        link_handling = parser.get("rendering", "link_handling").strip().lower()
        if link_handling not in _VALID_LINK_HANDLING:
            raise PreferencesError(
                "link_handling must be one of inline, footnote, or strip"
            )
        prefs = replace(prefs, link_handling=link_handling)

    if parser.has_option("rendering", "syntax_highlighting"):
        prefs = replace(
            prefs,
            syntax_highlighting=_parse_bool(
                parser.get("rendering", "syntax_highlighting")
            ),
        )

    return prefs


def _merge_files_section(
    parser: configparser.ConfigParser, prefs: Preferences
) -> Preferences:
    if parser.has_option("files", "default_paths"):
        raw_value = parser.get("files", "default_paths")
        parsed_paths = _parse_default_paths(raw_value)
        prefs = replace(prefs, default_paths=parsed_paths)

    if parser.has_option("files", "trust_remote"):
        prefs = replace(
            prefs, trust_remote=_parse_bool(parser.get("files", "trust_remote"))
        )

    return prefs


def _parse_bool(raw_value: str) -> bool:
    normalized = raw_value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise PreferencesError("Boolean options must be true/false, yes/no, or on/off")


def _parse_default_paths(raw_value: str) -> Tuple[Path, ...]:
    paths = [entry.strip() for entry in raw_value.split(",")]
    return tuple(Path(entry) for entry in paths if entry)


def _ensure_user_config(
    user_config_path: Path, *, stock_config_path: Optional[Path] = None
) -> None:
    if user_config_path.exists():
        if user_config_path.is_file():
            return
        raise PreferencesError(
            f"User preferences path exists and is not a file: '{user_config_path}'"
        )

    stock_path = stock_config_path or _default_stock_config_path()
    if not stock_path.exists():
        raise PreferencesError(f"Stock preferences file not found at '{stock_path}'")

    try:
        user_config_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    except OSError as error:
        raise PreferencesError(
            f"Failed to prepare user preferences directory '{user_config_path.parent}':"
            f" {error}"
        ) from error

    stock_contents = _read_stock_contents(stock_path)

    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        file_descriptor = os.open(str(user_config_path), flags, 0o600)
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as handle:
            handle.write(stock_contents)
        os.chmod(user_config_path, 0o600)
    except FileExistsError:
        return
    except OSError as error:
        raise PreferencesError(
            f"Failed to create user preferences file '{user_config_path}': {error}"
        ) from error


def _default_stock_config_path() -> Path:
    project_root = Path(__file__).resolve().parents[2]
    return project_root / "resources" / "stock-config" / "mdview.conf"


def _read_stock_contents(stock_path: Path) -> str:
    try:
        return stock_path.read_text(encoding="utf-8")
    except OSError as error:
        raise PreferencesError(
            f"Failed to read stock preferences file '{stock_path}': {error}"
        ) from error


__all__ = [
    "DEFAULT_PREFERENCES",
    "Preferences",
    "PreferencesError",
    "load_preferences",
    "resolve_config_paths",
]
