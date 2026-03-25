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
5. If the sync must exclude specific files, preserve those exclusions explicitly in the temporary destination clone before committing.

## Safe Sync Procedure

1. Fetch the latest source and destination refs.
2. Inspect ancestry before changing anything:
   - `git merge-base <destination-branch> <source-ref>`
   - `git rev-list --max-parents=0 <destination-branch>`
   - `git rev-list --max-parents=0 <source-ref>`
3. Create a disposable clone or temporary worktree from the **destination** repository and check out the destination branch there.
4. Replace the destination tree contents from the source tree in that disposable clone.
   - Use tree-copy approaches such as `git checkout <source-ref> -- .`, `git archive`, or equivalent file-level sync in the temporary destination clone.
   - Do **not** merge the source branch history into the destination branch.
5. Restore explicitly excluded paths to their destination-repository state, or remove them if they must stay absent.
6. Review the staged diff to confirm it is a content diff, not a history rewrite.
7. Commit in the destination repository.
8. Push the destination commit normally.

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

## What Agents Must Not Do

- Do not assume "same files" implies "same branch history."
- Do not repair branch-history drift by merging the repositories together.
- Do not delete backup refs immediately after a rewrite.
- Do not leave PAT-backed temporary clones or remotes on disk after the operation completes.

## Minimum Verification Checklist

Before presenting the result as complete, verify all of the following:

- the target branch tip matches the intended repaired or synced commit,
- any required exclusions are still excluded,
- sample older branches now show sane ahead/behind counts against the repaired main line,
- backup refs exist during the validation window,
- temporary PAT-based clones/remotes have been removed,
- `python3 tools/lint_docs_structure.py` passes if documentation was changed.
