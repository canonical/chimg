#!/usr/bin/python3

#  SPDX-FileCopyrightText: 2024 Thomas Bechtold <thomasbechtold@jpberlin.de>
#  SPDX-License-Identifier: GPL-3.0-or-later

import pathlib
import sys
import os
import logging
import argparse

from chimg.context import Context
from chimg.chroot import Chroot


logger = logging.getLogger(__name__)


def _chrootfs(args) -> None:
    """
    Modify given chroot FS according to the given config
    """
    if not os.path.exists(args.config):
        logger.error(f"config file {args.config} does not exist")
        sys.exit(1)

    if not os.path.exists(args.rootfspath):
        logger.error(f"rootfs path {args.rootfspath} does not exist")
        sys.exit(1)

    ctx = Context(args.config, args.rootfspath)
    chroot = Chroot(ctx)
    chroot.apply()


def _parser():
    parser = argparse.ArgumentParser(description="change image")
    parser.add_argument("--log-level", choices=["info", "debug"], default="info")
    parser.add_argument("--log-file", type=pathlib.Path, help="write log to given file instead of stdout")
    parser.add_argument("--log-console", action="store_true", help="write log to stdout")
    p_sub = parser.add_subparsers(help="sub-command help")

    # chrootfs
    p_chrootfs = p_sub.add_parser("chrootfs", help="Modify given chroot FS")
    p_chrootfs.add_argument("config", type=pathlib.Path, help="the path to the chimg config file")
    p_chrootfs.add_argument("rootfspath", type=pathlib.Path, help="the path to the rootfs directory to work with")
    p_chrootfs.set_defaults(func=_chrootfs)

    return parser


def main():
    parser = _parser()
    args = parser.parse_args()
    log_formatter = logging.Formatter("%(asctime)s:%(name)s:%(levelname)s:%(message)s")
    # log level
    loglevel = logging.INFO
    if args.log_level == "debug":
        loglevel = logging.DEBUG
    root_logger = logging.getLogger()
    root_logger.setLevel(loglevel)
    # log file
    if args.log_file:
        file_handler = logging.FileHandler(filename=args.log_file)
        file_handler.setFormatter(log_formatter)
        root_logger.addHandler(file_handler)
    # log console
    if args.log_console:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(log_formatter)
        root_logger.addHandler(console_handler)
    if "func" not in args:
        sys.exit(parser.print_help())
    args.func(args)
    sys.exit(0)


if __name__ == "__main__":
    main()
