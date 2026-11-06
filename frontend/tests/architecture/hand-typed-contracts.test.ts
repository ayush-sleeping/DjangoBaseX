/**
 * API shapes come from the generated contract, not from hand (FRONTEND_PLATFORM § 24, closes DB-4).
 *
 * The bug it prevents: a hand-typed client typechecks against yesterday's contract while being
 * wrong. (8.4a found two: User.roles was untyped in the contract, and the role editor mutated
 * fields the API marks read-only.) A response type is an alias of the generated
 * components["schemas"][…]; a view with no schema yet keeps a hand type ONLY while it is listed
 * here with the view that owes the schema (BUILD_ORDER 9.2).
 *
 * How: every exported object-literal type in src/core/lib/** must be listed below — as a wire type
 * awaiting a schema, or as client-only (not an API shape). Two-way ratchet: a new hand type fails,
 * and an entry whose type became an alias (or vanished) must be deleted.
 * Do NOT silence this by listing a new wire type — give its view a schema and alias it.
 */
import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

import { assertRatchet, type Hit, iterSources, rel } from "./walk";

const WIRE = "hand-written wire type until its view has an OpenAPI schema (BUILD_ORDER 9.2)";
const CLIENT = "client-only: not an API shape";
const LISTED: Record<string, string> = {
  "src/core/lib/auth.ts::Me": `${WIRE}: MeView`,
  "src/core/lib/bootstrap.ts::Bootstrap": `${WIRE}: BootstrapView assembles contributors`,
  "src/core/lib/bootstrap.ts::BootstrapUser": `${WIRE}: BootstrapView's user section`,
  "src/core/lib/identity.ts::Identity": `${WIRE}: PublicConfigView`,
  "src/core/lib/mfa.ts::MfaSetup": `${WIRE}: MfaSetupView`,
  "src/core/lib/rbac.ts::CatalogPermission": `${WIRE}: PermissionCatalogView`,
  "src/core/lib/rbac.ts::PermissionGroup": `${WIRE}: PermissionCatalogView`,
  "src/core/lib/rbac.ts::NewRole": `${WIRE}: the role create request has no request component yet`,
  "src/core/lib/api.ts::Page": "the DRF page envelope, generic over the generated row type",
  "src/core/lib/api/errors.ts::FieldError": "the decoded error envelope; the error catalogue export is BUILD_ORDER 9.2",
  "src/core/lib/api/errors.ts::ApiErrorInit": `${CLIENT}: the ApiError constructor's input`,
  "src/core/lib/auth.ts::SignInResult": `${CLIENT}: the outcome of the sign-in flow`,
  "src/core/lib/auth.ts::MfaStepFailure": `${CLIENT}: what the MFA step shows on failure`,
  "src/core/lib/list-state.ts::ListState": `${CLIENT}: URL list state`,
  "src/core/lib/permissions.tsx::Permissions": `${CLIENT}: the provider's context value`,
  "src/core/lib/plugin-pages.ts::PluginFrontend": `${CLIENT}: a plugin's frontend manifest`,
  "src/core/lib/query/keys.ts::Keys": `${CLIENT}: query-key factory typing`,
  "src/core/lib/query/refresh-failed.ts::RefreshFailed": `${CLIENT}: a toast event`,
  "src/core/lib/query/use-api-query.ts::ApiQueryResult": `${CLIENT}: the load-state contract`,
  "src/core/lib/query/use-api-query.ts::ListErrorProps": `${CLIENT}: ListLoadError's props`,
};

const OBJECT_TYPE = /^export type ([A-Za-z]+)(<[^>]*>)? = \{/gm;

describe("hand-typed contracts", () => {
  it("every exported object type in src/core/lib is generated, or listed with why it is not", () => {
    const hits: Hit[] = [];
    for (const file of iterSources()) {
      const path = rel(file);
      if (!path.startsWith("src/core/lib/")) continue;
      const text = readFileSync(file, "utf8");
      for (const match of text.matchAll(OBJECT_TYPE)) {
        hits.push({ path, line: text.slice(0, match.index).split("\n").length, value: match[1] });
      }
    }
    assertRatchet(hits, LISTED, "hand_typed_contracts");
  });

  it("the module types alias the generated contract", () => {
    const aliases: [string, RegExp][] = [
      ["src/core/lib/users.ts", /export type User = components\["schemas"\]\["User"\];/],
      ["src/core/lib/users.ts", /export type RoleRef = components\["schemas"\]\["RoleSummary"\];/],
      ["src/core/lib/invitations.ts", /export type Invitation = components\["schemas"\]\["Invitation"\];/],
      ["src/core/lib/rbac.ts", /export type Role = components\["schemas"\]\["Role"\];/],
    ];
    for (const [file, alias] of aliases) expect(readFileSync(`${__dirname}/../../${file}`, "utf8"), file).toMatch(alias);
  });
});
