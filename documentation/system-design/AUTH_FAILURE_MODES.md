# Auth & RBAC — Failure Modes and Design Checklist

**The reasoning behind [`AUTH_BLUEPRINT.md`](AUTH_BLUEPRINT.md).** That document says *what to
build*; this one says *what goes wrong in authentication and authorization systems*, and which of
those failures each decision is buying protection from.

**Read this when a decision in the blueprint looks arbitrary or expensive.** Most of them are
paying for a failure listed here, and the failures are the kind that do not show up in a demo, a
code review, or a green test suite.

---

## 1. The asymmetry that makes authorization bugs durable

Authorization has two failure directions, and they are **not** equally visible:

| Failure | Who notices | How fast | Typical outcome |
|---|---|---|---|
| A gate **wrongly denies** | The blocked user | Days to weeks | A support ticket. Annoying, self-reporting |
| A gate is **missing entirely** | Nobody | Never, until exploited | Silent, indefinite exposure |

Every mechanism in Chapter 9 of the blueprint exists because of this asymmetry. **A test suite
measures the code you wrote; it cannot measure the gate you forgot to write.** Coverage does not
help — the handler is covered, it works, and it serves the data it was asked for.

### The compounding factor: a broad superuser bypass

The people most likely to exercise a new feature before release are usually senior, and usually
hold the bypass. So:

1. A route is misconfigured and denies every ordinary role
2. It is checked by someone holding the bypass, who sails through
3. It ships "working"
4. It surfaces weeks later, reported by someone junior enough to hit the real path

**A bypass held by the people most likely to test hides breakage from the people most able to fix
it.** The defence is not to abolish the bypass — a system with no emergency access is a system
nobody can repair — but to make every use of it leave a trail (blueprint § 9.5).

---

## 2. The failure catalogue

Each entry: what it is, how it presents, and what defends against it.

### F1 — The forgotten gate

**What:** an endpoint ships with no permission attached.
**Presents as:** nothing. It works. Anyone authenticated can call it.
**Why it recurs:** when the gate is a *call inside the handler* (`require(request, …)` as the first
line), omitting the call is indistinguishable from a public endpoint, and the code reads correctly.
**Defence:** make omission *deny* rather than serve — a default-deny base class where a missing
declaration produces 403 (blueprint § 9.1), plus a boot check and a route-enforcement test.

> **This is the single most important failure in this document.** Everything else on this list is
> recoverable; this one is indefinite and invisible.

### F2 — The permission that does not exist

**What:** a route requires a permission code that was never created — a typo, a rename, or a seed
that never ran.
**Presents as:** **everyone is denied, permanently, while the grant looks correct on the roles
screen.** A checkbox is ticked; access is refused. The time is lost hunting a permissions bug that
is really a spelling bug.
**Cost:** high and concentrated. This is the failure most likely to produce *"it must be a caching
problem"* and days of misdirected debugging.
**Defence:** a boot check comparing every referenced code against the code-declared catalog
(`dbx.E002`). A typo becomes a failed `manage.py check`, not a production denial.

### F3 — Layer 1 without Layer 2

**What:** the endpoint checks *may this user use this feature*, then looks the row up by id from the
URL.
**Presents as:** any user holding `x.update` can update **any** row, including rows belonging to
other teams, customers or tenants.
**Why it recurs:** Layer 1 is what a permission system obviously provides; Layer 2 has to be
remembered per query. A scaffolded object-permission layer that nobody ever fills in is **worse than
none**, because it reads as though the check exists.
**Defence:** `visible_to(user)` as a contract that raises when unimplemented, every list going
through it, and every detail route resolving through the scoped queryset (blueprint § 7.6).

### F4 — Implicit route→permission resolution

**What:** which permission a route needs is *reconstructed* at request time — from the route name,
the controller class name, a prefix map, a verb map, or a table of exceptions.
**Presents as:** works fine at ten controllers. At a few hundred routes the resolver needs mapping
tables, pluralisation rules and irregular-case lists, and grows larger than the feature it guards.
Routes start resolving to permissions that do not exist (→ F2), and **you cannot assert correctness**
because "every route resolves to a real permission" is not true and cannot be made true.
**Defence:** the link is **declared**, not derived. One explicit attribute on the view.

> **Scale is the trap.** This pattern is genuinely fine in a small application, which is exactly why
> it gets copied into a core — and a core is copied into products that reach the size where it
> breaks.

### F5 — Authorization keyed on a UI concept

**What:** the grouping that exists to lay out checkboxes on the roles screen becomes load-bearing
for the access decision (e.g. matching a group's "controller" name against the route's controller).
**Presents as:** renaming a class, moving a file, or restructuring a screen silently changes who can
do what.
**Defence:** display metadata is display-only. Nothing in the code may branch on a permission group.

### F6 — Status as free text

**What:** account state stored as a string and compared `!= "ACTIVE"`.
**Presents as:** any writer that sets `"active"`, `"Active"` or `"ACTIVE "` silently grants or
revokes access, and the bug is invisible in review.
**Defence:** booleans. Two states, no spelling.

### F7 — Revocation that is not revocation

**What:** deactivating an account, or "signing out everywhere", does not end sessions already
issued.
**Presents as:** a dismissed employee keeps working access until their token expires — hours or
weeks. **Stateless tokens cannot be withdrawn**; that is their defining property, not a bug.
**Defence:** a session row per issued refresh token, checked on each request (blueprint § 3.2, § 6.4).
Accept and document the latency introduced by any cache in front of that check.

### F8 — The password change that ends nothing

**What:** a password is changed in response to a suspected compromise; existing sessions survive.
**Presents as:** the attacker keeps their session. The user believes they have fixed it.
**Defence:** a password change revokes **every** session, including the current one, and stamps
`password_changed_at` so older tokens fail (blueprint § 6.7).

### F9 — The login endpoint as a user oracle

**What:** wrong password, unknown address and inactive account produce distinguishable responses —
different status, different wording, or measurably different timing.
**Presents as:** an attacker enumerates valid accounts without ever logging in. The usual leak is
**not** the status code; it is one branch with a more helpful message.
**Defence:** one identical response for all three; the real reason recorded server-side only; the
password hasher run even when the account does not exist.

### F10 — The unthrottled front door

**What:** no rate limit or lockout on login, reset or MFA verification.
**Presents as:** credential stuffing at whatever rate the network allows.
**Defence:** throttles keyed on **identifier and IP together** — identifier alone lets one attacker
spread across accounts, IP alone punishes everyone behind a NAT.

### F11 — Total takeover from one session

**What:** every action, including the most destructive, is available to any live session.
**Presents as:** one stolen laptop, one XSS or one unlocked screen equals full compromise of
everything that account can reach.
**Defence:** re-authentication on named dangerous actions, **off by default** so installing it
breaks nothing, with a distinct status (`423`) so clients can prompt rather than log out.

### F12 — The audit trail with holes

**What:** logins are logged; password resets, MFA changes and permission grants are not.
**Presents as:** after an incident, the most important questions are unanswerable — *who widened
this role, and when? who turned MFA off?* Disabling MFA in particular is what an attacker does
**after** taking an account over, and it is frequently the one event nobody records.
**Defence:** an append-only log covering authentication, authorization *changes*, and bypass use.
And every write wrapped so that **logging never breaks the action it observes**.

### F13 — Cached permissions with no invalidation path

**What:** the permission set is cached for performance, and a grant change does not clear it.
**Presents as:** revoking access appears to do nothing; the fix is "wait" or "restart", and someone
eventually removes the cache instead of fixing invalidation.
**Defence:** a version counter bumped on any grant, role or assignment change — invalidating
everyone at once, which is correct, since a role edit changes many users' effective permissions.

### F14 — Privilege escalation through role assignment

**What:** whoever can assign roles can assign themselves the administrator role.
**Presents as:** ordinary-looking use. Not an exploit — a missing rule.
**Defence:** roles flagged elevated, assignable only by a superuser, enforced **in the service**
rather than the view so commands and the admin cannot bypass it.

### F15 — Locking everyone out

**What:** the last superuser is demoted or deactivated.
**Presents as:** a system nobody can grant anyone the right to repair.
**Defence:** an explicit last-superuser guard on both demotion and deactivation.

### F16 — UI affordances gated on the wrong right

**What:** row actions all hang off one blunt "can manage" flag.
**Presents as:** an add-only user is shown Edit and Delete buttons that can only 403; an
update-only user is refused an edit they are entitled to make. It reads as a permissions bug and is
really a UI bug.
**Defence:** each affordance gated on **exactly the permission its own endpoint enforces**, with a
test asserting the pairing.

### F17 — Seeding that deletes

**What:** the permission seeder removes catalog entries that are no longer declared in code.
**Presents as:** a refactor drops a permission; the delete cascades away every grant that referenced
it; restoring the code does not restore access.
**Defence:** seeding **never deletes**. A code that leaves the catalog is marked deprecated, and the
doctor reports deprecated codes that still hold grants.

---

## 3. The design checklist

**Use this to evaluate any auth system, including ours.** Blank answers are the finding.

**Identity**
- [ ] Custom user model, in place before the first migration
- [ ] One login identifier, unique and normalised
- [ ] Account state as booleans, not free text (F6)
- [ ] New accounts inactive until explicitly activated
- [ ] Internal ids never exposed in URLs

**Authentication**
- [ ] One credential mechanism, chosen deliberately — not two installed side by side
- [ ] Revocation effective without waiting for expiry (F7)
- [ ] "Sign out everywhere" possible at all
- [ ] Password change revokes every session (F8)
- [ ] Reset tokens hashed at rest, single-use, short-lived
- [ ] Identical response for wrong password / unknown address / inactive (F9)
- [ ] Throttling on login, reset and MFA, keyed on identifier **and** IP (F10)
- [ ] Second factor available, and enforceable by policy rather than only opt-in
- [ ] Re-authentication on dangerous actions, off by default (F11)

**Authorization**
- [ ] Permission catalog declared in code, reviewable in a diff (F4)
- [ ] Codes namespaced per module, so modules cannot collide
- [ ] Modules contribute permissions by existing, not by being listed centrally
- [ ] Grant-only: no per-user grants, no explicit denies
- [ ] **The gate is declared on the view, not called inside it** (F1)
- [ ] **Omitting the gate denies rather than serves** (F1)
- [ ] Every referenced code verified against the catalog at boot (F2)
- [ ] Row-level scoping is a contract every listable model implements (F3)
- [ ] Unscoped queryset → nothing, never everything
- [ ] Elevated roles assignable only by a superuser (F14)
- [ ] Last superuser cannot be removed (F15)
- [ ] Permission cache has an invalidation path (F13)
- [ ] Seeding never deletes (F17)

**Proof**
- [ ] A test walks **every** route unauthenticated and fails on anything that is not 401/403
- [ ] A user with a role holding zero permissions is refused by **every** gated endpoint
- [ ] An invisible row returns 404, not 403
- [ ] UI affordances are tested against the rights their endpoints enforce (F16)
- [ ] Bypass use is audited (§ 1)
- [ ] Auth *and* authorization-change events are logged, including MFA disable (F12)

---

## 4. Rules for the tooling itself

A checker that is wrong, noisy or over-trusted is worse than no checker. Four rules:

1. **Delegate to the real enforcement code; never model it twice.** A checker that reimplements
   resolution will eventually disagree with the code that actually decides — and then it reports
   "healthy" over broken routes, which is worse than silence.
2. **Separate hard failures from advisory findings.** Failing a build over untidy-but-harmless
   configuration is how a check gets switched off, and a switched-off check protects nothing.
3. **Never report health over a known backlog.** If a ledger of known-broken entries is introduced,
   report the remaining count instead of "healthy" — **and the list may only shrink.** Adding to it
   means shipping something broken.
4. **Detect the ledger's own rot.** Report entries that are fixed or gone, or the list quietly
   becomes decoration and its count stops meaning anything.

**And: error messages name the fix, not just the fault.** *"X requires permission Y, which is not in
the catalog — add it to the module's declaration, or correct the code on the viewset."*

---

## 5. What "stronger" means here

Not a longer feature list. A system can ship MFA, OAuth, impersonation, re-auth and a full audit
trail and still be weaker than one without them, because **the way authorization actually fails is
F1 — somebody adds an endpoint and forgets the gate.** No feature prevents that.

Three properties do:

1. **Omitting the gate denies.** The failure mode is inverted, so forgetting is safe.
2. **A wrong or missing permission code cannot boot.** It fails `manage.py check`, which already
   runs in the verification gate — before any test, on every machine, every time.
3. **Row scoping is a contract, not a convention.** A model that has not answered "who may see
   these rows" cannot be listed at all.

Each of these turns a *discipline* — remember to do the thing — into a *mechanism*. Discipline does
not survive scale, staff turnover, or a deadline. Mechanisms do.
