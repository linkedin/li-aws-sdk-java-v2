import importlib.util
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


if __name__ == "__main__":
    unittest.main()
