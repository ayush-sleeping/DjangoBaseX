# R&D: Session Auth vs JWT

**Resolves [`TECH_DEBT.md`](TECH_DEBT.md) DB-1 — the decision blocking every authenticated feature.**

**Status:** R&D, awaiting a decision. When decided, this becomes an ADR and this file points at it.

---

## Why this is urgent

`backend/config/settings.py` today sets:

```python
"DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.SessionAuthentication"],
"DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
```

…while [`ROADMAP.md`](ROADMAP.md) plans **SimpleJWT**. Those are different models with different
CSRF, CORS, storage and refresh semantics.

**Whichever the first authenticated endpoint uses settles it by accident**, and the loser gets
half-implemented — which is where the real bugs live. Decide first, then build.

This is a **core** decision. Every product copied from DjangoBaseX inherits it, so it is worth an
hour now.

---

## The two options

### A — Django sessions (what is configured today)

The browser holds Django's `sessionid` cookie; DRF reads it. `CORS_ALLOW_CREDENTIALS = True` and
`CSRF_TRUSTED_ORIGINS` are already set, so the cross-origin case is configured.

**For**
- **Already working.** Zero new dependencies, zero new code
- **`httpOnly` cookie — JavaScript cannot read it.** An XSS bug cannot exfiltrate the session, which
  is the single biggest practical advantage over token-in-storage
- Server-side revocation is real: delete the session row and the user is out **immediately**
- Django's battle-tested implementation — rotation on login, expiry, `SESSION_COOKIE_SECURE`

**Against**
- **CSRF token on every write.** The frontend must fetch and send `X-CSRFToken`. Forgettable, and the
  failure is a 403 that looks like a permissions bug
- Cross-origin cookies need `SameSite=None; Secure` in production, so **HTTPS is mandatory** — fine
  in production, friction with a plain-HTTP staging box
- Harder for non-browser clients — a mobile app or a server-to-server caller wants a token
- A stateful session store to scale

### B — SimpleJWT (access + refresh)

**For**
- Stateless; any number of API servers with no shared session store
- Natural for mobile apps and machine callers
- Short-lived access + long-lived refresh is a well-understood pattern
- What the roadmap already assumes

**Against**
- **Where does the token live?** `localStorage` is readable by any XSS. `httpOnly` cookie is safe but
  then you have cookies *and* CSRF again — and most of session auth's cost with none of its
  simplicity
- **Revocation is not free.** A signed token is valid until it expires. Real logout needs a blacklist
  — which is a database read per request, i.e. the statelessness you chose it for
- Refresh rotation with reuse detection is genuinely fiddly to get right, and getting it wrong is a
  silent security bug
- More moving parts in the frontend: refresh on 401, retry once, queue concurrent requests during
  refresh

---

## What comparable systems settle on

**The common answer for an API + separate SPA is JWT in `httpOnly` cookies** — an access/refresh
pair, refresh-token rotation **with reuse detection**, and a transparent single-retry refresh on the
client. The shape is what makes it work: it takes JWT's flexibility *and* the cookie's XSS
protection, and pays for both by implementing rotation and reuse detection properly rather than
skipping them.

It carries one consequence that must be written down on day one: **authenticated data is fetched
client-side, because an `httpOnly` cookie is not attached to a `fetch()` issued from a server
component** — a server component has to read the cookie and forward it explicitly. Public data is
fetched server-side. Getting the two backwards **fails silently**: the request succeeds,
unauthenticated, and renders the empty state. Any cookie-based choice inherits that trap, and it
belongs in `NEXTJS_STANDARDS.md` immediately.

**The other common arrangement is sessions for the first-party frontend plus tokens for API
consumers** — two mechanisms, deliberately, for two different audiences.

---

## Recommendation

**Option C — JWT in `httpOnly` cookies.**

- Keeps the XSS protection that makes sessions good
- Keeps the stateless-ish scaling and non-browser support that make JWT good
- Costs: you still need CSRF protection (cookies are sent automatically), and you must implement
  refresh rotation properly

If that cost is unattractive, **stay with sessions.** They are already configured, already secure,
and a product that needs machine callers can add token auth *for those callers only*. That is a
perfectly respectable end state.

**What would be wrong: JWT in `localStorage`.** It is the most commonly shown tutorial pattern and it
trades away the one protection that matters most, for convenience.

---

## Questions to answer before deciding

1. **Will a mobile app or a third-party integration ever call this API?** If yes, tokens must exist
   for *someone*, and the question becomes whether the browser also uses them
2. **Must logout be immediate?** If yes, you need a blacklist or sessions
3. **Multi-server from the start, or one box for a while?** Statelessness is worth less than it sounds
   at one server
4. **Who writes the frontend auth layer?** Refresh-with-retry-and-queue is the fiddliest part and it
   is frontend work

---

## Next step

Answer the four questions, pick A / B / C, write the ADR, then build. Do not start the auth
implementation before the ADR exists — that is precisely how this gets decided by accident.
