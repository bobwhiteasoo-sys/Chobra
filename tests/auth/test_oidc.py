import json
import time
from dataclasses import replace
from urllib.parse import parse_qs, urlsplit

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from fastapi.testclient import TestClient

from chobra_api import oidc
from chobra_api.config import Settings
from chobra_api.deps import get_db
from chobra_api.errors import ApiError, install
from chobra_api.routers import oidc as routes

CONFIG = Settings(auth_mode="oidc", oidc_issuer="https://id.example", oidc_client_id="app", oidc_client_secret="secret", oidc_redirect_uri="https://app.example/api/v1/auth/oidc/callback", signing_key="test-signing-material", secure_cookies=True)
META = {"issuer": CONFIG.oidc_issuer, "authorization_endpoint": "https://id.example/authorize", "token_endpoint": "https://id.example/token", "jwks_uri": "https://id.example/keys", "response_types_supported": ["code"], "id_token_signing_alg_values_supported": ["RS256"]}
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
JWK = {**json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(KEY.public_key())), "kid": "key", "use": "sig", "alg": "RS256"}


def claims(**overrides):
    return {"iss": CONFIG.oidc_issuer, "sub": "person", "aud": "app", "iat": int(time.time()), "exp": int(time.time()) + 60, "nonce": "nonce", **overrides}


def signed(data, key=KEY):
    return jwt.encode(data, key, algorithm="RS256", headers={"kid": "key"})


def test_valid_signature_and_claims():
    assert oidc.verify_id_token(signed(claims()), {"keys": [JWK]}, CONFIG, "nonce", META)["sub"] == "person"


@pytest.mark.parametrize("overrides", [{"iss": "https://evil.example"}, {"aud": "other"}, {"nonce": "other"}, {"exp": 1}, {"aud": ["app", "other"]}, {"azp": "other"}, {"sub": ""}, {"iat": int(time.time()) + 3600}])
def test_invalid_claims(overrides):
    with pytest.raises(ApiError):
        oidc.verify_id_token(signed(claims(**overrides)), {"keys": [JWK]}, CONFIG, "nonce", META)


def test_invalid_signature_and_none_algorithm():
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    for token in [signed(claims(), other), jwt.encode(claims(), "", algorithm="none"), jwt.encode(claims(), "secret", algorithm="HS256")]:
        with pytest.raises(ApiError):
            oidc.verify_id_token(token, {"keys": [JWK]}, CONFIG, "nonce", META)


def test_browser_state_and_pkce():
    data, cookie = oidc.transaction(b"x" * 32, "/projects")
    assert oidc.read_transaction(cookie, data["state"], b"x" * 32) == data
    params = parse_qs(urlsplit(oidc.authorization_url(META, CONFIG, data)).query)
    assert params["code_challenge_method"] == ["S256"]
    assert params["nonce"] == [data["nonce"]]
    assert data["verifier"] not in str(params)
    for bad_cookie, state in [(cookie[:-8] + "tampered", data["state"]), (cookie, "other"), (None, data["state"]), (jwt.encode({**data, "iat": 0, "exp": 300}, b"x" * 32, algorithm="HS256"), data["state"])]:
        with pytest.raises(ApiError):
            oidc.read_transaction(bad_cookie, state, b"x" * 32)


@pytest.mark.parametrize("url", ["//evil.example", "https://evil.example", "/\\evil.example", "/%2fevil.example", "/\nevil.example", "/api/v1/auth/oidc/start"])
def test_safe_next(url):
    assert oidc.safe_next(url) == "/"


def test_missing_configuration_and_unsafe_endpoint():
    with pytest.raises(ApiError) as error:
        oidc.configured(replace(CONFIG, oidc_issuer=""))
    assert error.value.status == 503
    for url in ["http://id.example", "http://localhost:8000", "https://user:pass@id.example", "https://id.example/#fragment"]:
        with pytest.raises(ApiError):
            oidc.endpoint(url, CONFIG)


def test_transport_exchange_and_replay():
    data, _ = oidc.transaction(b"x" * 32)
    used = False
    def transport(request):
        nonlocal used
        if request.url.path.endswith("openid-configuration"):
            return httpx.Response(200, json=META)
        if request.url.path == "/keys":
            return httpx.Response(200, json={"keys": [JWK]})
        assert request.url.path == "/token" and request.method == "POST"
        payload = parse_qs(request.content.decode())
        assert payload["code_verifier"] == [data["verifier"]]
        assert payload["redirect_uri"] == [CONFIG.oidc_redirect_uri]
        assert request.headers["Authorization"].startswith("Basic ")
        assert "secret" not in str(request.url)
        if used:
            return httpx.Response(400, json={"error": "invalid_grant"})
        used = True
        return httpx.Response(200, json={"id_token": signed(claims(nonce=data["nonce"]))})
    with httpx.Client(transport=httpx.MockTransport(transport), follow_redirects=False) as client:
        metadata = oidc.discovery(client, CONFIG)
        assert oidc.exchange(client, metadata, CONFIG, "one-time-code", data)["sub"] == "person"
        with pytest.raises(httpx.HTTPStatusError):
            oidc.exchange(client, metadata, CONFIG, "one-time-code", data)


def test_discovery_rejects_wrong_issuer_and_http_jwks():
    for altered in [{**META, "issuer": "https://other.example"}, {**META, "jwks_uri": "http://id.example/keys"}]:
        with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=altered))) as client:
            with pytest.raises(ApiError):
                oidc.discovery(client, CONFIG)


def test_routes_missing_config_and_state_rejection(monkeypatch):
    app = FastAPI()
    install(app)
    app.include_router(routes.router, prefix="/api/v1")
    app.dependency_overrides[get_db] = lambda: None
    monkeypatch.setattr(routes, "settings", replace(CONFIG, oidc_issuer=""))
    with TestClient(app, base_url="https://app.example") as client:
        assert client.get("/api/v1/auth/oidc/start").status_code == 503
        monkeypatch.setattr(routes, "settings", CONFIG)
        monkeypatch.setattr(routes, "signing_key", lambda: b"x" * 32)
        monkeypatch.setattr(routes, "client", lambda: httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=META))))
        result = client.get("/api/v1/auth/oidc/start", follow_redirects=False)
        assert result.status_code == 302
        assert "HttpOnly" in result.headers["set-cookie"] and "Secure" in result.headers["set-cookie"]
        result = client.get("/api/v1/auth/oidc/callback?state=wrong&code=code")
        assert result.status_code == 400
        assert "Max-Age=0" in result.headers["set-cookie"]
        assert result.headers["cache-control"] == "no-store"


def test_next_preserves_internal_replay_position():
    target = "/runs/abc/replay?seq=28#event-28"
    assert oidc.safe_next(target) == target
