#  SPDX-FileCopyrightText: 2024 Thomas Bechtold <thomasbechtold@jpberlin.de>
#  SPDX-License-Identifier: GPL-3.0-or-later

from typing import List, Optional
from pydantic import BaseModel, Field


class ConfigFile(BaseModel):
    """
    A file configuration
    """

    destination: str
    content: str
    owner: Optional[str] = Field(description="Optional file owner", default=None)
    group: Optional[str] = Field(description="Optional file group", default=None)
    mode: Optional[int] = Field(description="Optional file mode", default=None)


class ConfigSnap(BaseModel):
    """
    General snap configuration required for preseeding
    """

    assertion_brand: str
    assertion_model: str
    # the apparmor features directory (must match the installed kernel to make preseeding work)
    aa_features_path: Optional[str]


class ConfigSnapPackage(BaseModel):
    """
    A snap package configuration
    """

    name: str
    channel: str
    classic: bool = False
    revision: Optional[str] = None


class ConfigDebPackage(BaseModel):
    """
    A deb package configuration
    """

    name: str
    hold: Optional[bool] = Field(description="Optional hold the package", default=False)


class ConfigPPA(BaseModel):
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


class ConfigFilesystem(BaseModel):
    root_fs_label: str


class ConfigCommand(BaseModel):
    cmd: str


class Config(BaseModel):
    """
    The base configuration
    """

    kernel: str
    snap_config: ConfigSnap
    fs: ConfigFilesystem
    ppas: Optional[List[ConfigPPA]] = Field(description="Optional list of PPAs", default=[])
    debs: Optional[List[ConfigDebPackage]] = Field(description="Optional list of debs", default=[])
    snaps: Optional[List[ConfigSnapPackage]] = Field(description="Optional list of snaps", default=[])
    files: Optional[List[ConfigFile]] = Field(description="Optional list of files", default=[])
    cmds_pre: Optional[List[ConfigCommand]] = Field(description="Optional list of pre commands", default=[])
    cmds_post: Optional[List[ConfigCommand]] = Field(description="Optional list of post commands", default=[])
