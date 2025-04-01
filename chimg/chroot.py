#  SPDX-FileCopyrightText: 2024 Thomas Bechtold <thomasbechtold@jpberlin.de>
#  SPDX-License-Identifier: GPL-3.0-or-later

import multiprocessing
import shutil
import textwrap
from pathlib import Path
from typing import List, Optional, Dict, Tuple
import logging
from contextlib import contextmanager, ExitStack
import urllib.request
import tempfile
import os
import glob
import yaml

from chimg.common import run_command
from chimg.config import ConfigFile
from chimg.context import Context

logger = logging.getLogger(__name__)


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

    def _snaps_install(self):
        """
        Install all configured snaps
        """
        if not self._ctx.conf["snap"]:
            return

        logger.info("Installing snaps ...")
        for snap in self._ctx.conf["snap"]["snaps"]:
            self._snap_install(snap["name"], snap["channel"], snap["classic"], snap.get("revision"))
            self._snap_base_install(snap["name"])
        # install snapd
        self._snap_install("snapd", "stable")
        logger.info("Snaps installed")

    def _snap_base_install(self, name: str):
        """
        Install the base (coreXX) snap for the given snap
        The expects that the snap was already installed via _snap_install()
        """
        # if there are zero or multiple snaps for the given name, something is wrong
        snaps = glob.glob(f"{self._ctx.chroot_path}/var/lib/snapd/seed/snaps/{name}*.snap")
        if len(snaps) != 1:
            raise RuntimeError(f"Expected exactly one snap file for {name}, got {len(snaps)}")

        snap_info, _ = run_command(["snap", "info", "--verbose", snaps[0]])
        snap_info_yaml = yaml.safe_load(snap_info)
        if "type" not in snap_info_yaml.keys() or snap_info_yaml["type"] != "base":
            if "base" not in snap_info_yaml.keys():
                raise RuntimeError(f"Snap {name} has no base set which means its 'core' which is no longer allowed")
            # there is a core set, so install it if not already installed
            # check if the core snap is already installed
            snap_cores = glob.glob(f"{self._ctx.chroot_path}/var/lib/snapd/seed/snaps/{snap_info_yaml['base']}*.snap")
            if len(snap_cores) == 0:
                self._snap_install(snap_info_yaml["base"], "stable")

    def _snap_install(self, name: str, channel: str, classic: bool = False, revision: Optional[str] = None):
        """
        Install a single snap
        Use _snaps_install() to install all configured snaps
        """
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
            snap_file = glob.glob(f"{tmpdir}/*.snap")[0]
            run_command(["mv", snap_file, f"{self._ctx.chroot_path}/var/lib/snapd/seed/snaps"])

            # add snap to seed.yaml
            self._snap_add_to_seed_yaml(name, channel, os.path.basename(snap_file), classic)

    def _snap_add_to_seed_yaml(self, name: str, channel: str, snap_file: str, classic: bool):
        """
        add a snap to the seed.yaml file
        """
        seed_yaml = f"{self._ctx.chroot_path}/var/lib/snapd/seed/seed.yaml"
        # if the file doesn't exist yet, create it with the basic yaml structure
        if not os.path.exists(seed_yaml):
            with open(seed_yaml, "w") as f:
                f.write("snaps: []")
        # read existing snaps listed in seed.yaml
        with open(seed_yaml, "r") as f:
            y = yaml.safe_load(f.read())

        snaps_yaml = y["snaps"]
        if name in [snap["name"] for snap in snaps_yaml]:
            logger.warning(f"Snap {name} is already in seed.yaml. skipping")
            return

        snap_yaml = {
            "name": name,
            "channel": channel,
            "file": snap_file,
            "classic": classic,
        }
        snaps_yaml.append(snap_yaml)
        y["snaps"] = snaps_yaml
        # write the updated seed.yaml
        with open(seed_yaml, "w+") as f:
            f.write(yaml.dump(y))

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
                target = f"{self._ctx.chroot_path}/sys/kernel/security/apparmor/features/"
                with self._mount_bind(self._ctx.conf["snap"]["aa_features_path"], target):
                    run_command(
                        [
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
                    )

    def _files_install(self):
        """
        Install all configured files
        """
        logger.info("Installing files ...")
        for f in self._ctx.conf["files"]:
            if f.get("content"):
                self._file_install_from_content(ConfigFile(**f))
            else:
                self._file_install_from_path(ConfigFile(**f))
        logger.info("Files installed")

    def _file_install_from_content(self, file_config: ConfigFile):
        """
        Install a single file
        """
        f_path = f"{self._ctx.chroot_path}/{file_config.destination}"
        os.makedirs(os.path.dirname(f_path), exist_ok=True)
        if not file_config.content:
            raise ValueError("File content is required to create file using content")
        with open(f_path, "w") as file:
            file.write(file_config.content)
        if file_config.owner is not None:
            os.chown(f_path, int(file_config.owner), -1)
        if file_config.group is not None:
            os.chown(f_path, -1, int(file_config.group))
        if file_config.mode is not None:
            os.chmod(f_path, file_config.mode)
        logger.info(f"Created file {f_path} using provided file content")

    def _file_install_from_path(self, config_file: ConfigFile):
        """
        Copy a local file or directory to the chroot
        """
        src = config_file.source
        dst = config_file.destination

        if not src:
            raise ValueError("Source file or directory is required to copy file(s) into chroot")

        # if the source is a directory, copy it recursively
        if os.path.isdir(src):
            if not os.path.isdir(f"{self._ctx.chroot_path}/{dst}"):
                os.makedirs(f"{self._ctx.chroot_path}/{dst}", exist_ok=True)
            # copy src dir to dst dir recursively
            shutil.copytree(src, f"{self._ctx.chroot_path}/{dst}", dirs_exist_ok=True)
            logger.info(f"Copied directory {src} to {dst}")
        # otherwise, copy the file
        else:
            # copy src file to dst file path
            shutil.copy2(src, f"{self._ctx.chroot_path}/{dst}")
            logger.info(f"Copied file {src} to {dst}")
        # only set the owner/group/mode to the destination if they are set
        # all files/dirs inside the destination will be copied with their original permissions and owner/group
        if config_file.owner is not None:
            os.chown(f"{self._ctx.chroot_path}/{dst}", int(config_file.owner), -1)
        if config_file.group is not None:
            os.chown(f"{self._ctx.chroot_path}/{dst}", -1, int(config_file.group))
        if config_file.mode is not None:
            os.chmod(f"{self._ctx.chroot_path}/{dst}", config_file.mode)

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
