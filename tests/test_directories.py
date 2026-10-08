import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agentdock.directories import list_directories


class DirectoryTests(unittest.TestCase):
    def test_lists_only_directories_on_the_selected_machine_without_writes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            (root / "project").mkdir()
            (root / "private-file").write_text("must not be returned")
            (root / "link").symlink_to(root / "project", target_is_directory=True)
            with patch.dict("os.environ", {"HOME": str(root)}):
                result = list_directories("~")
            self.assertEqual(result["path"], str(root))
            self.assertEqual(
                [item["name"] for item in result["directories"]], ["link", "project"]
            )
            self.assertNotIn("must not be returned", str(result))
            self.assertEqual(
                list_directories(str(root / "link"))["path"], str(root / "project")
            )
            for value in (
                "relative",
                "/bad\x00path",
                str(root / "missing"),
                str(root / "private-file"),
                None,
            ):
                with self.assertRaises(ValueError):
                    list_directories(value)
            self.assertEqual(
                sorted(p.name for p in root.iterdir()),
                ["link", "private-file", "project"],
            )

    def test_directory_listing_is_bounded(self):
        with tempfile.TemporaryDirectory() as temporary:
            for index in range(201):
                (Path(temporary) / str(index)).mkdir()
            result = list_directories(temporary)
            self.assertEqual(len(result["directories"]), 200)
            self.assertTrue(result["truncated"])
