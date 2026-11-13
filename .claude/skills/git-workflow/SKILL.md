---
name: git-workflow
description: Use when the user wants to review Git changes, stage files, create commits, or push changes to a remote repository.
---

# git-workflow

Solo-developer flow: proceed without asking for routine safe steps. **Stop and explain** whenever a step could be destructive, or when the files or destination are ambiguous. Expected setup: one remote `origin` (GitHub), and work happens on `main` tracking `origin/main`; pushing to `main` is normal here.

## Never

- `push --force` / `--force-with-lease`, `reset --hard`, `checkout -- <file>`, `restore` (only `restore --staged`, which just unstages, is allowed), `clean`, `stash drop`, `rebase`, `commit --amend`, or anything else that rewrites history or discards work, unless the user explicitly asks for it.
- `git add .` / `git add -A` / `git commit -a`. Stage explicit paths only.
- Commit secrets, credentials, real `.env` files (`.env.example` templates are fine), or runtime media from `uploads/`/`downloads/`.
- Create an empty commit, or skip hooks (`--no-verify`).

## 1. Inspect state

```bash
git status --short --branch
git remote -v
git rev-parse --abbrev-ref --symbolic-full-name @{u}
git fetch origin && git status -sb    # ahead/behind after fetch
```

Stop and explain if:
- HEAD is detached, or a merge/rebase/cherry-pick is in progress.
- There are conflicts (`UU`, `AA`, … in status).
- The branch is **behind or has diverged** from its upstream. Don't pull or rebase on your own; ask how to integrate.
- There's no remote, or several remotes and it's unclear which one is meant.

If there are no changes (nothing staged, modified or untracked), report "nothing to commit", plus whether there are unpushed commits (offer to push them). Then stop.

## 2. Review changes

```bash
git diff --stat; git diff
git diff --cached --stat; git diff --cached
git status --short --untracked-files=all
```

Read the actual diff, not just the file list. Keep in mind:
- Anything **already staged** may have been staged by the user deliberately. Include it, but review it with the same checks.
- Large or binary files: check the size (`du -k`). The Vosk `model/` files are intentionally tracked; new large binaries are not expected.
- `requirements.txt` is UTF-16, so git shows it as binary. Inspect it with `iconv -f UTF-16 -t UTF-8 requirements.txt` or `git diff --text`.

## 3. Exclude what shouldn't be committed

Leave a file unstaged, and say why, if it is:
- **A secret or env file**: `.env`, `.env.*` (not `*.example`), keys or certificates, or `.claude/settings.local.json`. The content scan runs in step 4.
- **A generated artifact**: `__pycache__`, `*.pyc`, `node_modules/`, `dist/`, logs, temp files, smoke-test leftovers in `backend/uploads|downloads`. The `.gitignore` covers these; if one shows up anyway, report it.
- **An unrelated change**: work that doesn't belong to the current task or theme.

When the changes cover more than one clear topic, make **separate commits**, one per topic, and say so. When it's unclear whether a file belongs (for example an unexpected edit you didn't make this session), **ask** instead of including it or leaving it out silently.

## 4. Stage, verify, commit

```bash
git add -- <explicit paths>
git diff --cached --stat          # confirm exactly what's going in
git diff --cached -U0 | grep -niE "(eyJ[A-Za-z0-9_-]{10,}\.|sk_(live|test)_|AKIA[0-9A-Z]{16}|BEGIN [A-Z ]*PRIVATE KEY|(api[_-]?key|secret|token|password)['\"]?\s*[:=]\s*['\"][^'\"]{12,})"
```

Look at every scan match, but never print the value; show it redacted:
- **Known non-secrets: continue, and mention them in the report.** These are code expressions and obvious placeholders, e.g. the `PLACEHOLDER_SUPABASE` dummy JWT in `scripts/smoke_test.py` and `"gladia_api_key"` used as a dict key in `App.jsx`.
- **Anything that could be a real credential: stop.** Unstage that file with `git restore --staged <file>`, which only unstages and keeps the changes in the working tree, then explain. Don't commit it.

Write a Conventional Commits message from the staged diff:
- Format: `type(scope): summary`. Imperative mood, at most about 72 characters, no trailing period.
- Types: `feat`, `fix`, `docs`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`, `style`. Use `!` for a breaking change (e.g. a job-result shape or endpoint contract change).
- Scopes that fit this repo: `backend`, `frontend`, `download`, `transcription`, `export`, `auth`, `docker`, `deps`, `docs`, `scripts`, `skills`. Omit the scope if nothing fits.
- Add a short body (wrapped bullets) only if the summary can't carry the why or the notable details.
- Follow the session's commit-attribution instructions (e.g. a `Co-Authored-By` trailer) if any are given.

Commit with a heredoc so formatting survives:

```bash
git commit -F - <<'EOF'
type(scope): summary

- optional detail
EOF
```

If a pre-commit hook fails, fix the reported issue (or report it) and make a **new** commit attempt. Don't amend or bypass the hook.

## 5. Push and verify

```bash
git push                          # upstream already set
git push -u origin <branch>       # only if the branch has no upstream and origin is the only remote
git status -sb                    # must show no "ahead"
git log -1 --format='%H %s'
```

If the push is rejected (non-fast-forward, auth, protected branch), **stop**. Report the error and don't force-push or auto-rebase.

## 6. Report

- Commit hash(es) and message(s).
- Files committed, and files deliberately left out with the reason for each.
- Push result (`<branch> -> origin/<branch>`).
- Final `git status -sb`.
