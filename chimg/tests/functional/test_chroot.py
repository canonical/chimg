#  SPDX-FileCopyrightText: 2024 Thomas Bechtold <thomasbechtold@jpberlin.de>
#  SPDX-License-Identifier: GPL-3.0-or-later

import pathlib
import pytest

from chimg import chroot
from chimg import context


curdir = pathlib.Path(__file__).parent.resolve()


@pytest.mark.parametrize(
    "config_path",
    [
        "configs/kernel-only.yaml",
    ],
)
@pytest.mark.realchroot
def test_config(chroot_mmdebstrap_dir, config_path):
    """
    Test different configuration examples from the functional/configs directory
    """
    ctx = context.Context(conf_path=curdir / config_path, chroot_path=chroot_mmdebstrap_dir)
    cr = chroot.Chroot(ctx)
    cr.apply()
