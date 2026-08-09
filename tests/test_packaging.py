from __future__ import annotations

import tomllib
import unittest
from pathlib import Path


class PackagingDependencyTests(unittest.TestCase):
    def test_trademark_dependency_tracks_main_branch(self) -> None:
        pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
        project = tomllib.loads(pyproject.read_text())
        dependencies = project["project"]["dependencies"]
        self.assertIn(
            "apache-trademark-mcp @ git+https://github.com/justinmclean/TrademarkMCP.git@main",
            dependencies,
        )


if __name__ == "__main__":
    unittest.main()
