# DjangoBaseX — agent entry point

@AGENTS.md

<!--
  Everything above the fold is that one import. Claude Code reads CLAUDE.md, not AGENTS.md, so the
  import is what makes the root AGENTS.md load at all — and it is the ONLY thing that loads
  automatically. Keep the operating contract in AGENTS.md; do not copy rules here, or the two will
  drift and nobody will know which one is current.

  ── What this repository is ────────────────────────────────────────────────────────────────────

  A BOILERPLATE — the Django/Next.js sibling of PriorCoreA. Products get copied from it. Do not give
  it a product identity, a client name, or domain models that belong to one product. If you are
  reading this inside a copy that HAS become a real product, the rename should already be reflected
  in AGENTS.md § 0 — if it is not, that is worth fixing before anything else, because every session
  reads that banner.

  ── One contract ───────────────────────────────────────────────────────────────────────────────

  There is exactly ONE agent contract: the root AGENTS.md. Do not add a second one under
  documentation/ or in an app directory. Two copies drift, and the failure mode is not "slightly out
  of date" — it is two files giving opposite instructions with no way to tell which is current.

  frontend/AGENTS.md is the exception, and it is not ours: `next dev` generates and re-adds it. Never
  hand-edit it; frontend rules go in the root AGENTS.md or in
  documentation/system-design/NEXTJS_STANDARDS.md.

  Deliberately NOT imported: documentation/INDEX.md. Imports load eagerly into every session, and the
  doc map matters a few times per task rather than every turn. AGENTS.md § 6 points at it.

  Imports are recursive to 4 hops, and a relative path resolves against the file containing the
  import — not the project root.
-->
