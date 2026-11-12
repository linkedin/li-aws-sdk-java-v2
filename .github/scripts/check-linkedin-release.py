"""Fail closed before building or publishing a LinkedIn SDK release."""

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path


NAMESPACE = {"m": "http://maven.apache.org/POM/4.0.0"}
REPOSITORY = "https://linkedin.jfrog.io/artifactory/li-aws-sdk-java-v2"
GITHUB_REPOSITORY = "linkedin/li-aws-sdk-java-v2"
RELEASE_REF = "refs/heads/s3-li-2.23.3"


def eligible_release(event, repository, ref, sha, pages):
    if repository != GITHUB_REPOSITORY or ref != RELEASE_REF:
        return False
    if event == "workflow_dispatch":
        return True
    if event != "push":
        return False
    return any(
        pull["merged_at"] is not None
        and pull["merge_commit_sha"] == sha
        and pull["base"]["ref"] == "s3-li-2.23.3"
        and pull["base"]["repo"]["full_name"] == GITHUB_REPOSITORY
        for page in pages
        for pull in page
    )


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
    return seen


def prepare_release(path, expected=None, opener=urllib.request.urlopen):
    pom = ET.parse(path).getroot()
    version = pom.findtext("m:version", namespaces=NAMESPACE) if expected is None else expected
    validate_pom(pom, version or "")
    validate_fork_versions(path, version)
    require_unpublished(version, opener)
    return version


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--select", action="store_true", help="Select manual runs and merged-PR pushes.")
    mode.add_argument("--prepare", action="store_true", help="Validate and output the committed release version.")
    args = parser.parse_args()
    if args.select:
        event = os.environ["GITHUB_EVENT_NAME"]
        pages = json.load(sys.stdin) if event == "push" else []
        eligible = eligible_release(
            event, os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_REF"], os.environ["GITHUB_SHA"], pages
        )
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
            output.write(f"eligible={str(eligible).lower()}\n")
        print("Release selected." if eligible else "No matching merged release PR; publishing skipped.")
        return
    expected = None if args.prepare and os.environ["GITHUB_EVENT_NAME"] == "push" else os.environ["RELEASE_VERSION"]
    version = prepare_release(Path("pom.xml"), expected)
    if args.prepare:
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
            output.write(f"version={version}\n")
    print(f"Validated unpublished LinkedIn SDK release {version}.")


if __name__ == "__main__":
    main()
