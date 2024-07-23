#  SPDX-FileCopyrightText: 2024 Thomas Bechtold <thomasbechtold@jpberlin.de>
#  SPDX-License-Identifier: GPL-3.0-or-later

import pathlib
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


class ConfigSnapPackage(BaseModel):
    """
    A snap package configuration
    """

    name: str
    channel: str
    classic: bool = False
    revision: Optional[str] = None


class ConfigSnap(BaseModel):
    """
    General snap configuration required for preseeding
    """

    assertion_brand: str
    assertion_model: str
    # the apparmor features directory (must match the installed kernel to make preseeding work)
    aa_features_path: Optional[str]
    snaps: List[ConfigSnapPackage]


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
    fingerprint: Optional[str] = Field(description="Optional PPA fingerprint (key will be downloaded)", default=None)
    signed_by: Optional[pathlib.Path] = Field(description="Optional path to a key file", default=None)
    username: Optional[str] = Field(description="Optional PPA username", default=None)
    password: Optional[str] = Field(description="Optional PPA password", default=None)
    auth_lines: Optional[List[str]] = Field(description="Optional list of APT auth.conf.d/ file lines", default=[])
    pin_name: Optional[str] = Field(description="Optional PPA Pin name", default=None)
    pin_priority: Optional[int] = Field(description="Optional PPA Pin priority", default=None)


class ConfigFilesystem(BaseModel):
    root_fs_label: str


class ConfigCommand(BaseModel):
    cmd: str


class Config(BaseModel):
    """
    The base configuration
    """

    kernel: Optional[str] = Field(description="Optional kernel deb package name", default=None)
    fs: Optional[ConfigFilesystem] = Field(description="Optional filesystem options", default=None)
    ppas: Optional[List[ConfigPPA]] = Field(description="Optional list of PPAs", default=[])
    debs: Optional[List[ConfigDebPackage]] = Field(description="Optional list of debs", default=[])
    snap: Optional[ConfigSnap] = Field(description="Optional snap configuration and preseeded snaps", default=None)
    files: Optional[List[ConfigFile]] = Field(description="Optional list of files", default=[])
    cmds_pre: Optional[List[ConfigCommand]] = Field(description="Optional list of pre commands", default=[])
    cmds_post: Optional[List[ConfigCommand]] = Field(description="Optional list of post commands", default=[])
