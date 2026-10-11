"""The users app's anonymous surface (registered in UsersConfig.ready(); TECH_DEBT DB-22)."""

PUBLIC_ROUTES: dict[str, str] = {
    "users:login": "The front door. Same answer for every failure; attempts recorded (Ch. 6.2).",
    "users:password-forgot": "Pre-authentication by definition. Always answers 204 (Ch. 6.6).",
    "users:password-reset": "Authenticated by the single-use reset token itself (Ch. 6.6).",
    "users:mfa-verify": "Authenticated by the password step's single-use mfa_token (Ch. 6.8).",
    "users:invitation-accept": "Authenticated by the single-use invitation token itself (§ 3.5).",
    "users:refresh": "Authenticated by the refresh cookie itself, not an access token (Ch. 6.3).",
}
