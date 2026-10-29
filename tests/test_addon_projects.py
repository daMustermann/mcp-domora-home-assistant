"""Exercise app project operations without a Home Assistant installation."""

import importlib.util
from pathlib import Path
import tempfile
import unittest

SOURCE = Path(__file__).parents[1] / "custom_components/mcp_domora/addon_projects.py"
spec = importlib.util.spec_from_file_location("addon_projects", SOURCE)
projects = importlib.util.module_from_spec(spec)
spec.loader.exec_module(projects)


class ProjectTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name

    def test_create_read_update_and_list(self):
        created = projects.create_project(self.root, "my_app", "My app", "Example app")
        self.assertEqual(created["project"], "my_app")
        self.assertEqual(projects.list_projects(self.root)["projects"], ["my_app"])
        self.assertEqual(len(projects.list_files(self.root, "my_app")["files"]), 4)
        self.assertIn(
            "slug: my_app",
            projects.read_file(self.root, "my_app", "my_app/config.yaml")["content"],
        )
        with self.assertRaises(projects.ProjectError):
            projects.write_files(self.root, "my_app", {"my_app/run.sh": "changed"})
        projects.write_files(
            self.root, "my_app", {"my_app/run.sh": "changed"}, overwrite=True
        )
        self.assertEqual(
            projects.read_file(self.root, "my_app", "my_app/run.sh")["content"],
            "changed",
        )
        projects.delete_file(self.root, "my_app", "my_app/run.sh")
        self.assertNotIn(
            "my_app/run.sh", projects.list_files(self.root, "my_app")["files"]
        )

    def test_create_existing_project_does_not_overwrite(self):
        projects.create_project(self.root, "demo", "Demo", "Description")
        with self.assertRaises(projects.ProjectError):
            projects.create_project(self.root, "demo", "Changed", "Description")
        self.assertIn(
            "Demo", projects.read_file(self.root, "demo", "repository.yaml")["content"]
        )

    def test_paths_cannot_escape_workspace(self):
        projects.create_project(self.root, "demo", "Demo", "Description")
        for path in (
            "../outside",
            "/absolute",
            "sub/../../escape",
            ".git/config",
            "sub\\file",
        ):
            with self.subTest(path=path), self.assertRaises(projects.ProjectError):
                projects.write_files(self.root, "demo", {path: "no"})
        self.assertFalse((Path(self.root) / "outside").exists())

    def test_invalid_slug_and_large_files_rejected(self):
        for slug in ("../outside", "UPPER", "", "a/b"):
            with self.subTest(slug=slug), self.assertRaises(projects.ProjectError):
                projects.create_project(self.root, slug, "Demo", "Description")
        projects.create_project(self.root, "demo", "Demo", "Description")
        with self.assertRaises(projects.ProjectError):
            projects.write_files(
                self.root, "demo", {"large": "a" * (projects.MAX_FILE_BYTES + 1)}
            )

    def test_batch_validation_prevents_partial_write_for_invalid_paths(self):
        projects.create_project(self.root, "demo", "Demo", "Description")
        with self.assertRaises(projects.ProjectError):
            projects.write_files(self.root, "demo", {"new.txt": "new", "../bad": "bad"})
        with self.assertRaises(projects.ProjectError):
            projects.read_file(self.root, "demo", "new.txt")


if __name__ == "__main__":
    unittest.main()
