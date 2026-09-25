# Keep account data private

This prototype handles credentials and may return private calendar data. It is not security-audited software and has no security-response service-level commitment.

- Never post tokens, refresh tokens, browser storage, cookies, HAR files, screenshots of account details, or real reminder/calendar contents in an issue or pull request.
- Use synthetic data in examples and tests.
- Treat successful CLI output as private; the client does not anonymize account data that you ask it to display.
- A local `.env` is plaintext. Keep it out of shared folders, source control, support bundles, and public logs. Restrictive permissions do not encrypt it.
- If a credential is exposed, revoke or rotate it through the service's supported account process. Deleting a public file does not invalidate its old contents.

For a sensitive finding, use an established private contact with the maintainer. If none is available, request a private reporting channel without including exploit details or secrets. Do not post a sensitive report publicly. For a service-side issue, use Skylight's official support or reporting process; this repository is not operated by Skylight.
