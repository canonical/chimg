#  SPDX-FileCopyrightText: 2024 Thomas Bechtold <thomasbechtold@jpberlin.de>
#  SPDX-License-Identifier: GPL-3.0-or-later

import tempfile
import pathlib
import pytest


@pytest.fixture
def chroot_dir():
    """
    Create a chroot in a temporary directory as pytest fixture
    """
    with tempfile.TemporaryDirectory(prefix="chimg-test_") as tmpdirname:
        # TODO: mock the chroot directory here
        yield pathlib.Path(tmpdirname)
