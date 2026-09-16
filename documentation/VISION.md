# Vision

**What DjangoBaseX is for, who it serves, and how we will know it worked.**

Every other document answers *how*. This one answers *why*, and it is the tie-breaker when two
designs are both defensible. Read it before proposing anything structural.

---

## The one-sentence version

> **A Django + Next.js core you copy into a new project and start building on the same day — where
> the platform work is already done, several teams can build on it at once without colliding, and a
> fix made here reaches every product already built on it.**

---

## The three properties, in priority order

When two designs conflict, the higher property wins. This ordering is the whole point of the page.

### 1. Reusable — copy it and start building today

A new project starts from DjangoBaseX in minutes, not days. Auth, RBAC, users, settings and the
dashboard shell already exist and are already tested. You add a product; you do not rebuild any of
that.

**Test of this property:** someone clones it, runs one script, signs in, and sees a working
application before they have written a line of their own code.

### 2. Parallel — several teams, several repos, no collisions

A self-contained feature lives in **its own GitHub repo**, owned by one team, mounted as a plugin.
That team ships without opening a PR against the core, and without being able to break another
team's feature.

**Test of this property:** two teams ship features the same week, neither reviews the other's code,
and neither can break the other.

### 3. Maintained — a fix here reaches products already shipped

Products are created by clone-and-re-origin, so `git fetch core && git merge core/main` works. The
core is not a snapshot someone copied in 2026; it is upstream.

**Test of this property:** a security fix committed here lands in a product built six months ago in
under an hour, without a rewrite.

---

## Who this is for

| Audience | What they need from it |
|----------|------------------------|
| **You, starting a new project** | Skip the platform. Have auth and RBAC on day one |
| **A team owning one feature** | Their own repo, their own release pace, a stable seam |
| **An outside contributor** | A sandbox branch they can push to and cannot break production with |
| **An AI agent handed the repo** | A contract, a backlog, acceptance criteria — enough to work unsupervised |

That last row is deliberate. The docs are written so an agent arriving cold can be productive without
a conversation, because that is increasingly how work gets done here.

---

## What DjangoBaseX is **not**

Saying no is what keeps a core small enough to stay reusable.

- **Not a product.** It has no clients, no domain models, no business rules. A copy of it becomes a
  product; this one never does
- **Not a CMS or a site builder.** It is an API plus an authenticated back office
- **Not a framework.** It is a starting point you own and edit, not a dependency you install
- **Not a monolith of everything.** If a capability only some products want, it is a plugin. The core
  is the part **every** product needs
- **Not a place for clever abstraction.** Two products' worth of evidence before a seam exists. An
  abstraction built for one product is a guess

---

## Design principles

Ordered, and each earns its place by being violated often.

### 1. Dependencies point inward, registration points outward
`core` never imports `project` or a plugin. It exposes registries; others register into them at
boot. **Deleting `project/` must leave a working platform**, and a test asserts it.

### 2. Enforce with a test, not a convention
A rule that is only written down is already half-broken. Every boundary in the architecture has
something that goes red when it is crossed. This is the single biggest lesson from both reference
projects.

### 3. Fail closed
A new endpoint is private until it opts out. An unrecognised permission is denied. A scoping
question with no answer returns nothing. The default answer to "is this allowed?" is no.

### 4. Two products' evidence before a seam
A core change needs a reason that applies to more than one product. If it only serves yours, it
belongs in your copy. **Adding a seam beats adding a special case** — but adding neither beats
guessing.

### 5. Honest documentation
Docs say what is true today and mark what is planned. A doc that overstates the system is worse than
no doc, because people build on it. `TECH_DEBT.md` lists defects we are not fixing yet **by name**.

### 6. Decide deliberately, record it
The expensive decisions — the auth model, the primary key type, whether tenancy exists — get settled
by accident if nobody settles them on purpose. Write the ADR before the code.

---

## Success criteria

Concrete enough to be wrong about.

| # | Criterion | How we know |
|---|-----------|-------------|
| 1 | A new project is running on it **in under 30 minutes** | Time it, from `git clone` to signed in |
| 2 | **A second product exists** and needed no core edits | `core_doctor.py` reports zero drift |
| 3 | A plugin is built by someone who **never opened the core** | Ask them |
| 4 | A core update merges into a product **with no conflicts in `core/`** | The merge |
| 5 | An agent completes a `BUILD_ORDER.md` task **unsupervised** and passes the gate | The PR |
| 6 | The gate catches a real mistake **before review** | It happens once and we notice |

**Criterion 2 is the real one.** Nothing proves a core is reusable until something else is built on
it. Whatever hurts the second time is the design flaw, and it is far cheaper to find at product two
than at product five.

---

## Non-goals, stated so they do not creep in

- **Not maximal configurability.** Every setting is a branch someone must maintain. Opinionated
  defaults, few knobs
- **Not framework-agnostic.** It is Django and Next.js. An abstraction layer over either would cost
  more than it returns
- **Not multi-language or multi-region on day one.** Add when a product needs it
- **Not a performance project.** Correct, secure and clear first. Fast when something is measured slow

---

## How this document gets used

When a proposal arrives, ask in order:

1. Does it serve **reusability, parallelism or maintainability**? If none, it probably belongs in a
   product, not here
2. Would **the next product** want it? If not, it is a plugin or it is `project/` code
3. Does it make copying the core **harder**? That cost is paid by every future product
4. Is it **enforced**, or only written down?

If this document and a proposal genuinely conflict, that is worth an ADR — vision can change, but it
should change on purpose and in writing, not by drift.
