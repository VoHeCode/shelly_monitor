# config.py – Generic configuration handler.

import os
import configparser
from pathlib import Path


class AppConfig:
    """Manages persistent app settings via a .ini file.

    The config file is stored in the directory provided by the
    FLET_APP_STORAGE_DATA environment variable (set by flet on all
    platforms including Android). Falls back to ~/FletAppData/shelly_energie
    when running without the flet runner.
    """

    def __init__(self):
        # FLET_APP_STORAGE_DATA is set by flet on all platforms (including Android).
        # Fallback for development without the flet runner.
        data_storage_path = os.getenv("FLET_APP_STORAGE_DATA")
        if data_storage_path is None:
            data_storage_path = str(Path.home() / "FletAppData" / "shelly_energie")

        config_dir = Path(data_storage_path)
        config_dir.mkdir(parents=True, exist_ok=True)
        self.path = config_dir / "settings.ini"
        self.cfg  = configparser.ConfigParser()
        if self.path.exists():
            self.cfg.read(self.path)

    def get(self, section, key, default=None):
        """Return the value for *key* in *section*, or *default* if not found."""
        try:
            return self.cfg.get(section, key)
        except (configparser.NoSectionError, configparser.NoOptionError):
            return default

    def set(self, section, key, value):
        """Persist *value* for *key* in *section* and write the file immediately."""
        if not self.cfg.has_section(section):
            self.cfg.add_section(section)
        self.cfg.set(section, key, str(value))
        with self.path.open("w") as f:
            self.cfg.write(f)