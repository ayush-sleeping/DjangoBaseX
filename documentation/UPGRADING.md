# Taking a Core Update Into a Product

**A boilerplate that cannot deliver a fix to the products already built on it is a snapshot, not a
core.** This is the mechanism that makes DjangoBaseX the second thing.

> **Status:** built. The git mechanism, the drift doctor (`scripts/core_doctor.py` against
> `core.manifest.json`, BUILD_ORDER 4.2) and the PR guard (`.github/workflows/core-guard.yml`, 4.3)
> all exist. The rules they implement are
> [`system-design/ENGINEERING_PRACTICES.md`](system-design/ENGINEERING_PRACTICES.md) § 52.

---

## The premise

Your product was created by **clone and re-origin** ([`NEW_PROJECT.md`](NEW_PROJECT.md)), so it
shares history with DjangoBaseX and has two remotes:

```bash
git remote -v
# core    https://github.com/ayush-sleeping/DjangoBaseX.git
# origin  git@github.com:<owner>/my-product.git
```

If `git remote` shows no `core`, the product was made with "Use this template" and **cannot take
updates** — there is no common ancestor to merge from. Recovering means grafting history by hand;
avoid it by never using the template button.

---

## Taking an update

```bash
git checkout -b chore/core-update
git fetch core
git log --oneline HEAD..core/main          # read what you are about to take
git merge core/main
```

Then, in order:

```bash
cd backend
uv sync                                    # core may have changed dependencies
uv run python manage.py makemigrations --check --dry-run   # core may have shipped models
uv run python manage.py migrate
uv run ruff check . && uv run python manage.py check

cd ../frontend
npm ci                                     # ci, not install — respect the lockfile
npm run lint && npx tsc --noEmit

cd ..
python3 scripts/core_doctor.py             # clean = you took the core exactly as shipped
```

Open a PR against your own `main`. **Read the diff** — a core update is the one merge where "it
compiled" is not enough, because it can change behaviour your product depends on without changing
any file your product owns.

---

## Why conflicts are rare, and what it means when they are not

The three-layer split exists for exactly this moment. Core updates touch `core/`; your product lives
in `project/` and its plugins. Different files, no conflict.

**So a conflict is information.** It almost always means one of:

| Conflict in | What it tells you |
|-------------|-------------------|
| `core/` | **Your product edited the core.** This is the expensive case — see below |
| `config/settings.py`, `config/urls.py` | Normal. These are composition roots; both sides legitimately add to them. Merge both |
| lockfiles | Normal. Take the core's dependency change, re-run `uv sync` / `npm ci` |
| `documentation/` | Normal if you kept the core's docs. Take theirs for `core/` and `system-design/`; keep yours for `planning/` |

### If you edited core

A forked core stops receiving fixes — **silently, forever**. Nothing errors; updates simply stop
applying cleanly and eventually someone gives up merging.

`python3 scripts/core_doctor.py` names every core file your checkout has changed, by comparing
SHA-256s against `core.manifest.json`:

```text
$ python3 scripts/core_doctor.py
core 0.1.0
MODIFIED  backend/core/env.py
ADDED     backend/core/billing_hack.py

2 core file(s) drifted from core.manifest.json.
Ways forward, for each file above: …
```

- **modified:** the fork is diverging. **missing:** a core file was deleted. **added:** a private
  module inside a core tree, which is how a fork usually starts. An untracked file counts too.
- Exit codes: `0` clean, `1` drift, `2` a setup error (no manifest, not a git checkout).
  `--json` gives the same report for scripts.
- "Core" is a list, not a directory: the trees and files in the manifest's header. The places
  products are meant to edit (`config/settings.py`, `config/urls.py`, `project/`, `plugins/`,
  `documentation/`, `.github/`) are deliberately not in it.

On every pull request, `core-guard.yml` fails a PR that changes a core file unless the PR carries the
**`core-change`** label. It also runs the doctor over the whole tree, so drift that arrived by a direct
push or a merge fails too. Adding or removing the label re-runs the check.

For each file it names, ask: **why did this need editing?** The answer is nearly always "the core
had no seam for what I needed". That is a request to the core maintainer, not a local patch — a seam
added upstream serves every product and keeps yours mergeable. Move the change into `project/` or a
plugin, and open the upstream PR the same week.

> **Never regenerate `core.manifest.json` in a product repo.** It records your drift as correct,
> which is worse than having no manifest at all — it makes the doctor report clean while the fork is
> still there.

---

## For the core maintainer: shipping an update

A change to `core/` reaches **every product built on it, including ones already in production.**
That is why the rules are stricter than a product repo's.

- **A core change needs a reason that applies to more than one product.** If it only serves one, it
  belongs in that product's `project/`
- **Adding a seam beats adding a special case.** If core has to know something specific about one
  product to work, the design is wrong
- **Breaking changes go in `VERSION_SUMMARY.md` under `Breaking`**, stating what a product must
  change. That section is the one people actually read
- **Regenerate `core.manifest.json` in the same PR** (`python3 scripts/core_doctor.py --write`). A
  core change that forgets it makes every product report as drifted. In this repository, core-guard
  fails a PR that touches core without the manifest, and runs `--verify` on every PR and every push
  to `main`. `--write` refuses to run anywhere whose `origin` is not the core repository
- **Regenerate from a clean tree.** `--write` hashes the working tree. Run it with nothing
  uncommitted under a core tree, or from a detached worktree of the commit you are publishing
- **A version bump is a core change too.** `VERSION` is in the manifest's header, so bump it, then
  regenerate
- **Never rewrite published history.** A force-push to `core/main` breaks the merge base for every
  product at once, and there is no clean recovery

---

## If an update is genuinely unwanted

Skipping one update means the next is bigger, and the gap compounds until merging becomes a rewrite.
Prefer taking it and reverting the one commit you dislike:

```bash
git merge core/main
git revert <the-commit-you-do-not-want>
```

You stay on the shared history, and the next update still merges.
