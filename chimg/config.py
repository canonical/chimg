#  SPDX-FileCopyrightText: 2024 Thomas Bechtold <thomasbechtold@jpberlin.de>
#  SPDX-License-Identifier: GPL-3.0-or-later

from typing import List, Optional
from dataclasses import dataclass, field


@dataclass
class ConfigFile:
    """
    A file configuration
    """

    destination: str
    owner: Optional[str]
    group: Optional[str]
    mode: Optional[int]


@dataclass
class ConfigSnap:
    """
    General snap configuration required for preseeding
    """

    assertion_brand: str
    assertion_model: str
    # the apparmor features directory (must match the installed kernel to make preseeding work)
    aa_features_path: Optional[str]


@dataclass
class ConfigSnapPackage:
    """
    A snap package configuration
    """

    name: str
    channel: str
    classic: bool = False
    revision: Optional[str] = None


@dataclass
class ConfigDebPackage:
    """
    A deb package configuration
    """

    name: str
    hold: bool = False


@dataclass
class ConfigPPA:
    """
    A PPA configuration
    """

    name: str
    uri: str
    suites: List[str]
    components: List[str]
    fingerprint: str
    username: Optional[str]
    password: Optional[str]
    pin_name: Optional[str]
    pin_priority: Optional[int]


@dataclass
class ConfigFilesystem:
    root_fs_label: str


@dataclass
class ConfigCommand:
    cmd: str


@dataclass
class Config:
    """
    The base configuration
    """

    kernel: str
    snap_config: ConfigSnap
    fs: ConfigFilesystem
    ppas: Optional[List[ConfigPPA]] = field(default_factory=list)
    debs: Optional[List[ConfigDebPackage]] = field(default_factory=list)
    snaps: Optional[List[ConfigSnapPackage]] = field(default_factory=list)
    files: Optional[List[ConfigFile]] = field(default_factory=list)
    cmds_pre: Optional[List[ConfigCommand]] = field(default_factory=list)
    cmds_post: Optional[List[ConfigCommand]] = field(default_factory=list)
