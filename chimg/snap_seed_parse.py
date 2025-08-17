#!/usr/bin/python3

"""
Usage: snap-seed-parse [${chroot_dir}] <output file>

This script looks for a seed.yaml path in the given root directory, parsing
it and appending the parsed lines to the given output file.

The $chroot_dir argument is optional and will default to the empty string.
"""

import glob
import logging
import os.path
import re
import yaml


logger = logging.getLogger(__name__)


def main(
    chroot_path: str,
    output_file: str,
):
    """
    Main function to parse the seed.yaml file and generate a manifest.
    """
    CHROOT_ROOT = chroot_path
    FNAME = output_file
    logger.debug("Parsing seed.yaml")

    # Trim any trailing slashes for correct appending
    CHROOT_ROOT = CHROOT_ROOT.rstrip("/")

    # Snaps are prepended with this string in the manifest
    LINE_PREFIX = "snap:"

    # This is where we expect to find the seed.yaml file
    YAML_PATH = CHROOT_ROOT + "/var/lib/snapd/seed/seed.yaml"

    logger.debug("yaml path: %s", YAML_PATH)

    def make_manifest_from_seed_yaml(path):
        with open(YAML_PATH, "r") as fh:
            yaml_lines = yaml.safe_load(fh)["snaps"]

        logger.info("Writing manifest to %s", FNAME)

        with open(FNAME, "a+") as fh:
            for item in yaml_lines:
                filestring = item["file"]
                # Pull the revision number off the file name
                revision = filestring[filestring.rindex("_") + 1 :]  # noqa: E203 (black and flake8 disagree)
                revision = re.sub(r"[^0-9]", "", revision)
                fh.write(f"{LINE_PREFIX}{item['name']}\t{item['channel']}\t{revision}\n")

    def look_for_uc20_model(chroot):
        systems_dir = f"{chroot}/var/lib/snapd/seed/systems"
        if not os.path.isdir(systems_dir):
            logger.debug("no systems directory found")
            return None
        modeenv = f"{chroot}/var/lib/snapd/modeenv"
        system_name = None
        if os.path.isfile(modeenv):
            logger.debug("found modeenv file at %s", modeenv)
            with open(modeenv) as fh:
                for line in fh:
                    if line.startswith("recovery_system="):
                        system_name = line.split("=", 1)[1].strip()
                        logger.info("read system name %r from modeenv", system_name)
                        break
        if system_name is None:
            system_names = os.listdir(systems_dir)
            if len(system_names) == 0:
                logger.debug("no systems found")
                return None
            elif len(system_names) > 1:
                logger.debug("multiple systems found, refusing to guess which to parse")
                return None
            else:
                system_name = system_names[0]
                logger.debug("parsing only system found %s", system_name)
        system_dir = f"{chroot}/var/lib/snapd/seed/systems/{system_name}"
        if not os.path.isdir(system_dir):
            logger.debug("could not find system called %s", system_name)
            return None
        return system_dir

    def parse_assertion_file(asserts, filename):
        # Parse the snapd assertions file 'filename' and store the
        # assertions found in 'asserts'.
        with open(filename) as fp:
            text = fp.read()

        k = ""

        for block in text.split("\n\n"):
            if block.startswith("type:"):
                this_assert = {}
                for line in block.split("\n"):
                    if line.startswith(" "):
                        this_assert[k.strip()] += "\n" + line
                        continue
                    k, v = line.split(":", 1)
                    this_assert[k.strip()] = v.strip()
                asserts.setdefault(this_assert["type"], []).append(this_assert)

    def make_manifest_from_system(system_dir):
        files = [f"{system_dir}/model"] + glob.glob(f"{system_dir}/assertions/*")

        asserts = {}
        for filename in files:
            parse_assertion_file(asserts, filename)

        [model] = asserts["model"]
        snaps = yaml.safe_load(model["snaps"])

        snap_names = []
        for snap in snaps:
            snap_names.append(snap["name"])
        snap_names.sort()

        snap_name_to_id = {}
        snap_id_to_rev = {}
        for decl in asserts["snap-declaration"]:
            snap_name_to_id[decl["snap-name"]] = decl["snap-id"]
        for rev in asserts["snap-revision"]:
            snap_id_to_rev[rev["snap-id"]] = rev["snap-revision"]

        logger.debug("Writing manifest to %s", FNAME)

        with open(FNAME, "a+") as fh:
            for snap_name in snap_names:
                channel = snap["default-channel"]
                rev = snap_id_to_rev[snap_name_to_id[snap_name]]
                fh.write(f"{LINE_PREFIX}{snap_name}\t{channel}\t{rev}\n")

    if os.path.isfile(YAML_PATH):
        logger.debug("seed.yaml found at %s", YAML_PATH)
        make_manifest_from_seed_yaml(YAML_PATH)
    else:
        system_dir = look_for_uc20_model(CHROOT_ROOT)
        if system_dir is None:
            logger.error("WARNING: could not find seed.yaml or uc20-style seed")
            raise Exception("No seed.yaml or uc20-style seed found when trying to create manifest")
        make_manifest_from_system(system_dir)

    logger.debug("snap_seed_parse finished.")
