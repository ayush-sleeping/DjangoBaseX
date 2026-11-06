"use client";

/** The Users index (BUILD_ORDER 8.3b reference module): composes ResourceIndex only. */
import { Mail, Plus } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button, buttonClass } from "@/core/components/Button";
import { SearchInput } from "@/core/components/SearchInput";
import { useListState } from "@/core/lib/list-state";
import { usePermissions } from "@/core/lib/permissions";
import { useApiList } from "@/core/lib/query";
import { listUsers, type User } from "@/core/lib/users";
import { ResourceIndex } from "@/core/shells";

import { USER_ACTIONS } from "./actions";
import { USER_COLUMNS, userHref, userLabel } from "./columns";
import { UserForm } from "./Form";
import { userKeys } from "./keys";

const getRowId = (user: User) => user.public_id;

export function UsersIndex() {
  const router = useRouter();
  const perms = usePermissions();
  const state = useListState();
  const [creating, setCreating] = useState(false);
  const query = { page: state.page, search: state.search };
  const list = useApiList<User>(userKeys.list(query), (signal) => listUsers(query.page, query.search, signal));
  const canCreate = perms.can(USER_ACTIONS.create.permission);
  const newUser = canCreate ? (
    <Button onClick={() => setCreating(true)}>
      <Plus aria-hidden className="size-4" /> New user
    </Button>
  ) : null;

  return (
    <ResourceIndex<User>
      pageKey="users.user.index"
      title="Users"
      noun="users"
      description="Everyone who can sign in, and what they hold."
      actions={
        <>
          {perms.can(USER_ACTIONS.invite.permission) ? (
            <Link href="/users/invitations" className={buttonClass("secondary")}>
              <Mail aria-hidden className="size-4" /> Invitations
            </Link>
          ) : null}
          {newUser}
        </>
      }
      toolbar={<SearchInput value={state.search} onSearch={state.setSearch} label="Search users" placeholder="Search by email or name" />}
      columns={USER_COLUMNS}
      list={list}
      getRowId={getRowId}
      getRowLabel={userLabel}
      page={state.page}
      onPage={state.setPage}
      queryIdentity={`search=${state.search}`}
      filtered={state.isFiltered}
      onClearFilters={state.clearFilters}
      emptyAction={newUser}
    >
      {canCreate ? (
        <UserForm
          layout="modal"
          open={creating}
          onClose={() => setCreating(false)}
          onSaved={(user) => {
            setCreating(false);
            router.push(userHref(user.public_id));
          }}
        />
      ) : null}
    </ResourceIndex>
  );
}
