# QIRA Proof — GitHub App activation (owner-controlled)

**Status:** GitHub authorization code and UI have passed mocked tests. Live GitHub App authorization has NOT been exercised because an actual GitHub App has not been registered in this deployment.

**Auth preview origin:**
https://qira-proof-auth-lab-20261115.bryanleonard237.workers.dev

## 1. Register a GitHub App

From GitHub: Settings → Developer settings → GitHub Apps → New GitHub App.

Suggested name: QIRA Proof Research (choose any available name; record the actual slug).

Use:
- Homepage URL: https://qira-proof-auth-lab-20261115.bryanleonard237.workers.dev/
- Callback URL: https://qira-proof-auth-lab-20261115.bryanleonard237.workers.dev/oauth/github/callback
- Setup URL (optional): https://qira-proof-auth-lab-20261115.bryanleonard237.workers.dev/
- Request user authorization (OAuth) during installation: **off**. The application explicitly starts the state+PKCE authorization flow.
- Repository permissions: **Contents: read-only**. Metadata: read-only (GitHub automatically grants it).
- Organization permissions: none.
- Webhook subscriptions: none (disable webhooks if optional).
- Where can this app be installed?: only your account during testing. Do not open it publicly until security review.

GitHub App auth docs:
https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-a-user-access-token-for-a-github-app

Security guidance:
https://docs.github.com/en/apps/creating-github-apps/registering-a-github-app/about-the-setup-url

## 2. Configure your Cloudflare Worker

The authentication runtime requires exactly five bindings:

| Binding | Type | Notes |
|---|---|---|
| QIRA_PUBLIC_ORIGIN | Text | The HTTPS origin above, without trailing slash |
| GITHUB_APP_CLIENT_ID | Text | From GitHub App settings, NOT App ID |
| GITHUB_APP_SLUG | Text | Actual slug visible in the app installation URL |
| GITHUB_APP_CLIENT_SECRET | Secret | Generate in GitHub; never paste into a chat, GitHub issue or repository |
| QIRA_SESSION_KEY | Secret | Fresh random 32-byte key encoded as unpadded base64url, length 43 |

Generate your session key locally:

    node -e "console.log(require('node:crypto').randomBytes(32).toString('base64url'))"

Set the two values as **Cloudflare Worker secrets**. You can use Wrangler's interactive secret prompt or the Cloudflare dashboard. Never commit the resulting key or client secret.

Example commands, run in your own trusted terminal:

    npx wrangler secret put GITHUB_APP_CLIENT_SECRET --name qira-proof-auth-lab-20261115
    npx wrangler secret put QIRA_SESSION_KEY --name qira-proof-auth-lab-20261115

The client ID and slug are not passwords; enter them as text Worker variables. The application requires an exact HTTPS origin and fails closed until all required bindings are present.

WARNING: any later redeployment must preserve these bindings. Confirm them in your Cloudflare account before deploying.

## 3. Test with your own account

1. Open the preview and confirm that the GitHub App connection shows "Ready" rather than "Pending setup".
2. Select **Connect GitHub**. GitHub will ask you to authorize the App via PKCE.
3. If it has not been installed, choose **Install read-only App** and grant access ONLY to your chosen test repository.
4. Reconnect, then select the installation → repository → workflow.
5. Run the **Assess selected workflow** action; verify that all findings cite the selected repository.
6. Review the downloaded evidence locally. Verify the report before treating any indicator as a factual configuration assertion.
7. Select **Disconnect**; a local session cookie is cleared. This is NOT revocation of GitHub authorization. Revoke the App separately under your GitHub account settings if needed.

## Data minimization on connected assessments

The browser sends selected repository and workflow names in a **same-origin POST
JSON body**, not an application URL query. The server requires the established
OAuth session, the exact application Origin, and a CSRF token. It verifies
installation and repository access again before reading a selected file.

Provider API calls use GET for listing and reading metadata. OAuth authorization
requires a separate code-exchange POST to GitHub. The Worker does not maintain
a database of selected repositories, but Cloudflare and GitHub may retain
infrastructure-level access logs. Do not interpret "no persistent application
database" as "no platform telemetry or provider logs."

## Scope and trust boundaries

- The GitHub App grants only the intersection of the installing user's access and the App permissions.
- The server verifies each requested installation and repository against GitHub *before* reading selected workflow content.
- Workflow source is processed ephemerally to produce a small normalized snapshot. The Worker does not persist raw source, account metadata, or tokens in D1, KV, R2 or logs.
- Sessions live in AES-GCM encrypted, HttpOnly, Secure, SameSite=Lax cookies; they expire in at most 15 minutes. PKCE state cookies expire after 10 minutes.
- Worker-encrypted cookies can still be replayed if stolen until expiration; no central server-side token revocation exists in this pilot. Github App authorization may outlive the browser session.
- No refresh tokens are saved. Expiring GitHub App tokens are required; nonexpiring token responses are rejected.
- A user access token is never returned to client JavaScript. GitHub server API calls are allowlisted and use GET only, aside from the required OAuth code exchange POST to GitHub.
- No active exploitation, arbitrary network scans, credential enumeration, or changes to customer resources are implemented.
- A disappearing heuristic indicator is not proof of remediation. Signed provider evidence and independent validation remain future work.
- This is NOT production multi-tenant authentication; audit externally before connecting other organizations.

## Automated verification

    node --test product/qira-proof/tests/*.test.mjs
    python -m unittest discover -s product/qira-proof/tests -p 'test_*.py' -v
    node product/qira-proof/build.mjs
    node --check product/qira-proof/dist/worker.mjs

The tests mock GitHub to exercise legitimate and malicious authorization flows. Passing them is necessary but does NOT prove live GitHub OAuth interoperability.

## Support references

- Main product branch: product/qira-proof-pilot-2026-11-15
- Isolated auth feature branch: product/qira-proof-github-app-auth-2026-11-15
- The baseline evidence snapshot and local fallback remain available without app registration.
- LOLM public site remains unchanged: https://lolm.imagineqira.com/
