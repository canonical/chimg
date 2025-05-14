import datetime
import os
import subprocess
import shutil
from pathlib import Path
import logging
from argparse import Namespace
import sys
import tempfile
from chimg.chroot import chrootfs_entry_point

logger = logging.getLogger(__name__)


class ImageCustomizer:
    def __init__(
        self,
        *,
        input_image_file: str | Path,
        output_image_path: str | Path,
        target_mount_point: str | Path,
        chimg_config_file: str | Path,
        overwrite: bool = False,
    ):
        """
        Initialize the ImageCustomizer with the input image file, output image path, and target mount point."

        Args:
            input_image_file (str | Path): The path to the input image file.
            output_image_path (str | Path): The path where the modified image will be saved.
            target_mount_point (str | Path): The mount point for the image.
            chimg_config_file (str | Path): The path to the chimg config file.
            overwrite (bool): Whether to overwrite existing output image files.
        """
        self.input_image_file = Path(input_image_file)
        self.output_image_path = Path(output_image_path)
        self.target_mount_point = Path(target_mount_point) if target_mount_point else Path(tempfile.mkdtemp(prefix="chimg-", suffix=datetime.now().strftime("%Y%m%d%H%M%S")))
        self.chimg_config_file = Path(chimg_config_file)
        self.overwrite = overwrite

        self.modified_image_file = self.input_image_file.with_suffix(".modifying")
        self.output_files_name = self.output_image_path.with_suffix("")
        self.input_image_type = ""
        self.resolv_conf_existed = False

        # Check if the output image file already exists
        if os.path.exists(self.output_image_path) and not self.overwrite:
            raise FileExistsError(
                f"Error: Output image file '{self.output_image_path}' already exists! Use overwrite=True to overwrite."
            )

    def _ensure_paths(self):
        # if the input image is just in the current directory, we dont need to create the directory
        if os.path.dirname(self.input_image_file) != "":
            os.makedirs(os.path.dirname(self.modified_image_file), exist_ok=True)
        os.makedirs(self.target_mount_point, exist_ok=True)

    def _remove_existing_modified_image(self):
        if os.path.exists(self.modified_image_file):
            os.remove(self.modified_image_file)
            logger.info("Removed existing modified image file")

    def _validate_input_image_exists(self):
        if not os.path.isfile(self.input_image_file):
            raise FileNotFoundError(f"Error: Input image file '{self.input_image_file}' not found!")

    def _convert_or_copy_image(self):
        file_info = subprocess.check_output(["file", self.input_image_file]).decode()
        if "QCOW" in file_info:
            logger.info("Converting input qcow2 image to raw image...")
            subprocess.run(
                ["qemu-img", "convert", "-f", "qcow2", "-O", "raw", self.input_image_file, self.modified_image_file],
                check=True,
            )
            self.input_image_type = "qcow2"
        else:
            logger.info("Image is already raw. Copying to %s", self.modified_image_file)
            shutil.copy(self.input_image_file, self.modified_image_file)
            self.input_image_type = "raw"
        logger.info("Converted or copied image for modifying to: %s", self.modified_image_file)

    def _get_partition_offset(self):
        fdisk_output = subprocess.check_output(["fdisk", "-l", self.modified_image_file]).decode()
        start_sector = next((line.split()[1] for line in fdisk_output.splitlines() if "Linux filesystem" in line), None)
        sector_size_line = next((line for line in fdisk_output.splitlines() if "Sector size" in line), None)
        sector_size = sector_size_line.split()[3] if sector_size_line else None

        if not start_sector or not sector_size:
            raise RuntimeError("Error: Could not determine partition offset!")

        offset = int(start_sector) * int(sector_size)
        return offset

    def _mount_image(self, offset):
        result = subprocess.run(
            [
                "sudo",
                "mount",
                "-o",
                f"loop,offset={offset}",  # noqa: E231
                self.modified_image_file,
                self.target_mount_point,
            ]
        )
        if result.returncode != 0:
            raise RuntimeError("Error: Failed to mount the image.")
        logger.info("Mounted successfully at %s", self.target_mount_point)

    def _handle_resolv_conf(self):
        resolv_path = os.path.join(self.target_mount_point, "etc", "resolv.conf")
        backup_path = f"{resolv_path}.bak"

        # Check if file or symlink exists
        if os.path.lexists(resolv_path):  # works for symlinks too
            logger.info("Backing up existing resolv.conf (may be a symlink)")
            try:
                subprocess.run(["sudo", "cp", "-a", resolv_path, backup_path], check=True)
                self.resolv_conf_existed = True
            except subprocess.CalledProcessError:
                logger.warning("Failed to backup resolv.conf. Proceeding without backup.")
                self.resolv_conf_existed = False

            subprocess.run(["sudo", "rm", "-f", resolv_path], check=True)

        # Always replace with host's resolv.conf as regular file
        subprocess.run(["sudo", "cp", "/etc/resolv.conf", resolv_path], check=True)
        subprocess.run(["sudo", "ls", "-l", resolv_path])

    def _restore_resolv_conf(self):
        resolv_path = os.path.join(self.target_mount_point, "etc", "resolv.conf")
        backup_path = f"{resolv_path}.bak"

        if self.resolv_conf_existed and os.path.exists(backup_path):
            logger.info("Restoring original resolv.conf")
            subprocess.run(["sudo", "rm", "-f", resolv_path], check=True)
            subprocess.run(["sudo", "mv", backup_path, resolv_path], check=True)
        else:
            logger.info("Removing temporary resolv.conf")
            subprocess.run(["sudo", "rm", "-f", resolv_path], check=True)

    def _unmount_image(self):
        logger.info("Unmounting image...")
        subprocess.run(["sudo", "umount", self.target_mount_point], check=True)
        subprocess.run(["sleep", "1"])

    def _produce_final_image(self):
        if os.path.exists(self.output_image_path):
            os.remove(self.output_image_path)
            logger.info("Removed existing output image file")

        if self.input_image_type == "qcow2":
            logger.info("Converting raw image back to qcow2 at: %s", self.output_image_path)
            subprocess.run(
                ["qemu-img", "convert", "-f", "raw", "-O", "qcow2", self.modified_image_file, self.output_image_path],
                check=True,
            )
        else:
            logger.info("Copying raw image to: %s", self.output_image_path)
            shutil.copy(self.modified_image_file, self.output_image_path)

        # Clean up the modified image file
        os.remove(self.modified_image_file)
        if os.path.exists(self.modified_image_file):
            logger.warning("Failed to remove modified image file.")
        else:
            logger.info("Removed temporary interim modified image file successfully.")

        logger.info("New image is available at: %s", self.output_image_path)

    def setup(self):
        logger.info("Setting up image customizer...")
        self._ensure_paths()
        self._remove_existing_modified_image()
        self._validate_input_image_exists()
        self._convert_or_copy_image()
        offset = self._get_partition_offset()
        self._mount_image(offset)
        self._handle_resolv_conf()
        logger.info("Image customizer setup complete!")

    def create_final_image(self):
        logger.info("Creating final image...")
        self._restore_resolv_conf()
        self._unmount_image()
        self._produce_final_image()
        logger.info("Done!")

    def main(self):
        self.setup()

        try:
            args = Namespace(
                config=self.chimg_config_file,
                rootfspath=self.target_mount_point,
                output_files_name=self.output_files_name,
                generate_sbom=False,
                overwrite=self.overwrite,
            )

            chrootfs_entry_point(args)
            logger.info("Succesfully invoked chimg chrootfs with config file: %s", self.chimg_config_file)

        except Exception as e:
            # Cleanup on failure
            self._unmount_image()
            self._remove_existing_modified_image()
            raise RuntimeError(f"Chimg logic failed: {e}") from e

        self.create_final_image()


def customize_image_entry_point(args) -> None:
    """
    Customize image according to the given config
    """
    if not os.path.exists(args.chimg_config_file):
        logger.error(f"chimg config file {args.chimg_config_file} does not exist")
        sys.exit(1)

    if not os.path.exists(args.input_image_file):
        logger.error(f"input image file {args.input_image_file} does not exist")
        sys.exit(1)

    customizer = ImageCustomizer(
        input_image_file=args.input_image_file,
        output_image_path=args.output_image_path,
        target_mount_point=args.target_mountpoint,
        chimg_config_file=args.chimg_config_file,
        overwrite=args.overwrite_output,
    )
    customizer.main()


# if __name__ == "__main__":

#     customizer = ImageCustomizer(
#         input_image_file="oracle-jammy-minimal-20250316.img",
#         output_image_path="chimg-modified-oracle-jammy-minimal-20250316.img",
#         target_mount_point="mount2",
#         chimg_config_file="add-cloud-init-daily-ppa.yaml",
#         overwrite=True,
#     )
#     customizer.main()
