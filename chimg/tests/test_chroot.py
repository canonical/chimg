#  SPDX-FileCopyrightText: 2024 Thomas Bechtold <thomasbechtold@jpberlin.de>
#  SPDX-License-Identifier: GPL-3.0-or-later

from unittest.mock import patch, ANY
import pathlib
import pytest

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


@pytest.mark.parametrize(
    "deb",
    [
        {"name": "emacs"},
        {"name": "emacs", "hold": True},
    ],
)
@patch("chimg.common.subprocess.run")
def test__deb_install(mock_subprocess, chroot_dir, deb):
    """
    test _deb_install() method
    """
    mock_subprocess.return_value.returncode = 0
    ctx = context.Context(conf_path=curdir / "fixtures/config1.yaml", chroot_path=chroot_dir)
    cr = chroot.Chroot(ctx)
    cr._deb_install(deb)
    mock_subprocess.assert_any_call(
        [
            "/usr/sbin/chroot",
            chroot_dir.as_posix(),
            "apt-get",
            "install",
            "--assume-yes",
            "--allow-downgrades",
            deb["name"],
        ],
        cwd=None,
        env={"DEBIAN_FRONTEND": "noninteractive"},
        capture_output=True,
        shell=False,
    )
    if deb.get("hold", False):
        mock_subprocess.assert_any_call(
            ["/usr/sbin/chroot", chroot_dir.as_posix(), "apt-mark", "hold", deb["name"]],
            cwd=None,
            env={"DEBIAN_FRONTEND": "noninteractive"},
            capture_output=True,
            shell=False,
        )
        assert mock_subprocess.call_count == 2
    else:
        assert mock_subprocess.call_count == 1


@pytest.mark.parametrize(
    "snap",
    [
        {"name": "hello", "channel": "latest/stable", "classic": False, "revision": None},
        {"name": "chimg", "channel": "latest/edge", "classic": True, "revision": None},
    ],
)
def test__snap_install(chroot_dir, snap):
    """
    test _snap_install() method
    """
    ctx = context.Context(conf_path=curdir / "fixtures/config1.yaml", chroot_path=chroot_dir)
    cr = chroot.Chroot(ctx)
    snap_info = cr._snap_install(snap["name"], snap["channel"], snap["classic"], snap["revision"])

    assert pathlib.Path(f"{chroot_dir}/var/lib/snapd/seed/snaps/{snap_info.filename}").exists()
    assert snap_info.info["name"] == snap["name"]
    if snap["classic"] is True:
        assert snap_info.info["notes"]["confinement"] == "classic"
