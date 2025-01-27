#  SPDX-FileCopyrightText: 2024 Thomas Bechtold <thomasbechtold@jpberlin.de>
#  SPDX-License-Identifier: GPL-3.0-or-later

from unittest.mock import patch, ANY
import pathlib
import pytest

from chimg import chroot
from chimg import context
from chimg.config import ConfigFile  # Add import for ConfigFile


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


@patch("os.path.isdir")
@patch("os.makedirs")
@patch("shutil.copy2")
@patch("shutil.copytree")
@patch("os.chown")
@patch("os.chmod")
def test__file_install_from_path_file(
    mock_chmod,
    mock_chown,
    mock_copytree,
    mock_copy2,
    mock_makedirs,
    mock_isdir,
    chroot_dir,
):
    """
    test _file_install_from_path() method with a file
    """
    mock_isdir.return_value = False

    ctx = context.Context(conf_path=curdir / "fixtures/config1.yaml", chroot_path=chroot_dir)
    cr = chroot.Chroot(ctx)

    file_config = ConfigFile(
        source="/path/to/source/file.txt", destination="/path/to/dest/file.txt", owner="1000", group="1000", mode=644
    )

    cr._file_install_from_path(file_config)

    mock_isdir.assert_called_with(file_config.source)
    mock_copy2.assert_called_with(file_config.source, f"{chroot_dir}/{file_config.destination}")
    mock_chown.assert_any_call(f"{chroot_dir}/{file_config.destination}", int(file_config.owner), -1)
    mock_chown.assert_any_call(f"{chroot_dir}/{file_config.destination}", -1, int(file_config.group))
    mock_chmod.assert_called_with(f"{chroot_dir}/{file_config.destination}", file_config.mode)
    mock_copytree.assert_not_called()


@patch("os.path.isdir")
@patch("os.makedirs")
@patch("shutil.copy2")
@patch("shutil.copytree")
@patch("os.chown")
@patch("os.chmod")
def test__file_install_from_path_directory(
    mock_chmod,
    mock_chown,
    mock_copytree,
    mock_copy2,
    mock_makedirs,
    mock_isdir,
    chroot_dir,
):
    """
    test _file_install_from_path() method with a directory
    """
    # Configure isdir to return True for the source and False for the destination
    # to ensure makedirs is called
    mock_isdir.side_effect = lambda path: path == "/path/to/source/dir"

    ctx = context.Context(conf_path=curdir / "fixtures/config1.yaml", chroot_path=chroot_dir)
    cr = chroot.Chroot(ctx)

    dir_config = ConfigFile(
        source="/path/to/source/dir", destination="/path/to/dest/dir", owner="1000", group="1000", mode=755
    )

    cr._file_install_from_path(dir_config)

    # Verify isdir was called with the source path
    mock_isdir.assert_any_call(dir_config.source)
    # Verify isdir was called with the destination path
    mock_isdir.assert_any_call(f"{chroot_dir}/{dir_config.destination}")
    # Verify makedirs was called to create the destination directory
    mock_makedirs.assert_called_with(f"{chroot_dir}/{dir_config.destination}", exist_ok=True)
    mock_copytree.assert_called_with(dir_config.source, f"{chroot_dir}/{dir_config.destination}", dirs_exist_ok=True)
    mock_chown.assert_any_call(f"{chroot_dir}/{dir_config.destination}", int(dir_config.owner), -1)
    mock_chown.assert_any_call(f"{chroot_dir}/{dir_config.destination}", -1, int(dir_config.group))
    mock_chmod.assert_called_with(f"{chroot_dir}/{dir_config.destination}", dir_config.mode)
    mock_copy2.assert_not_called()


@patch("os.path.isdir")
@patch("shutil.copy2")
@patch("shutil.copytree")
def test__file_install_from_path_minimal(
    mock_copytree,
    mock_copy2,
    mock_isdir,
    chroot_dir,
):
    """
    test _file_install_from_path() method with minimal config (no owner/group/mode)
    """
    mock_isdir.return_value = False

    ctx = context.Context(conf_path=curdir / "fixtures/config1.yaml", chroot_path=chroot_dir)
    cr = chroot.Chroot(ctx)

    file_config = ConfigFile(source="/path/to/source/file.txt", destination="/path/to/dest/file.txt")

    cr._file_install_from_path(file_config)

    mock_isdir.assert_called_with(file_config.source)
    mock_copy2.assert_called_with(file_config.source, f"{chroot_dir}/{file_config.destination}")
    mock_copytree.assert_not_called()
