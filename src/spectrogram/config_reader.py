import json
import tomllib
from pathlib import Path
from pprint import pprint as pp
from importlib.metadata import PackageNotFoundError, version

_PROFILE_NAME = ""
_CONFIG_FILE = ""
_CONFIG = {}


def get_application_version(package_name: str, project_folder: str) -> str:
    """
    Return the application version.

    Priority:
    1. Installed package metadata (works in wheel/container installs)
    2. pyproject.toml fallback (works in local development)
    """

    try:
        return version(package_name)
    except PackageNotFoundError:
        pass

    # Fallback to using pyproject.toml
    file_path = Path(project_folder) / "pyproject.toml"
    if file_path.exists():
        with file_path.resolve().open("rb") as f:
            data = tomllib.load(f)
        return data["project"]["version"]

    return "0+unknown"


def load_config(config_file: str, profile: str):
    """Load the JSON configuration file """
    global _CONFIG, _PROFILE_NAME, _CONFIG_FILE
    file_path = Path(config_file).resolve()
    _CONFIG_FILE = file_path
    with open(file_path, "r") as file:
        _PROFILE_NAME = profile
        _CONFIG = json.load(file)[_PROFILE_NAME]


def print_config():
    """Print the current configuration"""
    global _CONFIG, _PROFILE_NAME, _CONFIG_FILE
    print(f"Using profile '{_PROFILE_NAME}' from '{_CONFIG_FILE}':")
    pp(_CONFIG)


def get_property(section: str, property: str) -> str:
    """Return a property from a config section """
    global _CONFIG
    return _CONFIG[section][property]


def get_spectrogram_property(property: str) -> str:
    """Return a spectrogram property """
    return get_property("spectrogram", property)


def get_noise_detection_property(property: str) -> str:
    """Return a noise detection property """
    return get_property("noise_detection", property)


def get_spectral_noise_reduction_property(property: str) -> str:
    """Return a spectral noise reduction property """
    return get_property("spectral_noise_reduction", property)


def get_high_pass_filter_property(property: str) -> str:
    """Return a spectral noise reduction property """
    return get_property("high_pass_filter", property)


def get_normalisation_property(property: str) -> str:
    """Return a peak normalisation property """
    return get_property("normalisation", property)
