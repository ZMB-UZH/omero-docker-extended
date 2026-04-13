# Repository Sync Safety

This document defines the safe procedure for copying tracked file content between related repositories without contaminating branch history.

Use this document whenever the goal is "make repository B contain the latest files from repository A" while keeping repository B's own branch graph intact.

## Core Rule

Treat cross-repository updates as a **tree-content synchronization** problem, not as a branch-history integration problem.

That means:

- the destination repository keeps its own ancestry,
- the source repository provides file content only,
- the resulting sync is recorded as a normal commit in the destination repository,
- foreign branch history is never merged into the destination branch unless a human explicitly requests that outcome.

## Hard Rules

1. Never run `git merge`, `git pull`, or `git rebase` from one repository into another repository's long-lived branch just to copy files.
2. Never normalize a widespread ahead/behind explosion by rewriting many old branches one-by-one unless the human explicitly requests that scope.
3. Always back up any branch you may rewrite under `backup/<date>-<reason>/...` before a force update.
4. Always use `--force-with-lease`, never plain `--force`, when moving a live branch tip.
5. Resolve the destination remote's default branch explicitly before any push, and use that branch unless the human explicitly names a different target.
6. Never choose the remote target branch by copying the current local branch name.
7. If the sync must exclude specific files, preserve those exclusions explicitly in the temporary destination clone before committing.

## Pre-Sync Safety Check (mandatory)

Before **any** file-sync, rsync, or tree-replacement operation, run:

```bash
python3 tools/env_safety_guard.py check
python3 tools/env_safety_guard.py compose-guard
python3 tools/env_safety_guard.py backup
```

The first command verifies every file listed in `.env_manifest` exists and is non-empty.
The second refuses `docker compose` from a non-canonical checkout whose repository root or `.env` project name does not match the declared installation.
The third creates a timestamped backup under `.env_backups/`.

If the check fails, **stop immediately** and investigate.

To restore after an accidental deletion:

```bash
python3 tools/env_safety_guard.py restore
```

## Safe Sync Procedure

1. Run `python3 tools/env_safety_guard.py check && python3 tools/env_safety_guard.py compose-guard && python3 tools/env_safety_guard.py backup`.
2. Fetch the latest source and destination refs.
3. Resolve the destination remote's default branch explicitly.
   - Example: `git remote show <remote>` and read `HEAD branch: ...`
   - If the human did not explicitly name a target branch, use that default branch.
4. Inspect ancestry before changing anything:
   - `git merge-base <destination-branch> <source-ref>`
   - `git rev-list --max-parents=0 <destination-branch>`
   - `git rev-list --max-parents=0 <source-ref>`
5. Create a disposable clone or temporary worktree from the **destination** repository and check out the destination branch there.
6. Replace the destination tree contents from the source tree in that disposable clone.
   - Use tree-copy approaches such as `git checkout <source-ref> -- .`, `git archive`, or equivalent file-level sync in the temporary destination clone.
   - Do **not** merge the source branch history into the destination branch.
7. Restore explicitly excluded paths to their destination-repository state, or remove them if they must stay absent.
8. Review the staged diff to confirm it is a content diff, not a history rewrite.
9. Commit in the destination repository.
10. Push the destination commit normally to the verified destination branch.

## Hard Stop Signals

Stop and switch to recovery mode if any of the following is true:

- `git merge-base` is empty between the current destination branch and a branch that used to line up.
- A recent sync suddenly makes many older branches show thousands of commits ahead/behind.
- Only a small recent branch family shares the new lineage while the older branch set remains on another line.
- The proposed "sync" requires merging unrelated root histories.

Those are signs of branch-history contamination, not a routine file-copy task.

## Recovery Procedure For Recent Branch-Root Drift

When one recent rewrite causes a large set of older branches to drift wildly:

1. Back up the currently live branch tips before touching them.
2. Identify the last stable tip on the intended destination-repository line, before the accidental history change.
3. Rebuild the intended recent work on top of that stable tip in a disposable clone.
   - Prefer replaying the small recent branch family.
   - Do not rewrite hundreds of older branches if the fault came from one recent branch-root change.
4. Verify the rebuilt line locally:
   - sample ahead/behind counts should collapse back to small numbers,
   - the rebuilt branch should share the expected stable ancestor with the older branch family,
   - the current live branch and the rebuilt branch should differ only by the intended recent content changes.
5. Update only the affected recent branches with `--force-with-lease`.
6. Confirm the repaired refs on the remote before deleting any backup branches.

## Incident Reference: 2026-04-07 Branch-Root Contamination

On 2026-04-07 a cross-repository file sync pushed a commit whose ancestry came
from the **source** repository's branch graph instead of the **destination**
repository's graph. This caused 644 branches to show thousands of commits
ahead/behind main because they no longer shared a common ancestor with main.

Root causes:

1. The sync commit was created on the local `alpha` branch (which carried
   the source repository's full commit history) and then pushed to the
   destination's `main` — injecting foreign ancestry.
2. The operator attempted to repair the drift by force-pushing all 644
   branch refs to tree-matched equivalents on the new lineage. This changed
   every branch ref twice and inflated ahead/behind counts further because
   the two lineages had different commit granularity.

Lessons:

- **Always sync via a disposable clone of the destination repository** (step 4
  above). Never commit source content onto a local branch that carries source
  history.
- **Never batch-rewrite hundreds of branch refs** to fix a single bad push.
  Instead, revert the one bad push and replay the small set of new commits.
- **Back up branch tips before any force-push.** Without backups, the original
  state cannot be recovered.

## What Agents Must Not Do

- Do not assume "same files" implies "same branch history."
- Do not repair branch-history drift by merging the repositories together.
- Do not delete backup refs immediately after a rewrite.
- Do not leave PAT-backed temporary clones or remotes on disk after the operation completes.
- Do not batch-rewrite hundreds of old branch refs to fix a problem caused by one bad commit on main.
- Do not push any commit to the destination whose root commit differs from the destination's existing root.

## Minimum Verification Checklist

Before presenting the result as complete, verify all of the following:

- the target branch tip matches the intended repaired or synced commit,
- any required exclusions are still excluded,
- sample older branches now show sane ahead/behind counts against the repaired main line,
- backup refs exist during the validation window,
- temporary PAT-based clones/remotes have been removed,
- `python3 tools/lint_docs_structure.py` passes if documentation was changed.
