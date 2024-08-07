import pathlib
import glob
from chimg import context

curdir = pathlib.Path(__file__).parent.resolve()


def test_config_samples():
    """
    Test the available config samples from the docs directory
    to make sure those configs are valid
    """
    config_samples_dir = curdir.parents[1] / "docs" / "config-samples"
    for f in glob.glob(f"{config_samples_dir}/*.yaml"):
        context.Context(config_samples_dir / f, None)
