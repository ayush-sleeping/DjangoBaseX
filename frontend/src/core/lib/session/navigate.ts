/**
 * The ONE way to leave the single-page app on purpose (FRONTEND_PLATFORM § 8.4, step 5). On an
 * identity change — sign-in, sign-out — a router push would keep the JavaScript heap, and with it
 * the previous identity's cached bootstrap, permissions and data. A full page load is the only
 * complete cache clear. Everything else navigates with the router.
 */
export function hardNavigate(path: string): void {
  window.location.assign(path);
}
