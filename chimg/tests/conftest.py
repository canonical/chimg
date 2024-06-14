#  SPDX-FileCopyrightText: 2024 Thomas Bechtold <thomasbechtold@jpberlin.de>
#  SPDX-License-Identifier: GPL-3.0-or-later

import tempfile
import pathlib
import pytest
import subprocess


def _get_host_apt_proxy():
    """
    Get the apt proxy from the host system
    """
    out = subprocess.check_output(["apt-config", "dump", "--format", "'%v'", "Acquire::http::Proxy"]).decode().strip()
    if out:
        return out
    else:
        return None


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

        cmd = ["mmdebstrap"]
        # if a apt proxy is configured on the host, use it for mmdebstrap to speedup the download
        apt_proxy = _get_host_apt_proxy()
        if apt_proxy:
            cmd.extend(["--aptopt", f"'Acquire::http {{ Proxy \"{apt_proxy}\"; }}'"])  # noqa: E201,E702,E202
        cmd.extend(["--variant", "apt", "--include", "gpg,squashfs-tools,snapd", "noble", tmpdirname])
        subprocess.check_call(cmd)
        yield pathlib.Path(tmpdirname)
