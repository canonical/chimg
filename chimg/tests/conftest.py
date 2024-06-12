#  SPDX-FileCopyrightText: 2024 Thomas Bechtold <thomasbechtold@jpberlin.de>
#  SPDX-License-Identifier: GPL-3.0-or-later

import tempfile
import pathlib
import pytest
import subprocess


@pytest.fixture
def chroot_dir():
    """
    Create a chroot in a temporary directory as pytest fixture
    """
    with tempfile.TemporaryDirectory(prefix="chimg-test_") as tmpdirname:
        # TODO: mock the chroot directory here
        yield pathlib.Path(tmpdirname)


@pytest.fixture(scope="module")
def chroot_mmdebstrap_dir():
    """
    Create a chroot using mmdebstrap in a temporary directory as pytest fixture
    This fixture will be reused for test functions within the same module
    See https://docs.pytest.org/en/6.2.x/fixture.html#scope-sharing-fixtures-across-classes-modules-packages-or-session
    """
    with tempfile.TemporaryDirectory(prefix="chimg-test_") as tmpdirname:
        # use mmbootstrap to setup the root directory
        # TODO: make suite configurable
        # TODO: drop hardcoded apt proxy
        subprocess.check_call(
            [
                "mmdebstrap",
                # "--aptopt",
                # "'Acquire::http { Proxy \"http://127.0.0.1:3142\"; }'",
                "--variant",
                "apt",
                "--include",
                # gpg for PPAs, squashfs-tools for snap preseeding
                "gpg,squashfs-tools,snapd",
                "noble",
                tmpdirname,
            ]
        )
        yield pathlib.Path(tmpdirname)
