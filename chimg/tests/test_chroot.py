#  SPDX-FileCopyrightText: 2024 Thomas Bechtold <thomasbechtold@jpberlin.de>
#  SPDX-License-Identifier: GPL-3.0-or-later

from unittest.mock import patch, ANY
import os
import pathlib
import pytest
import yaml

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


def test__snap_delete(chroot_dir):
    """
    test _snap_delete() method
    """
    ctx = context.Context(conf_path=curdir / "fixtures/config1.yaml", chroot_path=chroot_dir)
    cr = chroot.Chroot(ctx)
    # install the snap first
    snap_info = cr._snap_install("chimg", "latest/stable", True, None)
    # check that the .snap and .assert file exist
    assert pathlib.Path(f"{chroot_dir}/var/lib/snapd/seed/snaps/{snap_info.filename}").exists()
    assertion_name = snap_info.filename.replace(".snap", ".assert")
    assert pathlib.Path(f"{chroot_dir}/var/lib/snapd/seed/assertions/{assertion_name}").exists()
    # delete the snap
    cr._snap_delete(snap_info)
    assert not pathlib.Path(f"{chroot_dir}/var/lib/snapd/seed/snaps/{snap_info.filename}").exists()
    assert not pathlib.Path(f"{chroot_dir}/var/lib/snapd/seed/assertions/{assertion_name}").exists()


@pytest.mark.parametrize(
    "snap_infos,expected_call_count",
    [
        # not base given so it expects "core"
        ({"hello": chroot.SnapInfo(name="hello", channel="", classic=False, filename="hello_42.snap", info={})}, 1),
        # core explicit given so don't expect it to be installed
        ({"core": chroot.SnapInfo(name="core", channel="", classic=False, filename="core_423443.snap", info={})}, 0),
        # core22 explicit given so don't expect it to be installed
        (
            {"core22": chroot.SnapInfo(name="core", channel="", classic=False, filename="core22_423443.snap", info={})},
            0,
        ),
        # no base given for hello so expect "core" but core explicitly mentioned
        (
            {
                "hello": chroot.SnapInfo(name="hello", channel="", classic=False, filename="hello_42.snap", info={}),
                "core": chroot.SnapInfo(name="core", channel="", classic=False, filename="core_423443.snap", info={}),
            },
            0,
        ),
    ],
)
def test__snaps_base_install(chroot_dir, snap_infos, expected_call_count):
    """
    test _snaps_base_install() method
    """
    ctx = context.Context(conf_path=curdir / "fixtures/config1.yaml", chroot_path=chroot_dir)
    cr = chroot.Chroot(ctx)
    with patch.object(cr, "_snap_install") as mock:
        cr._snaps_base_install(snap_infos)
        assert mock.call_count == expected_call_count


@pytest.mark.parametrize(
    "snap_infos,expected_content",
    [
        # not base given so it expects "core"
        (
            {
                "hello": chroot.SnapInfo(
                    name="hello", channel="latest", classic=False, filename="hello_42.snap", info={}
                )
            },
            """snaps:
- channel: latest
  classic: false
  file: hello_42.snap
  name: hello
""",
        ),
    ],
)
def test__snaps_create_seed_yaml(chroot_dir, snap_infos, expected_content):
    """
    Test _snaps_create_seed_yaml()
    """
    ctx = context.Context(conf_path=curdir / "fixtures/config1.yaml", chroot_path=chroot_dir)
    cr = chroot.Chroot(ctx)
    cr._snaps_create_seed_yaml(snap_infos)
    with open(f"{chroot_dir}/var/lib/snapd/seed/seed.yaml", "r") as f:
        content = f.read()
        assert content == expected_content


@pytest.mark.parametrize(
    "config,grub_force_partuuid_exist",
    [
        ("fixtures/config1.yaml", True),
        ("fixtures/config2.yaml", False),
    ],
)
@patch("chimg.common.subprocess.run")
def test__kernel_boot_without_initramfs(mock_subprocess, chroot_dir, config, grub_force_partuuid_exist):
    """
    test _kernel_boot_without_initramfs()
    """
    mock_subprocess.return_value.returncode = 0
    mock_subprocess.return_value.stdout = b"stdout"
    mock_subprocess.return_value.stderr = b"stderr"

    grub_conf_dir = f"{chroot_dir}/etc/default/grub.d/"
    os.makedirs(grub_conf_dir, exist_ok=True)
    ctx = context.Context(conf_path=curdir / config, chroot_path=chroot_dir)
    cr = chroot.Chroot(ctx)
    cr._kernel_boot_without_initramfs()
    assert os.path.isfile(f"{grub_conf_dir}/40-force-partuuid.cfg") is grub_force_partuuid_exist


def test__snaps_already_installed_no_seed_yaml(chroot_dir):
    """Test _snaps_already_installed() when no seed.yaml file exists"""

    ctx = context.Context(conf_path=curdir / "fixtures/config1.yaml", chroot_path=chroot_dir)
    cr = chroot.Chroot(ctx)

    result = cr._snaps_already_installed()
    assert result == {}


def test__snaps_already_installed_with_seed_yaml(chroot_dir):
    """Test _snaps_already_installed() with snap files and seed.yaml"""
    # Mock seed.yaml content
    mock_seed_yaml = yaml.safe_load(
        """
snaps:
  - name: core20
    file: core20_1.snap
    channel: latest/edge
    classic: false
"""
    )

    # Mock _snap_info method
    mock_snap_info = chroot.SnapInfo(
        name="core20", filename="core20_1.snap", channel="latest/stable", classic=False, info={}
    )

    ctx = context.Context(conf_path=curdir / "fixtures/config1.yaml", chroot_path=chroot_dir)
    cr = chroot.Chroot(ctx)

    with patch.object(cr, "_snaps_read_seed_yaml", return_value=mock_seed_yaml):
        with patch.object(cr, "_snap_info", return_value=mock_snap_info):
            result = cr._snaps_already_installed()

    assert len(result) == 1
    assert "core20" in result
    assert result["core20"].name == "core20"
    assert result["core20"].filename == "core20_1.snap"
    assert result["core20"].channel == "latest/edge"
    assert result["core20"].classic is False
