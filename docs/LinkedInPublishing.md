# Publishing the LinkedIn SDK fork

The `Publish LinkedIn SDK` GitHub Actions workflow automatically builds, verifies,
and deploys the complete Maven reactor after a PR merges into `s3-li-2.23.3`.
Manual runs remain available and default to dry run. The destination is the existing
`https://linkedin.jfrog.io/artifactory/li-aws-sdk-java-v2` repository. ELR imports
the published coordinates into internal Artifactory separately. This is the same
publish-then-import model used by Ambry, not a direct upload to internal Artifactory.

## One-time administrator setup

1. Merge the workflow, release-check script, and this document into
   `s3-li-2.23.3`. The workflow must also be present on the repository's default
   branch (`master`) for GitHub to expose `workflow_dispatch`. Carry over these
   files only; do not merge the fork's release code into upstream master.
2. Configure the GitHub environment `jfrog-publish` to allow only the branch
   `s3-li-2.23.3`, not tags. Remove required reviewers to enable the requested
   unattended publication policy; environment settings are separate from YAML.
   This also removes the approval gate for manual uploads. Protect the release
   branch with reviewed PRs before enabling unattended publication: merged code
   runs with publishing authority, and other workflows on the allowed branch
   could also reference these environment secrets.
3. Add environment secrets `ARTIFACTORY_USER` and `ARTIFACTORY_PASSWORD`.
   The identity must have write access to the existing `li-aws-sdk-java-v2`
   repository. JFrog's **Set Me Up > Maven > Generate Token & Create Instructions**
   supplies the Maven username and identity token. Store that username in
   `ARTIFACTORY_USER` and the token in `ARTIFACTORY_PASSWORD`; the secret name does
   not require an account password. Do not paste credentials into code, logs, or
   chat. Revoke exposed tokens and replace the GitHub secret with a fresh token.
   Assign an owner to rotate credentials before expiry. A personal deploy grant
   may end before its token expires; replace temporary personal credentials with
   a publish-platform-approved automation identity. Do not assume service accounts
   or GitHub OIDC are already provisioned.
4. Ensure JFrog permissions prohibit overwriting release artifacts. The workflow
   serializes its own uploads and checks representative coordinates for existing
   or partial publication, but cannot atomically exclude another publisher.

No JFrog secrets are available to the existing pull-request build or release-selection
job. A release-branch push is eligible for automatic publication only if GitHub
associates its exact SHA with a merged PR targeting that branch in this repository.
Direct pushes and unmerged or differently targeted PRs do not publish. The workflow
checks out that immutable push SHA, never the unmerged PR head. Selection needs
read-only pull-request access; publishing retains read-only contents access.
Only the upload step receives JFrog credentials; Maven settings
contain environment references and are deleted at job completion. There is no
dependency cache in this credentialed workflow.

The workflow serializes builds and uploads and queues up to 100 pending runs.
GitHub cancels additional runs if that queue fills. Merging this workflow change
can itself trigger an upload, so complete credential rotation and repository
protection setup before enabling it.

## Automatic release

Each release PR must explicitly bump the final integer in the fork version,
for example `2.23.3-li-0.5` to `2.23.3-li-0.6`, consistently across the actual
reactor and profile POMs. The workflow publishes the committed version unchanged;
it does not generate versions, edit POMs, or commit version bumps back to the branch.
Preflight validates consistency and refuses an already-published version, so a PR
that retains a published version cannot publish again. Coordinate concurrent
release PRs so they do not reuse the same version.

Reruns use the same committed version: a completed or partially uploaded release is
refused rather than silently creating a new version. After validation, publication
requires a successful full-reactor `clean verify` and another absence check before
`deploy -DskipTests`. The version and source SHA appear in the run summary.
Do not merge further release changes blindly after a partial upload; follow the
recovery instructions below.

## Manual release or dry run

1. Commit the intended version consistently across the fork's POMs and review
   the release-branch changes. Preflight checks literal fork versions in the actual
   reactor and profile modules, excluding archetype templates and generated POMs.
   Manual runs require the requested version to match the committed POMs.
2. In Actions, select **Publish LinkedIn SDK**, choose branch `s3-li-2.23.3`,
   enter the exact version (initially `2.23.3-li-0.5`), and leave `dry_run=true`.
   Confirm the source SHA and successful full-reactor `clean verify`.
3. Dispatch the same reviewed commit/version with `dry_run=false` to upload without
   a separate environment approval. If the branch moved since the dry run, review
   the new SHA; both runs build the SHA selected when dispatched.
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
