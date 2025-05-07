#  SPDX-FileCopyrightText: 2024 Thomas Bechtold <thomasbechtold@jpberlin.de>
#  SPDX-License-Identifier: GPL-3.0-or-later

from dataclasses import dataclass
import multiprocessing
import textwrap
from pathlib import Path
from typing import List, Optional, Dict, Tuple, Any
import logging
from contextlib import contextmanager, ExitStack
import urllib.request
import re
import tempfile
import os
import glob
import yaml

from chimg.common import run_command
from chimg.context import Context

logger = logging.getLogger(__name__)


@dataclass
class SnapInfo:
    name: str
    filename: str
    channel: str
    classic: bool
    info: Dict[str, Any]


class Chroot:
    def __init__(self, ctx: Context):
        self._ctx: Context = ctx

    def apply(self):
        """
        Apply the chroot changes
        """
        stacks = [self._mount(), self._policy_rc_runlevel_ops(), self._ppas_setup(), self._grub_divert()]

        with ExitStack() as stack:
            # prepare chroot
            [stack.enter_context(s) for s in stacks]
            # run all steps
            self._cmds_pre()
            self._kernel_install()
            self._debs_install()
            self._files_install()
            # setup snap assertions for preseeding
            self._snap_assertion_install()
            # install snaps
            self._snaps_install()
            self._snap_preseed()
            self._cmds_post()
            logger.info("🎉 Chroot changes applied 🎉 . cleaning up ...")

    def _cmds_pre(self):
        """
        Run all pre commands
        """
        for cmd in self._ctx.conf["cmds_pre"]:
            self._cmd_run(cmd["cmd"])

    def _cmds_post(self):
        """
        Run all post commands
        """
        for cmd in self._ctx.conf["cmds_post"]:
            self._cmd_run(cmd["cmd"])

    def _cmd_run(self, cmd: str) -> Tuple[str, str]:
        """
        Run a command in the chroot
        """
        fname = None
        try:
            f = tempfile.NamedTemporaryFile(prefix="chimg_", dir=self._ctx.chroot_path, delete=False)
            fname = f.name
            f.write(cmd.encode())
            f.seek(0)
            os.chmod(f.name, 0o700)
            f.close()
            return run_command(["/usr/sbin/chroot", self._ctx.chroot_path, f"/{os.path.basename(f.name)}"])
        except Exception:
            logger.exception(f"Error running command: {cmd}")
            raise
        finally:
            if fname:
                os.remove(fname)

    def _snaps_base_install(self, snap_infos: Dict[str, SnapInfo]) -> Dict[str, SnapInfo]:
        """
        Install the required core/coreXX snaps for the given snaps
        """
        # install the required base snaps
        required_cores = set()
        for snap, si in snap_infos.items():
            if snap == "snapd":
                # snapd is self-contained, ignore base
                continue
            if re.match(r"^core(?:\d\d)?$", snap):
                # core and core## are self-contained, ignore base
                continue

            # the core for the current snap
            core_name = si.info.get("base", "core")
            if core_name in snap_infos.keys():
                # the core got already explicitly installed so don't add it here
                continue
            required_cores.add(core_name)

        for core in required_cores:
            snap_infos[core] = self._snap_install(name=core, channel="stable")
        return snap_infos

    def _snaps_install(self):
        """
        Install all configured snaps
        """
        if not self._ctx.conf["snap"]:
            return

        logger.info("Installing snaps ...")
        snap_infos: Dict[str, SnapInfo] = {}
        for snap in self._ctx.conf["snap"]["snaps"]:
            snap_infos[snap["name"]] = self._snap_install(
                snap["name"], snap["channel"], snap["classic"], snap.get("revision")
            )

        # install required cores
        snap_infos = self._snaps_base_install(snap_infos)

        # install snapd only if not already explicitly installed
        if "snapd" not in snap_infos.keys():
            snap_infos["snapd"] = self._snap_install("snapd", "stable")

        # write seed.yaml
        self._snaps_create_seed_yaml(snap_infos)
        logger.info("Snaps installed")

    def _snaps_create_seed_yaml(self, snap_infos: Dict[str, SnapInfo]):
        """
        Write out the seed.yaml file based on the given snap
        """
        Path(f"{self._ctx.chroot_path}/var/lib/snapd/seed/").mkdir(parents=True, exist_ok=True)
        seed_yaml = f"{self._ctx.chroot_path}/var/lib/snapd/seed/seed.yaml"
        snaps_yaml_list = []
        for snap, si in snap_infos.items():
            snap_yaml = {
                "name": si.name,
                "channel": si.channel,
                "file": si.filename,
                "classic": si.classic,
            }
            snaps_yaml_list.append(snap_yaml)
        snaps_yaml = {"snaps": snaps_yaml_list}
        # write the updated seed.yaml
        with open(seed_yaml, "w") as f:
            f.write(yaml.dump(snaps_yaml))
        logger.info(f"seed.yaml file written to {seed_yaml}")

    def _snap_info(self, path: str):
        """
        Get information for a downloaded snap
        this must be done from the downloaded .snap given that the API
        doesn't support channel and revision.
        :param path: the path to the .snap file
        :type path: str
        """
        info, _ = run_command(["snap", "info", "--verbose", path])
        info_yaml = yaml.safe_load(info)
        return info_yaml

    def _snap_install(self, name: str, channel: str, classic: bool = False, revision: Optional[str] = None) -> SnapInfo:
        """
        Install a single snap
        Use _snaps_install() to install all configured snaps
        """
        # make sure the final target directories exist
        Path(f"{self._ctx.chroot_path}/var/lib/snapd/seed/assertions").mkdir(parents=True, exist_ok=True)
        Path(f"{self._ctx.chroot_path}/var/lib/snapd/seed/snaps").mkdir(parents=True, exist_ok=True)

        arch, _ = run_command(["dpkg", "--print-architecture"])
        with tempfile.TemporaryDirectory(prefix="chimg_") as tmpdir:
            # FIXME: add cohort key support
            cmd = ["snap", "download", f"--target-directory={tmpdir}", f'--channel="{channel}"']
            if revision:
                cmd.extend(["--revision", revision])
            cmd.append(name)
            run_command(cmd, env={"UBUNTU_STORE_ARCH": arch, "SNAPPY_STORE_NO_CDN": "1", "PATH": "/usr/bin"})

            # move downloaded assertions (there should really be only a single one!)
            assertion_files = glob.glob(f"{tmpdir}/*.assert")
            if len(assertion_files) != 1:
                # TODO: use a chimg specific exception here
                raise RuntimeError(f"Multiple .assert files available for snap {name}")
            assertion_file = assertion_files[0]
            run_command(["mv", assertion_file, f"{self._ctx.chroot_path}/var/lib/snapd/seed/assertions"])
            # move downloaded snap files (there should really be only a single one!)
            snap_files = glob.glob(f"{tmpdir}/*.snap")
            if len(snap_files) != 1:
                # TODO: use a chimg specific exception here
                raise RuntimeError(f"Multiple .snap files available for snap {name}")
            snap_file = snap_files[0]
            snap_info_yaml = self._snap_info(snap_file)
            run_command(["mv", snap_file, f"{self._ctx.chroot_path}/var/lib/snapd/seed/snaps"])

            return SnapInfo(
                name=name, filename=os.path.basename(snap_file), channel=channel, classic=classic, info=snap_info_yaml
            )

    def _snap_assertion_install(self):
        """
        Install snap assertions
        """
        if not self._ctx.conf["snap"]:
            return

        logger.info("Installing snap assertions ...")
        Path(f"{self._ctx.chroot_path}/var/lib/snapd/seed/assertions").mkdir(parents=True, exist_ok=True)
        Path(f"{self._ctx.chroot_path}/var/lib/snapd/seed/snaps").mkdir(parents=True, exist_ok=True)

        # model assertion
        model_assertion, _ = run_command(
            [
                "snap",
                "known",
                "--remote",
                "model",
                "series=16",
                f"model={self._ctx.conf['snap']['assertion_model']}",
                f"brand-id={self._ctx.conf['snap']['assertion_brand']}",
            ]
        )
        # get the account key from the model assertion
        account_key = None
        for line in model_assertion.splitlines():
            if line.startswith("sign-key-sha3-384:"):
                account_key = line.split(":")[1].strip()
                break
        if not account_key:
            raise RuntimeError("Could not get account key from model assertion")

        # write model assertion
        with open(f"{self._ctx.chroot_path}/var/lib/snapd/seed/assertions/model", "w") as f:
            f.write(model_assertion)

        # account key assertion
        account_key_assertion, _ = run_command(
            ["snap", "known", "--remote", "account-key", f"public-key-sha3-384={account_key}"]
        )
        # get the account id from the account key assertion
        account_id = None
        for line in account_key_assertion.splitlines():
            if line.startswith("account-id:"):
                account_id = line.split(":")[1].strip()
                break
        if not account_id:
            raise RuntimeError("Could not get account id from account key assertion")

        # write account key assertion
        with open(f"{self._ctx.chroot_path}/var/lib/snapd/seed/assertions/account-key", "w") as f:
            f.write(account_key_assertion)

        # account assertion
        account_assertion, _ = run_command(["snap", "known", "--remote", "account", f"account-id={account_id}"])

        # write account assertion
        with open(f"{self._ctx.chroot_path}/var/lib/snapd/seed/assertions/account", "w") as f:
            f.write(account_assertion)

        logger.info("Snap assertions installed")

    def _snap_preseed(self):
        """
        Do the preseeding
        """
        seed_yaml_path = f"{self._ctx.chroot_path}/var/lib/snapd/seed/seed.yaml"
        if os.path.exists(seed_yaml_path):
            run_command(["snap", "debug", "validate-seed", seed_yaml_path])
            run_command(["/usr/lib/snapd/snap-preseed", "--reset", os.path.realpath(self._ctx.chroot_path)])
            run_command(
                ["/usr/lib/snapd/snap-preseed", os.path.realpath(self._ctx.chroot_path)], env={"PATH": "/usr/bin"}
            )
            # mount the apparmor features into the chroot to make snap preseeding work
            if self._ctx.conf["snap"]:
                cmd = [
                    "chroot",
                    self._ctx.chroot_path,
                    "apparmor_parser",
                    "--skip-read-cache",
                    "--write-cache",
                    "--skip-kernel-load",
                    "--verbose",
                    "-j",
                    str(multiprocessing.cpu_count()),
                    "/etc/apparmor.d",
                ]
                target = f"{self._ctx.chroot_path}/sys/kernel/security/apparmor/features/"
                if self._ctx.conf["snap"]["aa_features_path"]:
                    with self._mount_bind(self._ctx.conf["snap"]["aa_features_path"], target):
                        run_command(cmd)
                else:
                    run_command(cmd)

    def _files_install(self):
        """
        Install all configured files
        """
        logger.info("Installing files ...")
        for f in self._ctx.conf["files"]:
            self._file_install(f)
        logger.info("Files installed")

    def _file_install(self, f: Dict):
        """
        Install a single file
        """
        f_path = f"{self._ctx.chroot_path}/{f['destination']}"
        os.makedirs(os.path.dirname(f_path), exist_ok=True)
        with open(f_path, "w") as file:
            file.write(f["content"])
        if f.get("owner", None):
            os.chown(f_path, f["owner"], -1)
        if f.get("group", None):
            os.chown(f_path, -1, f["group"])
        if f.get("mode", None):
            os.chmod(f_path, f["mode"])

    def _debs_install(self):
        """
        Install all configured deb packages
        """
        logger.info("Installing deb packages ...")
        for deb in self._ctx.conf["debs"]:
            self._deb_install(deb)
        logger.info("Deb packages installed")

    def _deb_install(self, deb: Dict):
        """
        Install a single deb package
        Use _debs_install() to install all configured deb packages
        """
        run_command(
            [
                "/usr/sbin/chroot",
                self._ctx.chroot_path,
                "apt-get",
                "install",
                "--assume-yes",
                "--allow-downgrades",
                deb["name"],
            ],
            env={"DEBIAN_FRONTEND": "noninteractive"},
        )
        if deb.get("hold", False):
            run_command(
                ["/usr/sbin/chroot", self._ctx.chroot_path, "apt-mark", "hold", deb["name"]],
                env={"DEBIAN_FRONTEND": "noninteractive"},
            )

    def _apt_update(self):
        """
        Call apt-get update in the chroot
        """
        run_command(
            ["/usr/sbin/chroot", self._ctx.chroot_path, "apt-get", "update", "--assume-yes", "--error-on=any"],
            env={"DEBIAN_FRONTEND": "noninteractive"},
        )

    def _kernel_install(self):
        """
        Install a kernel package
        """
        if not self._ctx.conf["kernel"]:
            logger.info("No kernel configured")
            return

        logger.info("Installing kernel ...")
        run_command(
            [
                "/usr/sbin/chroot",
                self._ctx.chroot_path,
                "apt-get",
                "remove",
                "--purge",
                "--assume-yes",
                "--allow-change-held-packages",
                "'^linux-.*'",
                "linux-base+",
            ],
            env={"DEBIAN_FRONTEND": "noninteractive"},
            shell=True,
        )
        self._apt_update()
        run_command(
            ["/usr/sbin/chroot", self._ctx.chroot_path, "apt-get", "install", "--assume-yes", self._ctx.conf["kernel"]],
            env={"DEBIAN_FRONTEND": "noninteractive"},
        )
        logger.info("Kernel installed")
        self._kernel_boot_without_initramfs()
        self._grub_replace_root_with_label()

    def _kernel_boot_without_initramfs(self):
        m, _ = run_command(["findmnt", "-n", "-o", "SOURCE", "--target", self._ctx.chroot_path])
        partuuid, _ = run_command(["blkid", "-s", "PARTUUID", "-o", "value", m])
        if partuuid:
            logger.info("Force booting without initramfs with PARTUUID={partuuid}...")
            run_command(["mkdir", "-p", f"{self._ctx.chroot_path}/etc/default/grub.d"])
            with open(f"{self._ctx.chroot_path}/etc/default/grub.d/40-force-partuuid.cfg", "w") as f:
                f.write(
                    textwrap.dedent(
                        f"""
# Force boot without an initramfs by setting GRUB_FORCE_PARTUUID
# Remove this line to enable boot with an initramfs
GRUB_FORCE_PARTUUID={partuuid}"""
                    )
                )
                run_command(["chroot", self._ctx.chroot_path, "update-grub"])

    def _grub_replace_root_with_label(self):
        """
        Replace the root=PARTUUID=... with root=LABEL=... in the grub.cfg
        """
        if os.path.exists(f"{self._ctx.chroot_path}/etc/default/grub.d/40-force-partuuid.cfg"):
            return

        if not self._ctx.conf["fs"]:
            logger.info("No filesystem configured")
            return

        if os.path.exists(f"{self._ctx.chroot_path}/boot/grub/grub.cfg"):
            fs_label = self._ctx.conf["fs"]["root_fs_label"]
            run_command(
                [
                    "sed",
                    "-i",
                    "-e",
                    f'"s,root=[^ ]*,root=LABEL={fs_label},"',  # noqa: E231,E202
                    f"{self._ctx.chroot_path}/boot/grub/grub.cfg",
                ],
                shell=True,
            )

    def _write_key(self, key_fingerprint: str, dest_path: str):
        """
        Get a key (.asc) from a keyserver, convert to OpenPGP public key
        and write the key to the given dest_path
        """
        url = f"https://keyserver.ubuntu.com/pks/lookup?op=get&search=0x{key_fingerprint}"  # noqa: E231
        response = urllib.request.urlopen(url)
        data = response.read()
        with tempfile.NamedTemporaryFile(prefix="chimg_") as f:
            f.write(data)
            f.seek(0)
            cmd = ["/usr/bin/gpg", "--yes", "--dearmor", "--output", dest_path, f.name]
            run_command(cmd)

    @contextmanager
    def _grub_divert(self):
        """
        Context manager to divert grub and related stuff for a kernel repacement
        """
        # Don't divert all of grub-probe here; just the scripts we don't want
        # running. Otherwise, you may be missing part-uuids for the search
        # command, for example. ~cyphermox
        logger.info("Adding grub divertions ...")
        cmd = [
            "chroot",
            self._ctx.chroot_path,
            "dpkg-divert",
            "--local",
            "--divert",
            "/etc/grub.d/30_os-prober.dpkg-divert",
            "--rename",
            "/etc/grub.d/30_os-prober",
        ]
        run_command(cmd)

        # Divert systemd-detect-virt; /etc/kernel/postinst.d/zz-update-grub
        # no-ops if we are in a container, and the launchpad farm runs builds
        # in lxd.  We therefore pretend that we're never in a container (by
        # exiting 1).
        cmd = ["chroot", self._ctx.chroot_path, "dpkg-divert", "--local", "--rename", "/usr/bin/systemd-detect-virt"]
        run_command(cmd)
        with open(f"{self._ctx.chroot_path}/usr/bin/systemd-detect-virt", "w") as f:
            f.write(
                textwrap.dedent(
                    """\
            #!/bin/sh
            exit 1
            """
                )
            )
        os.chmod(f"{self._ctx.chroot_path}/usr/bin/systemd-detect-virt", 0o755)
        logger.info("grub divertions added")
        yield
        logger.info("Removing grub divertions ...")
        # cleanup the diversion
        cmd = [
            "chroot",
            self._ctx.chroot_path,
            "dpkg-divert",
            "--remove",
            "--local",
            "--divert",
            "/etc/grub.d/30_os-prober.dpkg-divert",
            "--rename",
            "/etc/grub.d/30_os-prober",
        ]
        run_command(cmd)
        os.remove(f"{self._ctx.chroot_path}/usr/bin/systemd-detect-virt")
        cmd = [
            "chroot",
            self._ctx.chroot_path,
            "dpkg-divert",
            "--remove",
            "--local",
            "--rename",
            "/usr/bin/systemd-detect-virt",
        ]
        run_command(cmd)
        logger.info("grub divertions removed")

    @contextmanager
    def _ppas_setup(self):
        """
        Setup all configured PPAs
        """
        if len(self._ctx.conf["ppas"]) > 0:
            with ExitStack() as stack:
                for ppa in self._ctx.conf["ppas"]:
                    stack.enter_context(
                        self._ppa_setup(
                            ppa["name"],
                            ppa["uri"],
                            ppa["suites"],
                            ppa["components"],
                            ppa["keep"],
                            ppa["fingerprint"],
                            ppa["signed_by"],
                            ppa["username"],
                            ppa["password"],
                            ppa["auth_lines"],
                            ppa["pin_name"],
                            ppa["pin_priority"],
                        )
                    )
                logger.info("All PPAs setup")
                cmd = ["/usr/sbin/chroot", self._ctx.chroot_path, "apt-cache", "policy"]
                out, err = run_command(cmd)
                logger.info(out)
                yield
        else:
            # no PPAs setup - but do at least one apt-get update
            self._apt_update()
            yield

    @contextmanager
    def _ppa_setup(
        self,
        name: str,
        repo_uri: str,
        repo_suites: List[str],
        repo_components: List[str],
        keep: bool,
        repo_key_fingerprint: Optional[str] = None,
        signed_by: Optional[str] = None,
        repo_username: Optional[str] = None,
        repo_password: Optional[str] = None,
        repo_auth_lines: Optional[List[str]] = None,
        repo_pin_name: Optional[str] = None,
        repo_pin_priority: Optional[int] = None,
    ):
        """
        Context manager to setup a single PPA and cleanup at the end.
        Use ppas_setup() to setup all configured PPAs.
        """
        logger.info("Adding PPA ...")

        lines = [
            f"X-Repolib-Name: {name}",
            "Enabled: yes",
            "Types: deb",
            f"URIs: {repo_uri}",
            f"Suites: {' '.join(repo_suites)}",
            f"Components: {' '.join(repo_components)}",
        ]

        if repo_key_fingerprint and signed_by:
            logger.warning("repo key fingerprint and signed_by are mutually exclusive. Using repo_key_fingerprint")

        # get & write the key for the given fingerprint and write it
        if repo_key_fingerprint:
            self._write_key(repo_key_fingerprint, f"{self._ctx.chroot_path}/etc/apt/trusted.gpg.d/{name}.gpg")
            lines.append(f"Signed-By: /etc/apt/trusted.gpg.d/{name}.gpg")
        elif signed_by:
            lines.append(f"Signed-By: {signed_by}")

        # a deb822 style sources file
        with open(f"{self._ctx.chroot_path}/etc/apt/sources.list.d/{name}.sources", "w") as f:
            f.write("\n".join(lines))

        # apt authentication if username/password provided
        if repo_username and repo_password:
            with open(f"{self._ctx.chroot_path}/etc/apt/auth.conf.d/{name}.conf", "w") as f:
                f.write(f"machine {repo_uri} login {repo_username} password {repo_password}")

        # apt authentication if auth_lines provided
        if repo_auth_lines:
            with open(f"{self._ctx.chroot_path}/etc/apt/auth.conf.d/{name}.conf", "a+") as f:
                f.write("\n".join(repo_auth_lines))

        # apt pinning if pin_name and pin_priority provided
        if repo_pin_name and repo_pin_priority:
            with open(f"{self._ctx.chroot_path}/etc/apt/preferences.d/{name}.pref", "w") as f:
                f.write(
                    f"""Package: *
Pin: release o={repo_pin_name}
Pin-Priority: {repo_pin_priority}
"""
                )
        self._apt_update()
        logger.info("PPA added")
        yield
        # cleanup the PPA
        if not keep:
            logger.info("Removing PPA ...")
            if os.path.exists(f"{self._ctx.chroot_path}/etc/apt/sources.list.d/{name}.sources"):
                os.remove(f"{self._ctx.chroot_path}/etc/apt/sources.list.d/{name}.sources")
            if os.path.exists(f"{self._ctx.chroot_path}/etc/apt/trusted.gpg.d/{name}.gpg"):
                os.remove(f"{self._ctx.chroot_path}/etc/apt/trusted.gpg.d/{name}.gpg")
            if os.path.exists(f"{self._ctx.chroot_path}/etc/apt/auth.conf.d/{name}.conf"):
                os.remove(f"{self._ctx.chroot_path}/etc/apt/auth.conf.d/{name}.conf")
            if os.path.exists(f"{self._ctx.chroot_path}/etc/apt/preferences.d/{name}.pref"):
                os.remove(f"{self._ctx.chroot_path}/etc/apt/preferences.d/{name}.pref")
            self._apt_update()
            logger.info("PPA removed")

    @contextmanager
    def _policy_rc_runlevel_ops(self):
        """
        Disable all runlevel operations in the chroot
        """
        policy_rc_path = f"{self._ctx.chroot_path}/usr/sbin/policy-rc.d"
        written = False
        if not os.path.exists(policy_rc_path):
            logger.info("Disabling runlevel operations ...")
            with open(policy_rc_path, "w") as f:
                f.write(
                    textwrap.dedent(
                        """
                    #!/bin/sh
                    echo "All runlevel operations denied by policy" >&2
                    exit 101
                    """
                    )
                )
            os.chmod(policy_rc_path, 0o755)
            written = True
        yield
        if written:
            os.remove(policy_rc_path)
            logger.info("Runlevel operations reenabled")

    @contextmanager
    def _mount_bind(self, source: str, target: str):
        """
        bind mount source to target if target is not already mounted
        """
        mount_done = False
        try:
            if not os.path.ismount(target):
                run_command(["mount", "--bind", source, target])
                mount_done = True
            else:
                logger.info(f"{target} already mounted")
            yield
        finally:
            if mount_done:
                run_command(["umount", target])

    @contextmanager
    def _mount_fs(self, source: str, target: str, fs_type: str, options: str):
        """
        mount file system type source to target if target is not already mounted
        """
        mount_done = False
        try:
            if not os.path.ismount(target):
                cmd = ["mount", source, target, "-t", fs_type]
                if options:
                    cmd += ["-o", options]
                run_command(cmd)
                mount_done = True
            else:
                logger.info(f"{target} already mounted")
            yield
        finally:
            if mount_done:
                run_command(["umount", target])

    @contextmanager
    def _mount(self):
        """
        Do required mounts in chroot
        """
        logger.info("Setup mount points ...")
        mounts_fs = [
            ("dev-live", "/dev", "devtmpfs", None),
            ("devpts-live", "/dev/pts", "devpts", "nodev,nosuid"),
            ("proc-live", "/proc", "proc", None),
            ("sysfs-live", "/sys", "sysfs", None),
            ("securityfs", "/sys/kernel/security", "securityfs", None),
            ("none", "/sys/fs/cgroup", "cgroup2", None),
            ("none", "/tmp", "tmpfs", None),
            ("none", "/var/lib/apt/lists", "tmpfs", None),
            ("none", "/var/cache/apt", "tmpfs", None),
        ]
        with ExitStack() as stack:
            [
                stack.enter_context(self._mount_fs(s, f"{self._ctx.chroot_path}{t}", fs, opts))
                for s, t, fs, opts in mounts_fs
            ]
            logger.info("mount points setup done")
            yield
        logger.info("mount points cleanup done")
