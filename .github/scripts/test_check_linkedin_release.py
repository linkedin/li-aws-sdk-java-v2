import copy
import importlib.util
import json
import subprocess
import sys
import unittest
import urllib.error
import xml.etree.ElementTree as ET
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock


SPEC = importlib.util.spec_from_file_location("release", Path(__file__).with_name("check-linkedin-release.py"))
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)
VERSION = "2.23.3-li-0.5"


class ReleaseCheckTest(unittest.TestCase):
    def pom(self):
        return ET.fromstring(
            '<project xmlns="http://maven.apache.org/POM/4.0.0">'
            '<groupId>software.amazon.awssdk</groupId><artifactId>aws-sdk-java-pom</artifactId>'
            f'<version>{VERSION}</version>'
            '<distributionManagement><repository><id>central</id>'
            f'<url>{release.REPOSITORY}</url>'
            '</repository></distributionManagement></project>'
        )

    def test_valid_version_and_destination(self):
        pom = self.pom()
        pom.find("m:version", release.NAMESPACE).text = VERSION
        release.validate_pom(pom, VERSION)

    def test_rejects_invalid_or_mismatched_version(self):
        for version in ("", "2.23.3-li-0.5-SNAPSHOT", "$(echo bad)", "2.23.3-li-0.999"):
            with self.subTest(version=version), self.assertRaises(ValueError):
                release.validate_pom(self.pom(), version)

    def test_rejects_wrong_destination_or_identity(self):
        for path in (
            "m:groupId",
            "m:artifactId",
            "m:distributionManagement/m:repository/m:id",
            "m:distributionManagement/m:repository/m:url",
        ):
            pom = self.pom()
            pom.find("m:version", release.NAMESPACE).text = VERSION
            pom.find(path, release.NAMESPACE).text = "wrong"
            with self.subTest(path=path), self.assertRaises(ValueError):
                release.validate_pom(pom, VERSION)

    def test_checks_all_representative_artifacts(self):
        opener = MagicMock(side_effect=urllib.error.HTTPError("url", 404, "missing", {}, None))
        release.require_unpublished(VERSION, opener)
        self.assertEqual(opener.call_count, 4)
        for call, artifact in zip(opener.call_args_list, ("aws-sdk-java-pom", "bom", "s3", "netty-nio-client")):
            self.assertTrue(call.args[0].endswith(f"/{artifact}/{VERSION}/{artifact}-{VERSION}.pom"))

    def test_rejects_stale_fork_version_in_a_module(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "pom.xml"
            path.write_text(
                '<project xmlns="http://maven.apache.org/POM/4.0.0">'
                '<parent><version>2.23.3-li-0.4</version></parent></project>'
            )
            with self.assertRaisesRegex(ValueError, "Inconsistent fork version"):
                release.validate_fork_versions(path, VERSION)
            path.write_text(path.read_text().replace("2.23.3-li-0.4", VERSION))
            release.validate_fork_versions(path, VERSION)

    def test_checks_modules_and_profile_modules_not_archetype_templates(self):
        for modules in (
            "<modules><module>child</module></modules>",
            "<profiles><profile><modules><module>child</module></modules></profile></profiles>",
        ):
            with self.subTest(modules=modules), TemporaryDirectory() as directory:
                root = Path(directory)
                (root / "pom.xml").write_text(
                    f'<project xmlns="http://maven.apache.org/POM/4.0.0">{modules}</project>'
                )
                (root / "child").mkdir()
                (root / "child/pom.xml").write_text(
                    '<project xmlns="http://maven.apache.org/POM/4.0.0">'
                    '<version>2.23.3-li-0.4</version></project>'
                )
                (root / "template").mkdir()
                (root / "template/pom.xml").write_text("not an actual Maven POM")
                with self.assertRaisesRegex(ValueError, "Inconsistent fork version"):
                    release.validate_fork_versions(root / "pom.xml", VERSION)
                (root / "child/pom.xml").write_text((root / "child/pom.xml").read_text().replace("0.4", "0.5"))
                release.validate_fork_versions(root / "pom.xml", VERSION)

    def test_rejects_existing_or_partial_release(self):
        opener = MagicMock()
        opener.side_effect = [
            urllib.error.HTTPError("url", 404, "missing", {}, None),
            MagicMock(),
        ]
        with self.assertRaisesRegex(ValueError, "already exists"):
            release.require_unpublished(VERSION, opener)

    def test_auth_server_and_transport_errors_do_not_mean_absent(self):
        for code in (401, 403, 429, 500):
            opener = MagicMock(side_effect=urllib.error.HTTPError("url", code, "error", {}, None))
            with self.subTest(code=code), self.assertRaises(ValueError):
                release.require_unpublished(VERSION, opener)
        with self.assertRaises(urllib.error.URLError):
            release.require_unpublished(VERSION, MagicMock(side_effect=urllib.error.URLError("network failure")))

    def test_selects_only_manual_runs_or_merged_release_commits(self):
        sha = "a" * 40
        pull = {
            "merged_at": "2026-11-10T00:00:00Z",
            "merge_commit_sha": sha,
            "base": {"ref": "s3-li-2.23.3", "repo": {"full_name": release.GITHUB_REPOSITORY}},
        }
        self.assertTrue(
            release.eligible_release("workflow_dispatch", release.GITHUB_REPOSITORY, release.RELEASE_REF, sha, [])
        )
        self.assertTrue(
            release.eligible_release("push", release.GITHUB_REPOSITORY, release.RELEASE_REF, sha, [[], [pull]])
        )
        for event, repository, ref, pages in (
            ("push", release.GITHUB_REPOSITORY, release.RELEASE_REF, []),
            ("pull_request", release.GITHUB_REPOSITORY, release.RELEASE_REF, [[pull]]),
            ("push", "someone/fork", release.RELEASE_REF, [[pull]]),
            ("workflow_dispatch", release.GITHUB_REPOSITORY, "refs/heads/master", []),
            ("push", release.GITHUB_REPOSITORY, "refs/tags/s3-li-2.23.3", [[pull]]),
        ):
            with self.subTest(event=event, repository=repository, ref=ref):
                self.assertFalse(release.eligible_release(event, repository, ref, sha, pages))
        for key, value in (
            ("merged_at", None),
            ("merge_commit_sha", "b" * 40),
            ("base", {"ref": "master", "repo": {"full_name": release.GITHUB_REPOSITORY}}),
            ("base", {"ref": "s3-li-2.23.3", "repo": {"full_name": "someone/fork"}}),
        ):
            other = copy.deepcopy(pull)
            other[key] = value
            with self.subTest(key=key, value=value):
                self.assertFalse(
                    release.eligible_release("push", release.GITHUB_REPOSITORY, release.RELEASE_REF, sha, [[other]])
                )

    def test_selection_cli_writes_github_outputs(self):
        with TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            for event, expected in (("push", "false"), ("workflow_dispatch", "true")):
                subprocess.run(
                    [sys.executable, SPEC.origin, "--select"],
                    input=json.dumps([]),
                    capture_output=True,
                    text=True,
                    check=True,
                    env={
                        "GITHUB_EVENT_NAME": event,
                        "GITHUB_REPOSITORY": release.GITHUB_REPOSITORY,
                        "GITHUB_REF": release.RELEASE_REF,
                        "GITHUB_SHA": "a" * 40,
                        "GITHUB_OUTPUT": str(output),
                        "PYTHONDONTWRITEBYTECODE": "1",
                    },
                )
                self.assertEqual(output.read_text(), f"eligible={expected}\n")
                output.unlink()

    def test_prepares_all_reactor_and_profile_poms_without_changing_templates(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            pom = self.pom()
            modules = ET.SubElement(pom, f"{{{release.NAMESPACE['m']}}}modules")
            ET.SubElement(modules, f"{{{release.NAMESPACE['m']}}}module").text = "child"
            profiles = ET.SubElement(pom, f"{{{release.NAMESPACE['m']}}}profiles")
            profile = ET.SubElement(profiles, f"{{{release.NAMESPACE['m']}}}profile")
            profile_modules = ET.SubElement(profile, f"{{{release.NAMESPACE['m']}}}modules")
            ET.SubElement(profile_modules, f"{{{release.NAMESPACE['m']}}}module").text = "profile-child"
            (root / "pom.xml").write_text(ET.tostring(pom, encoding="unicode"))
            for name in ("child", "profile-child"):
                (root / name).mkdir()
                (root / name / "pom.xml").write_text(
                    '<project xmlns="http://maven.apache.org/POM/4.0.0">'
                    '<!-- Preserve formatting and non-fork dependencies. -->\n'
                    f'<parent><version>{VERSION}</version></parent>'
                    f'<dependencies><dependency><version>{VERSION}</version></dependency>'
                    '<dependency><version>1.0</version></dependency></dependencies></project>'
                )
            (root / "template").mkdir()
            (root / "template/pom.xml").write_text(f"template {VERSION}")
            opener = MagicMock(side_effect=urllib.error.HTTPError("url", 404, "missing", {}, None))
            version = release.prepare_release(root / "pom.xml", "42918591349", opener)
            self.assertEqual(version, "2.23.3-li-0.42918591349")
            self.assertEqual(len(release.validate_fork_versions(root / "pom.xml", version)), 3)
            self.assertNotIn(VERSION, (root / "child/pom.xml").read_text())
            self.assertIn("<!-- Preserve formatting", (root / "child/pom.xml").read_text())
            self.assertIn("<version>1.0</version>", (root / "child/pom.xml").read_text())
            self.assertEqual((root / "template/pom.xml").read_text(), f"template {VERSION}")
            self.assertEqual(opener.call_count, 4)

    def test_invalid_run_id_or_existing_release_does_not_change_poms(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "pom.xml"
            original = ET.tostring(self.pom(), encoding="unicode")
            path.write_text(original)
            for run_id in ("", "0", "-1", "123\nother=value", "$(echo unsafe)"):
                opener = MagicMock()
                with self.subTest(run_id=run_id), self.assertRaises(ValueError):
                    release.prepare_release(path, run_id, opener)
                opener.assert_not_called()
                self.assertEqual(path.read_text(), original)
            for opener in (
                MagicMock(),
                MagicMock(side_effect=urllib.error.HTTPError("url", 403, "forbidden", {}, None)),
                MagicMock(side_effect=urllib.error.URLError("network failure")),
            ):
                with self.assertRaises((ValueError, urllib.error.URLError)):
                    release.prepare_release(path, "42918591349", opener)
                self.assertEqual(path.read_text(), original)

    def test_preparation_fails_before_network_for_inconsistent_source_versions(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "pom.xml"
            pom = self.pom()
            dependency = ET.SubElement(pom, f"{{{release.NAMESPACE['m']}}}dependency")
            ET.SubElement(dependency, f"{{{release.NAMESPACE['m']}}}version").text = "2.23.3-li-0.4"
            path.write_text(ET.tostring(pom, encoding="unicode"))
            opener = MagicMock()
            with self.assertRaisesRegex(ValueError, "Inconsistent fork version"):
                release.prepare_release(path, "42918591349", opener)
            opener.assert_not_called()

    def test_reruns_keep_the_same_version(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "pom.xml"
            original = ET.tostring(self.pom(), encoding="unicode")
            versions = []
            for _ in range(2):
                path.write_text(original)
                opener = MagicMock(side_effect=urllib.error.HTTPError("url", 404, "missing", {}, None))
                versions.append(release.prepare_release(path, "42918591349", opener))
            self.assertEqual(versions[0], versions[1])


if __name__ == "__main__":
    unittest.main()
