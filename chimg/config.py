#  SPDX-FileCopyrightText: 2024 Thomas Bechtold <thomasbechtold@jpberlin.de>
#  SPDX-License-Identifier: GPL-3.0-or-later

import pathlib
from typing import List, Optional
from pydantic import BaseModel, Field, model_validator


class ConfigFile(BaseModel):
    """
    A file configuration.

    This allows for easily creating files on the target system either with content or by copying a file or directory.

    If `content` is provided, the file will be created with the content provided.

    If `source` is provided and the source is a file, the file will be copied to the destination path.

    If `source` is provided and the source is a directory, all files in the directory will be copied to the
    destination path (destination will be treated as a directory).

    If `source` is a directory, the `owner`, `group`, and `mode` attributes will only be applied to the root
    destination directory. The files inside the directory will be copied with their original permissions.
    """

    destination: str = Field(description="Destination file or directory path")
    content: Optional[str] = Field(description="Content of the file being created", default=None)
    source: Optional[str] = Field(description="Source file or directory to copy into destination", default=None)
    owner: Optional[str] = Field(description="Optional file owner", default=None)
    group: Optional[str] = Field(description="Optional file group", default=None)
    mode: Optional[int] = Field(description="Optional file mode", default=None)

    @model_validator(mode="after")
    def check_content_or_source(self) -> "ConfigFile":
        """
        Check that either content or source is provided, but not both.

        Also, removes leading '/' from destination path if it exists.

        Raises:
            ValueError: If both content and source are provided, or if neither is provided.
        """
        if self.content is not None and self.source is not None:
            raise ValueError("Either 'content' or 'source' must be provided, but not both")
        if self.content is None and self.source is None:
            raise ValueError("Either 'content' or 'source' must be provided")
        # strip leading '/' from destination since chroot path already ends with '/'
        if self.destination.startswith("/"):
            self.destination = self.destination[1:]
        return self


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
    keep: bool = Field(description="Keep the PPA configured")
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
