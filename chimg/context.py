#  SPDX-FileCopyrightText: 2024 Thomas Bechtold <thomasbechtold@jpberlin.de>
#  SPDX-License-Identifier: GPL-3.0-or-later

import logging
import pathlib
import yaml
import os

from chimg.config import Config

logger = logging.getLogger(__name__)


class Context:
    """
    Context holds the used configuration and some
    automatically calculated values
    """

    def __init__(self, conf_path: pathlib.Path, chroot_path: pathlib.Path):
        self._conf_path: pathlib.Path = conf_path.resolve()
        self._chroot_path: pathlib.Path = chroot_path
        self._conf = None

        # read the config itself
        with open(self._conf_path, "r") as f:
            y = yaml.safe_load(f.read())
            self._conf = Config(**y)
            # handle relative paths in config files. those are relative to the config file dirname
            if self.conf.snap_config["aa_features_path"] and not os.path.isabs(
                self.conf.snap_config["aa_features_path"]
            ):
                self.conf.snap_config["aa_features_path"] = (
                    pathlib.Path(self._conf_path).parent / self.conf.snap_config["aa_features_path"]
                ).as_posix()
            logger.debug(f"config loaded as: {self._conf}")

    @property
    def conf(self):
        return self._conf

    @property
    def chroot_path(self) -> str:
        return self._chroot_path.as_posix()
