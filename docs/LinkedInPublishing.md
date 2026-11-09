# Publishing the LinkedIn SDK fork

The `Publish LinkedIn SDK` GitHub Actions workflow builds and verifies the complete
Maven reactor, then optionally deploys it to the existing
`https://linkedin.jfrog.io/artifactory/li-aws-sdk-java-v2` repository. ELR imports
the published coordinates into internal Artifactory separately. This is the same
publish-then-import model used by Ambry, not a direct upload to internal Artifactory.

## One-time administrator setup

1. Merge the workflow, release-check script, and this document into
   `s3-li-2.23.3`. The workflow must also be present on the repository's default
   branch (`master`) for GitHub to expose `workflow_dispatch`. Carry over these
   files only; do not merge the fork's release code into upstream master.
2. Create a GitHub environment named `jfrog-publish`. Require release-owner
   approval, prevent self-review where available, and restrict deployment branches
   to `s3-li-2.23.3`. Configure these protections **before enabling real uploads**;
   naming an environment in YAML does not configure its protections.
3. Add environment secrets `ARTIFACTORY_USER` and `ARTIFACTORY_PASSWORD`.
   The identity must have write access to the existing `li-aws-sdk-java-v2`
   repository. The private-fork guidelines currently document the JFrog profile's
   **encrypted password**, not an API key, for Maven publication. Obtain it through
   the approved process; do not paste it into code, logs, or chat.
   A repository-authorized publisher such as Shan can provision these secrets.
   They need not be Cris's credentials. Ask publish-platform for a supported
   automation identity/rotation process rather than assuming a service account
   or GitHub OIDC is already supported.
4. Ensure JFrog permissions prohibit overwriting release artifacts. The workflow
   serializes its own uploads and checks representative coordinates for existing
   or partial publication, but cannot atomically exclude another publisher.

No secrets are available to the existing pull-request build. Publishing is manual,
restricted to this repository and release branch, and uses the dispatch commit's
immutable SHA. Only the upload step receives JFrog credentials; Maven settings
contain environment references and are deleted at job completion. There is no
dependency cache in this credentialed workflow.

## Release

1. Commit the intended version consistently across the fork's POMs and review
   the release-branch changes. Preflight checks literal fork versions in the actual
   reactor and profile modules, excluding archetype templates and generated POMs.
   The workflow does not bump versions or create tags.
2. In Actions, select **Publish LinkedIn SDK**, choose branch `s3-li-2.23.3`,
   enter the exact version (initially `2.23.3-li-0.5`), and leave `dry_run=true`.
   Confirm the source SHA and successful full-reactor `clean verify`.
3. Dispatch the same reviewed commit/version with `dry_run=false`, then obtain
   the environment approval. If the branch moved since the dry run, review the
   new SHA; both runs build the SHA selected when dispatched.
4. The workflow checks the root version and destination, refuses representative
   existing release coordinates, runs `clean verify`, then runs `deploy` for the
   complete reactor. The deploy invocation skips unit tests already run by verify.
   It does not activate the upstream `publishing` profile, which targets Sonatype.
5. Confirm Maven reports success for the complete reactor and inspect the published
   parent/BOM, S3 and Netty POMs, JARs, and normal attached artifacts in JFrog.
   Maven deployment is not transactional. If it fails partway, stop and have the
   repository owner assess the uploaded artifacts; do not bypass the preflight
   or blindly overwrite a partial release.
6. Confirm ELR import (or request it through go/elr). Observe the seven-day
   dependency cooldown or obtain an incident exception before consumption.
   Update the consumer dependencies and verify the actual resolved
   `netty-nio-client` version; publication alone does not roll the fix out.

## Local workflow checks

```bash
python3 -m unittest discover -s .github/scripts -p 'test_*.py'
RELEASE_VERSION=2.23.3-li-0.5 python3 .github/scripts/check-linkedin-release.py
```

The second command makes read-only requests to JFrog; it never uploads artifacts.
