"""Verification of the OIDC token Google Chat attaches to every request.

Cloud Run is deployed with public ingress (Chat has to reach it), so the
service itself must prove each request comes from Google Chat. We check:
signature + expiry, audience, verified email and the expected issuer.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

logger = logging.getLogger(__name__)

# (token, audience) -> claims. Raises on invalid tokens. Injectable for tests.
TokenVerifier = Callable[[str, str], dict]


def google_token_verifier(token: str, audience: str) -> dict:
    # Imported lazily so mock mode and unit tests don't need google-auth.
    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token

    return id_token.verify_oauth2_token(token, google_requests.Request(), audience=audience)


@dataclass
class AuthResult:
    ok: bool
    reason: str = ""


class ChatRequestAuthenticator:
    def __init__(self, audience: str, issuer_email: str, verifier: TokenVerifier | None = None):
        self.audience = audience
        self.issuer_email = issuer_email
        self._verify = verifier or google_token_verifier

    def check(self, authorization_header: str | None) -> AuthResult:
        if not self.audience:
            return self._reject("audience not configured")

        header = authorization_header or ""
        if not header.startswith("Bearer "):
            return self._reject("missing Bearer token")

        token = header[len("Bearer "):].strip()
        if not token:
            return self._reject("empty token")

        try:
            claims = self._verify(token, self.audience)
        except Exception:  # bad signature, expired, wrong audience...
            return self._reject("token could not be verified")

        if claims.get("aud") != self.audience:
            return self._reject("audience mismatch")
        if not claims.get("email_verified"):
            return self._reject("email not verified")
        if claims.get("email") != self.issuer_email:
            return self._reject("unexpected issuer")

        return AuthResult(ok=True)

    @staticmethod
    def _reject(reason: str) -> AuthResult:
        logger.warning("Rejected request: %s", reason)
        return AuthResult(ok=False, reason=reason)
