"""Include the already-built interface in both wheel and source installations."""

import shutil
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py


class WebBuild(build_py):
    def run(self):
        source = Path(__file__).parent / "web/dist"
        if not (source / "index.html").is_file():
            raise RuntimeError(
                "Build the interface first: cd web && npm ci && npm run build"
            )
        super().run()
        destination = Path(self.build_lib) / "agentdock/static"
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(source, destination)


setup(cmdclass={"build_py": WebBuild})
