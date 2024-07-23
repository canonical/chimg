#  SPDX-FileCopyrightText: 2024 Thomas Bechtold <thomas.bechtold@canonical.com>
#  SPDX-License-Identifier: GPL-3.0-or-later

from unittest.mock import patch
import pathlib
import pytest
import os

from chimg import chroot
from chimg import context


curdir = pathlib.Path(__file__).parent.resolve()


@pytest.mark.parametrize(
    "name,uri,suites,components,key_fingerprint,signed_by,username,password,auth_lines,pin_name,pin_priority,expected_files",  # noqa: E501
    [
        # basic PPA without any features
        (
            "name",
            "uri",
            ["jammy"],
            ["main"],
            None,
            None,
            None,
            None,
            [],
            None,
            None,
            [
                {
                    "path": "etc/apt/sources.list.d/name.sources",
                    "content": """X-Repolib-Name: name
Enabled: yes
Types: deb
URIs: uri
Suites: jammy
Components: main""",
                }
            ],
        ),
        # PPA with auth_lines
        (
            "name2",
            "uri",
            ["noble"],
            ["main", "universe"],
            None,
            None,
            None,
            None,
            ["machine esm.ubuntu.com/apps/ubuntu/ login bearer password secret-password  # ubuntu-pro-client"],
            None,
            None,
            [
                {
                    "path": "etc/apt/sources.list.d/name2.sources",
                    "content": """X-Repolib-Name: name2
Enabled: yes
Types: deb
URIs: uri
Suites: noble
Components: main universe""",
                },
                {
                    "path": "etc/apt/auth.conf.d/name2.conf",
                    "content": "machine esm.ubuntu.com/apps/ubuntu/ login bearer password secret-password  # ubuntu-pro-client",  # noqa: E501
                },
            ],
        ),
        # PPA with key fingerprint
        (
            "name2",
            "uri",
            ["noble"],
            ["main", "universe"],
            "DBB1FC89762BF6B96707C4059BC0A1A1622CF918",
            None,
            None,
            None,
            [],
            None,
            None,
            [
                {
                    "path": "etc/apt/trusted.gpg.d/name2.gpg",
                },
            ],
        ),
    ],
)
@patch("chimg.chroot.Chroot._apt_update")
def test__ppa_setup(
    mock_apt_update,
    name,
    uri,
    suites,
    components,
    key_fingerprint,
    signed_by,
    username,
    password,
    auth_lines,
    pin_name,
    pin_priority,
    expected_files,
    chroot_dir,
):
    """
    test _ppa_setup() method
    """
    ctx = context.Context(conf_path=curdir / "fixtures/config1.yaml", chroot_path=chroot_dir)
    # make sure required directories exist (usually already exist in a chroot)
    os.makedirs(chroot_dir / "etc/apt/sources.list.d", exist_ok=True)
    os.makedirs(chroot_dir / "etc/apt/trusted.gpg.d", exist_ok=True)
    os.makedirs(chroot_dir / "etc/apt/auth.conf.d", exist_ok=True)
    os.makedirs(chroot_dir / "etc/apt/preferences.d", exist_ok=True)
    cr = chroot.Chroot(ctx)
    with cr._ppa_setup(
        name,
        uri,
        suites,
        components,
        key_fingerprint,
        signed_by,
        username,
        password,
        auth_lines,
        pin_name,
        pin_priority,
    ):
        for ef in expected_files:
            # the file should exist
            assert (chroot_dir / ef["path"]).exists() is True
            # the content should match
            if "content" in ef:
                assert (chroot_dir / ef["path"]).read_text() == ef["content"]
