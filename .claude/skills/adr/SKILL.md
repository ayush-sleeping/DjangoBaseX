---
name: adr
description: Record a settled architectural decision as a numbered ADR and register it in documentation/ADR.md, or supersede an Accepted one. Use when the repository owner settles a 🚧 DECISION or any choice that constrains future work.
argument-hint: "<short decision title>"
allowed-tools: Bash(ls documentation/adr*)
---

# Architecture Decision Record

The rules on when to write one and what immutability means are in `documentation/ADR.md`. This is the
procedure.

## Existing records

!`ls documentation/adr`

## Procedure

1. **Only record what the owner decided.** An agent's recommendation is not a decision. If the owner has not
   said yes in this conversation, write the ADR as **Proposed**, or ask first.
2. **Number it**: one higher than the highest above, zero-padded to four digits. Name the file
   `documentation/adr/NNNN-<kebab-title>.md`.
3. **Copy `documentation/adr/0000-template.md`** and fill in every section:
   - **Context**: the pressure that forced the choice, written for someone who wasn't there.
   - **Decision**: present tense, one paragraph if possible.
   - **Consequences**: include the costs. An ADR that lists only benefits is marketing.
   - **Alternatives considered**: each option, with why not.
4. **Register it**: add a row to the table in `documentation/ADR.md` with the number, the title, the status
   and today's date.
5. **To supersede an Accepted ADR**: never edit the old file's decision text. Write the new ADR, set the old
   one's status line to `Superseded by [ADR-NNNN](NNNN-….md)`, and update both rows in `documentation/ADR.md`.
6. **Follow through.** Update the docs that described the open question: the `BUILD_ORDER.md` task, the
   "Pending decisions" list in the owning spec, and any `TECH_DEBT.md` row the decision resolves. Then
   write the `/changelog` entry.
7. **Rule 5a**: the reasoning stands on its own merits. Never cite another codebase or its record numbers.
