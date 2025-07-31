#  SPDX-FileCopyrightText: 2024 Thomas Bechtold <thomasbechtold@jpberlin.de>
#  SPDX-License-Identifier: GPL-3.0-or-later

import os
import pathlib
import glob
import pytest
import yaml
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


def _check_snap_preseeded(snap_name: str, chroot_path: pathlib.Path):
    """
    check that a given snap package is preseeded
    """
    # files should be there
    assertion_files = glob.glob(f"{chroot_path.as_posix()}/var/lib/snapd/seed/assertions/{snap_name}_*.assert")
    assert len(assertion_files) == 1
    snap_files = glob.glob(f"{chroot_path.as_posix()}/var/lib/snapd/seed/snaps/{snap_name}_*.snap")
    assert len(snap_files) == 1

    # entry in seed.yaml should exist
    with open(f"{chroot_path.as_posix()}/var/lib/snapd/seed/seed.yaml", "r") as f:
        y = yaml.safe_load(f.read())
        existing_names = [snap["name"] for snap in y["snaps"]]
    assert snap_name in existing_names


@pytest.mark.parametrize(
    "config_paths,checks",
    [
        [
            [
                "configs/kernel-only.yaml",
            ],
            [
                (partial(_check_file_exists, pathlib.Path("boot/vmlinuz"))),
                (partial(_check_deb_installed, "linux-aws", False)),
            ],
        ],
        [
            [
                "configs/deb-only.yaml",
            ],
            [
                (partial(_check_deb_installed, "chrony", False)),
                (partial(_check_deb_installed, "fuse3", True)),
                (partial(_check_deb_installed, "ec2-hibinit-agent", False)),
            ],
        ],
        [
            [
                "configs/snap-only.yaml",
            ],
            [
                (partial(_check_snap_preseeded, "hello")),
            ],
        ],
        [
            [
                "configs/snap-only-with-apparmor-feature-path.yaml",
            ],
            [
                (partial(_check_snap_preseeded, "hello")),
            ],
        ],
        [
            [
                "configs/ppas.yaml",
            ],
            [
                (partial(_check_file_exists, pathlib.Path("etc/apt/sources.list.d/deadsnakes.sources"))),
                (partial(_check_file_exists, pathlib.Path("etc/apt/trusted.gpg.d/deadsnakes.gpg"))),
                (partial(_check_file_not_exists, pathlib.Path("etc/apt/sources.list.d/kernel-unstable.sources"))),
                (partial(_check_file_not_exists, pathlib.Path("etc/apt/trusted.gpg.d/kernel-unstable.gpg"))),
            ],
        ],
    ],
)
@pytest.mark.realchroot
def test_config(chroot_mmdebstrap_dir, config_paths, checks):
    """
    Test different configuration examples from the functional/configs directory
    """
    for config_path in config_paths:
        ctx = context.Context(conf_path=curdir / config_path, chroot_path=chroot_mmdebstrap_dir)
        cr = chroot.Chroot(ctx)
        cr.apply()

    # do checks
    for check in checks:
        check(chroot_mmdebstrap_dir)
