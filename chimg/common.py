#  SPDX-FileCopyrightText: 2024 Thomas Bechtold <thomasbechtold@jpberlin.de>
#  SPDX-License-Identifier: GPL-3.0-or-later

import logging
import subprocess
from typing import List, Optional, Dict, Tuple


logger = logging.getLogger(__name__)


def run_command(
    cmd: List[str], env: Optional[Dict[str, str]] = None, cwd: Optional[str] = None, shell=False, success_codes=[0]
) -> Tuple[str, str]:
    """
    Run a command and return the output
    """
    logger.info(f'Running command: {" ".join(cmd)}')
    if shell is True:
        result = subprocess.run(" ".join(cmd), cwd=cwd, env=env, capture_output=True, shell=shell)
    else:
        result = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, shell=shell)
    if result.returncode not in success_codes:
        logger.error(f"Command failed with return code {result.returncode} (success codes are: {success_codes})")
        logger.error(f"Env: {env}")
        logger.error(f"Cwd: {cwd}")
        logger.error(f"Stdout: {result.stdout.decode()}")
        logger.error(f"Stderr: {result.stderr.decode()}")
        raise subprocess.CalledProcessError(result.returncode, cmd)
    logger.debug(f"Stdout: {result.stdout.decode()}")
    logger.debug(f"Stderr: {result.stderr.decode()}")
    return result.stdout.decode().strip(), result.stderr.decode().strip()
