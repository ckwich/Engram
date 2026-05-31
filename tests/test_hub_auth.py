from core.hub_auth import authorize_hub_request, load_hub_access_token, token_fingerprint


def test_hub_token_requires_minimum_length(monkeypatch):
    monkeypatch.setenv("ENGRAM_HUB_ACCESS_TOKEN", "too-short")

    result = load_hub_access_token()

    assert result["status"] == "policy_denied"
    assert result["error"]["code"] == "hub_access_token_too_short"


def test_authorize_hub_request_requires_bearer_token():
    result = authorize_hub_request({}, expected_token="x" * 40)

    assert result["authorized"] is False
    assert result["error"]["code"] == "hub_authorization_required"


def test_authorize_hub_request_accepts_matching_token_without_echoing_secret():
    token = "x" * 40

    result = authorize_hub_request({"Authorization": f"Bearer {token}"}, expected_token=token)

    assert result["authorized"] is True
    assert result["token_fingerprint"] == token_fingerprint(token)
    assert token not in str(result)
