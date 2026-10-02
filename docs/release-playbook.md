# CKF Hard Mode release playbook

Use this checklist to take a finished tuning/configuration state through validation, packaging, Git, and a GitHub Release. It is written for the maintainer checkout at `D:\ckf-data-modding` and the default Cyber Knights: Flashpoint installation path.

For explanations of the build system and version model, see [Workflow](workflow.md). For commands that intentionally exit non-zero, see [Gotchas: Build and release](gotchas.md#build--release).

All command blocks below use `cmd.exe` syntax. Replace `X.Y.Z`, `OLD.VERSION`, `FULL_COMMIT_SHA`, and `RELEASE NOTES` before running a command that contains them.

## 1. Validate the live tuning

Run both validators against the live game configuration and a complete Data Dump:

```bat
cd /d "D:\ckf-data-modding"
python schema\check_schema.py --game "C:\Program Files (x86)\Steam\steamapps\common\Cyber Knights Flashpoint"
python scripts\validate_rules.py --game "C:\Program Files (x86)\Steam\steamapps\common\Cyber Knights Flashpoint" --dump "D:\ckf-data-modding\sheets\raw"
```

Do not continue until `check_schema.py` reports zero problems and `validate_rules.py` reports no errors. Review warnings against [Gotchas](gotchas.md); some documented gates intentionally exit non-zero. Do not run `validate_rules.py --game` without `--dump`: this checkout's dump is not in the default game path, so that invocation is expected to refuse.

## 2. Set the public version

The public version must be updated in:

- `mods\CKFHardMode\CKFHardMode.csproj` (`<Version>`)
- `mods\CKFHardMode\Plugin.cs` (`PluginVersion`)
- `gui\serve.py` (`MIGRATION_PLUGIN_VERSION`)
- Current-version prose in the README and subsystem documentation

Find every current declaration before editing:

```bat
cd /d "D:\ckf-data-modding"
rg -n "<Version>|PluginVersion =|MIGRATION_PLUGIN_VERSION =|public plugin version|plugin identifies itself|Current declarations: plugin version" README.md docs gui mods schema
rg -n -F "OLD.VERSION" README.md docs gui mods schema
```

The second search catches prose whose wording is not covered by the declaration search. Review every remaining old-version reference; keep only intentional historical references.

`Defaults.DocVersion` is independent of the public version. Change it, `MIGRATION_DOC_VERSION`, and all ten settings-document `_version` values only when the settings document shape changes. The version rules and checks are described in [Workflow: Maintain the two versions](workflow.md#maintain-the-two-versions).

## 3. Check generated files

```bat
cd /d "D:\ckf-data-modding"
python scripts\gen_binds.py --check
python scripts\gen_cfg_template.py --check
python scripts\gen_teampl_labels.py --check --config "C:\Program Files (x86)\Steam\steamapps\common\Cyber Knights Flashpoint\BepInEx\config"
```

If a generated file is stale, run that generator again without `--check`, review its diff, and rerun the check. Never hand-edit a generated file.

## 4. Rebuild when required

Rebuild after changing C# source, the project version, or anything else compiled into `CKFHardMode.dll`:

```bat
cd /d "D:\ckf-data-modding"
dotnet build -c Release -p:GameDir="C:\Program Files (x86)\Steam\steamapps\common\Cyber Knights Flashpoint" "D:\ckf-data-modding\mods\CKFHardMode\CKFHardMode.csproj"
```

Require a successful build with zero errors. With the game directory present, the project deploys the DLL to `BepInEx\plugins`. Tuning-only and documentation-only changes do not require this build.

## 5. Build the release archive

```bat
cd /d "D:\ckf-data-modding"
python scripts\make_release.py
```

The archive is written to:

```text
D:\ckf-data-modding\dist\CKF-Hard-Mode-X.Y.Z.zip
```

The builder must finish without a refusal. `dist\` is ignored by Git; the ZIP is published as a GitHub Release asset, not committed to the repository.

## 6. Verify the release archive

Run the release-builder self-test and calculate the archive digest:

```bat
cd /d "D:\ckf-data-modding"
python scripts\make_release.py --selftest --config "C:\Program Files (x86)\Steam\steamapps\common\Cyber Knights Flashpoint\BepInEx\config"
certutil -hashfile "D:\ckf-data-modding\dist\CKF-Hard-Mode-X.Y.Z.zip" SHA256
```

Record the SHA-256 digest with the release notes. Also confirm that the archive name contains the intended version and that the release builder reports the expected DLL and configuration versions.

## 7. Stage and inspect the source release

```bat
cd /d "D:\ckf-data-modding"
git add -A
git status --short
git --no-pager diff --cached --stat
git diff --cached --check
```

Before committing:

- Inspect every added and deleted path.
- Confirm no live tuning, dump output, logs, vendor payload, or `dist\` artifact is staged.
- Require `git diff --cached --check` to print nothing.
- Treat Git's LF/CRLF working-copy warning as informational; the staged diff and `git diff --cached --check` are the gates.

## 8. Commit the source release

```bat
git commit -m "Release X.Y.Z"
git status --short --branch
git log -1 --oneline
git rev-parse HEAD
```

Save the full commit SHA printed by `git rev-parse HEAD`. The release tag must target that exact commit.

## 9. Push the source release

```bat
git push origin main
git status --short --branch
```

The final status should be:

```text
## main...origin/main
```

Do not publish the GitHub Release until the source commit is on `origin/main`.

## 10. Check GitHub authentication and the tag name

```bat
gh auth status
gh release view vX.Y.Z --repo PhreakTurley/ckf-hardmode
```

Before publication, `release not found` is the expected result of the second command. If the release already exists, stop and inspect it instead of creating a duplicate.

## 11. Publish the GitHub Release

```bat
gh release create vX.Y.Z "D:\ckf-data-modding\dist\CKF-Hard-Mode-X.Y.Z.zip" --repo PhreakTurley/ckf-hardmode --target FULL_COMMIT_SHA --title "CKF Hard Mode X.Y.Z" --notes "RELEASE NOTES" --latest
```

Release notes should summarize player-visible changes and include any upgrade or backup instructions. The asset path must name the archive produced and verified in steps 5 and 6.

## 12. Verify the published release

```bat
gh release view vX.Y.Z --repo PhreakTurley/ckf-hardmode
git fetch --tags
git tag --list vX.Y.Z
git rev-list -n 1 vX.Y.Z
git status --short --branch
```

Confirm all of the following:

- The release is public and marked latest.
- The tag is `vX.Y.Z` and targets the saved source commit.
- `CKF-Hard-Mode-X.Y.Z.zip` is attached.
- GitHub's asset digest matches the SHA-256 recorded in step 6.
- `main` remains synchronized with `origin/main`.

The release is complete only after all five checks pass.
