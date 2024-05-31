#  SPDX-FileCopyrightText: 2024 Thomas Bechtold <thomasbechtold@jpberlin.de>
#  SPDX-License-Identifier: GPL-3.0-or-later

import pathlib
import pytest

from chimg import context


curdir = pathlib.Path(__file__).parent.resolve()


@pytest.mark.parametrize(
    "config_path",
    [
        "fixtures/config1.yaml",
    ],
)
def test_context_create(chroot_dir, config_path):
    """
    Create a Context object from a given configuration file
    """
    ctx = context.Context(curdir / config_path, chroot_dir)
    assert ctx._conf_path == curdir / config_path
    assert ctx._chroot_path == chroot_dir
    assert ctx.chroot_path == chroot_dir.as_posix()
