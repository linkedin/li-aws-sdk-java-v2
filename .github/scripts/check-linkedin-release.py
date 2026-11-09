"""Fail closed before building or publishing a LinkedIn SDK release."""

import os
import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path


NAMESPACE = {"m": "http://maven.apache.org/POM/4.0.0"}
REPOSITORY = "https://linkedin.jfrog.io/artifactory/li-aws-sdk-java-v2"


def validate_pom(pom, expected):
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+-li-[0-9]+\.[0-9]+", expected):
        raise ValueError("Expected a release version such as 2.23.3-li-0.5, not a snapshot.")
    if pom.findtext("m:version", namespaces=NAMESPACE) != expected:
        raise ValueError("Requested version does not match the checked-out root POM.")
    if pom.findtext("m:groupId", namespaces=NAMESPACE) != "software.amazon.awssdk":
        raise ValueError("Unexpected Maven group.")
    if pom.findtext("m:artifactId", namespaces=NAMESPACE) != "aws-sdk-java-pom":
        raise ValueError("Run this check from the SDK repository root.")
    repository = pom.find("m:distributionManagement/m:repository", NAMESPACE)
    if repository is None:
        raise ValueError("Missing release repository.")
    if (
        repository.findtext("m:id", namespaces=NAMESPACE) != "central"
        or repository.findtext("m:url", namespaces=NAMESPACE) != REPOSITORY
    ):
        raise ValueError("Release destination must be the existing LinkedIn SDK JFrog repository.")


def require_unpublished(version, opener=urllib.request.urlopen):
    # Representative coordinates also catch common partially published releases.
    # This is not an atomic reservation; JFrog must independently deny release overwrites.
    for artifact in ("aws-sdk-java-pom", "bom", "s3", "netty-nio-client"):
        url = f"{REPOSITORY}/software/amazon/awssdk/{artifact}/{version}/{artifact}-{version}.pom"
        try:
            with opener(url, timeout=30):
                raise ValueError(f"{artifact}:{version} already exists. Do not overwrite or blindly retry.")
        except urllib.error.HTTPError as error:
            if error.code != 404:
                raise ValueError(f"Cannot establish absence of {artifact}: HTTP {error.code}") from error


def validate_fork_versions(path, expected, seen=None):
    if seen is None:
        seen = set()
    path = path.resolve()
    if path not in seen:
        seen.add(path)
        pom = ET.parse(path).getroot()
        for node in pom.findall(".//m:version", NAMESPACE):
            if node.text and "-li-" in node.text and node.text != expected:
                raise ValueError(f"Inconsistent fork version {node.text} in {path}.")
        modules = pom.findall("m:modules/m:module", NAMESPACE)
        modules += pom.findall("m:profiles/m:profile/m:modules/m:module", NAMESPACE)
        for module in modules:
            validate_fork_versions(path.parent / module.text / "pom.xml", expected, seen)


def main():
    version = os.environ["RELEASE_VERSION"]
    validate_pom(ET.parse(Path("pom.xml")).getroot(), version)
    validate_fork_versions(Path("pom.xml"), version)
    require_unpublished(version)
    print(f"Validated unpublished LinkedIn SDK release {version}.")


if __name__ == "__main__":
    main()
