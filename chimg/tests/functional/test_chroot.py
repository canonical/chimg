#  SPDX-FileCopyrightText: 2024 Thomas Bechtold <thomasbechtold@jpberlin.de>
#  SPDX-License-Identifier: GPL-3.0-or-later

import os
import pathlib
import pytest
import subprocess
from functools import partial
from chimg import chroot
from chimg import context


curdir = pathlib.Path(__file__).parent.resolve()


def _check_file_exists(file_path: pathlib.Path, chroot_path: pathlib.Path):
    """
    check that a given file exists
    """
    assert os.path.exists(chroot_path / file_path)


def _check_file_not_exists(file_path: pathlib.Path, chroot_path: pathlib.Path):
    """
    check that a given file does not exists
    """
    assert not os.path.exists(chroot_path / file_path)


def _check_deb_installed(deb_name: str, deb_hold: bool, chroot_path: pathlib.Path):
    """
    check that a given deb package is installed
    """
    res = subprocess.run(["/usr/sbin/chroot", chroot_path.as_posix(), "dpkg-query", "-W", deb_name])
    assert res.returncode == 0, f"deb package {deb_name} is not installed"
    # check the hold status
    res_mark = subprocess.check_output(["/usr/sbin/chroot", chroot_path.as_posix(), "apt-mark", "showhold", deb_name])
    assert (deb_name in res_mark.decode().strip()) is deb_hold


@pytest.mark.parametrize(
    "config_path,checks",
    [
        [
            "configs/kernel-only.yaml",
            [
                (partial(_check_file_exists, pathlib.Path("boot/vmlinuz"))),
                (partial(_check_deb_installed, "linux-aws", False)),
            ],
        ],
        [
            "configs/deb-only.yaml",
            [
                (partial(_check_deb_installed, "chrony", False)),
                (partial(_check_deb_installed, "fuse3", True)),
                (partial(_check_deb_installed, "ec2-hibinit-agent", False)),
            ],
        ],
        [
            "configs/ppas.yaml",
            [
                (partial(_check_file_exists, pathlib.Path("etc/apt/sources.list.d/deadsnakes.sources"))),
                (partial(_check_file_exists, pathlib.Path("etc/apt/trusted.gpg.d/deadsnakes.gpg"))),
                (partial(_check_file_not_exists, pathlib.Path("etc/apt/sources.list.d/kernel-unstable.sources"))),
                (partial(_check_file_not_exists, pathlib.Path("etc/apt/trusted.gpg.d/kernel-unstable.gpg"))),
            ],
        ],
        pytest.param(
            "configs/files.yaml",
            [
                # test uploading a file using content
                (partial(_check_file_exists, pathlib.Path("single_file_upload/using_content.txt"))),
                # test uploading a file using local source path
                (partial(_check_file_exists, pathlib.Path("single_file_upload/using_source.txt"))),
                # test uploading a directory with single file
                (partial(_check_file_exists, pathlib.Path("directory_upload_1/file_1.txt"))),
                # test uploading a directory with multiple files
                (partial(_check_file_exists, pathlib.Path("directory_upload_2/file_1.txt"))),
                (partial(_check_file_exists, pathlib.Path("directory_upload_2/file_2.txt"))),
                # test recursive directory upload that contains a file and a sub-directory inside
                (
                    partial(
                        _check_file_exists,
                        pathlib.Path(
                            "examples_files_directory/directory_with_multiple_files/file_1.txt",
                        ),
                    )
                ),
                (
                    partial(
                        _check_file_exists,
                        pathlib.Path(
                            "examples_files_directory/directory_with_multiple_files/file_2.txt",
                        ),
                    )
                ),
                (
                    partial(
                        _check_file_exists,
                        pathlib.Path(
                            "examples_files_directory/directory_with_single_file/file_1.txt",
                        ),
                    )
                ),
                (
                    partial(
                        _check_file_exists,
                        pathlib.Path(
                            "examples_files_directory/single_file.txt",
                        ),
                    )
                ),
            ],
            id="test all config file methods",
        ),
    ],
)
@pytest.mark.realchroot
def test_config(chroot_mmdebstrap_dir, config_path, checks):
    """
    Test different configuration examples from the functional/configs directory
    """
    ctx = context.Context(conf_path=curdir / config_path, chroot_path=chroot_mmdebstrap_dir)
    cr = chroot.Chroot(ctx)
    cr.apply()
    # do checks
    for check in checks:
        check(chroot_mmdebstrap_dir)
