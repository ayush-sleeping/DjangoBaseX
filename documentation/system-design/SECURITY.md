# Security

**What the core guarantees, what it does not, and the rules that keep it true.**

Written down because a boilerplate's security posture is inherited silently. A weakness here ships to
every product copied from it, into repositories with their own access lists, long after anyone
remembers where it came from.

---

## Threat model — who we are defending against

| Actor | Can | The core must |
|-------|-----|---------------|
| **Anonymous internet** | Hit any exposed endpoint | Refuse everything not explicitly public |
| **A signed-in user** | Call any endpoint their session reaches | Enforce RBAC per request, not per screen |
| **A curious employee** | Change ids in URLs | Scope every query; a guessed id must 404 |
| **A compromised browser (XSS)** | Run JS as the user | Keep the session token unreadable by JS |
| **A plugin author** | Run code in the same process | Be contained by convention + tests, **not** a sandbox |
| **A leaked backup** | Read the database | Hash passwords and tokens at rest |

> **Stated plainly: plugins are not sandboxed.** A plugin runs in the same Python process with the
> same database access. The boundaries are conventions enforced by tests — they prevent *accidents*,
> not malice. **Only install plugins you trust as much as the core.**

---

## What the core guarantees (once Phase 1 is built)

1. **Fail closed.** An endpoint without an explicit permission is denied
2. **Passwords hashed** with Django's PBKDF2/Argon2 — never stored, logged, or comparable outside
   `check_password`
3. **Tokens hashed at rest** — invitations, API credentials, reset tokens. A leaked table yields no
   usable credential
4. **No user enumeration** — wrong password and unknown email answer identically
5. **Object-level scoping** — a guessed id returns 404, not 403, so ids are not an oracle
6. **Audit trail** — who did what, when, from where, superusers included
7. **Rate limiting** — on by default, harder on auth endpoints

## What it does **not** guarantee

- **Not deployment security.** TLS, WAF, network policy and secret storage are the deployer's
  ([`DEPLOYMENT.md`](DEPLOYMENT.md) § 0)
- **Not plugin isolation.** See above
- **Not compliance.** No GDPR/SOC2 posture is claimed; retention and export are per product
- **Not DoS resistance** beyond basic throttling

---

## Rules, by area

### Secrets

- Everything environment-dependent comes from `.env` via `django-environ`. **Nothing hard-coded**
- **Never echo a `.env` value** into output, logs, docs or a commit — key names only
- Add every new key to `.env.example` **with a placeholder**, same change
- **A fresh `SECRET_KEY` per environment and per product.** Two products sharing one means a session
  cookie minted by either is accepted by both — a cross-product authentication bypass
- `NEXT_PUBLIC_*` is **inlined into the client bundle**. A secret must never carry that prefix

### Authentication

- Pending [`../planning/AUTH_RND.md`](../planning/AUTH_RND.md). Whatever wins:
  - The browser's credential must be **unreadable by JavaScript** (`httpOnly`), so an XSS bug cannot
    exfiltrate a session
  - **Revocation must be real** — a `Session` row, or a token blacklist. "Valid until it expires" is
    not logout
  - Rotate the session identifier on login to prevent fixation
  - Throttle auth endpoints harder than the rest

### Authorization

Both layers, every time — entity **and** object ([`RBAC_DESIGN.md`](RBAC_DESIGN.md)).

> The defining bug: `users.users.update` means *may edit users*, not *may edit **this** user*. A view
> that checks only the entity layer and then looks up by URL id lets any permitted user edit any row.

**Ownership never comes from the payload.** `user`, `owner`, `organisation` come from `request.user`.

### Input and output

- Validate in serializers; the ORM parameterises queries — **never** `.raw()` or `.extra()` with an
  f-string
- **Allow-list filter and ordering fields.** `.filter(**request.query_params)` lets a caller filter on
  anything, including traversing a relation into another user's rows
- **Cap `page_size`** — uncapped it is a DoS parameter
- Validate uploads by **content**, not extension; store outside the web root; never serve from a
  user-controlled path
- React escapes by default — **`dangerouslySetInnerHTML` needs a sanitiser and a comment**

### Errors and logging

- **Never leak internals** — no stack traces, SQL or paths in a response. `DEBUG=False` covers the
  unhandled case; your own messages are yours
- **Never log a credential, token, session id or password** — not even at DEBUG. Redact at the
  formatter so it cannot be reintroduced by a careless log line

### Dependencies

- Lockfiles committed (`uv.lock`, `package-lock.json`); `uv sync --frozen` and `npm ci` in CI and deploy
- 🔜 Enable Dependabot and `pip-audit` / `npm audit` in CI

---

## Production checklist

Nothing below is optional, and none of it is configured yet (`TECH_DEBT` **DB-7**, **DB-8**).

```python
DEBUG = False
ALLOWED_HOSTS = ["your.host"]          # never ["*"]
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")   # only behind a trusted proxy
CORS_ALLOWED_ORIGINS = ["https://your.frontend"]                 # never "*" with credentials
```

```sh
uv run python manage.py check --deploy    # run it — it names what is missing
```

🔜 **DB-7 — a startup guard that refuses to boot** with `DEBUG=True` or a placeholder `SECRET_KEY`
outside development. A default that is safe locally and unsafe in production is invisible until
something asserts it.

---

## Reporting and response

This is a public repository. Report a vulnerability **privately** to the maintainer — never in a
public issue.

If a secret is committed: **rotate it first**, then remove it. Deleting the line does not remove it
from history, and in a boilerplate that history is inherited by every copy. Treat any committed
secret as permanently public.
