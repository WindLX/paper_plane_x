from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.sync_version import sync_python_module_version


class SyncPythonModuleVersionTest(unittest.TestCase):
    def test_updates_public_module_version(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "__init__.py"
            path.write_text('__version__ = "0.1.0"\n', encoding="utf-8")

            sync_python_module_version(path, "0.1.8")

            self.assertEqual(
                path.read_text(encoding="utf-8"), '__version__ = "0.1.8"\n'
            )

    def test_rejects_module_without_version_field(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "__init__.py"
            path.write_text('"""Package."""\n', encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "Could not update __version__"):
                sync_python_module_version(path, "0.1.8")


if __name__ == "__main__":
    unittest.main()
