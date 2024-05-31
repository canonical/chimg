#  SPDX-FileCopyrightText: 2024 Thomas Bechtold <thomasbechtold@jpberlin.de>
#  SPDX-License-Identifier: GPL-3.0-or-later

from unittest.mock import patch, ANY
import pathlib

from chimg import chroot
from chimg import context


curdir = pathlib.Path(__file__).parent.resolve()


@patch("chimg.common.subprocess.run")
def test__cmd_run(mock_subprocess, chroot_dir):
    """
    test _cmd_run() method
    """
    mock_subprocess.return_value.returncode = 0
    mock_subprocess.return_value.stdout = b"stdout"
    mock_subprocess.return_value.stderr = b"stderr"

    ctx = context.Context(conf_path=curdir / "fixtures/config1.yaml", chroot_path=chroot_dir)
    cr = chroot.Chroot(ctx)

    stdout, stderr = cr._cmd_run("ls")
    assert stdout == "stdout"
    mock_subprocess.assert_called_once_with(
        ["/usr/sbin/chroot", chroot_dir.as_posix(), ANY], cwd=None, env=None, capture_output=True, shell=False
    )
