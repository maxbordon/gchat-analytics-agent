from app.auth import ChatRequestAuthenticator

AUD = "https://bot.example.run.app"
ISSUER = "chat@system.gserviceaccount.com"
GOOD = {"aud": AUD, "email": ISSUER, "email_verified": True}


def make(claims=None, raises=False):
    def verifier(token, audience):
        if raises:
            raise ValueError("bad token")
        return claims
    return ChatRequestAuthenticator(AUD, ISSUER, verifier=verifier)


def test_valid_token_is_accepted():
    assert make(GOOD).check("Bearer abc").ok


def test_missing_header_is_rejected():
    assert make(GOOD).check(None).reason == "missing Bearer token"


def test_empty_token_is_rejected():
    assert make(GOOD).check("Bearer   ").reason == "empty token"


def test_unverifiable_token_is_rejected():
    assert not make(raises=True).check("Bearer abc").ok


def test_wrong_issuer_is_rejected():
    claims = {**GOOD, "email": "attacker@example.com"}
    assert make(claims).check("Bearer abc").reason == "unexpected issuer"


def test_unverified_email_is_rejected():
    claims = {**GOOD, "email_verified": False}
    assert make(claims).check("Bearer abc").reason == "email not verified"


def test_missing_audience_config_rejects_everything():
    auth = ChatRequestAuthenticator("", ISSUER, verifier=lambda t, a: GOOD)
    assert not auth.check("Bearer abc").ok
