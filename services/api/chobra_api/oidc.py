"""OIDC code flow primitives; network inputs are never trusted as JWT key URLs."""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from urllib.parse import urlencode, urlsplit, quote_plus

import httpx
import jwt

from .errors import ApiError

TTL = 300
ALGORITHMS = frozenset({"RS256", "RS384", "RS512", "ES256", "ES384", "ES512", "PS256", "PS384", "PS512"})


def failed():
    return ApiError(400, "OIDC_FAILED", "Вход не подтвержден. Начните вход заново.")


def endpoint(url, config):
    if not isinstance(url, str):
        raise ApiError(503, "OIDC_CONFIG", "Администратор должен настроить OIDC.")
    p = urlsplit(url)
    local = getattr(config, "oidc_allow_insecure_localhost", False) and p.hostname in {"localhost", "127.0.0.1", "::1"}
    if not p.hostname or p.username or p.password or p.fragment or not (p.scheme == "https" or (p.scheme == "http" and local)):
        raise ApiError(503, "OIDC_CONFIG", "OIDC требует безопасные HTTPS адреса.")
    return url


def configured(config):
    if config.auth_mode != "oidc":
        raise ApiError(404, "NOT_FOUND", "OIDC не включен.")
    if not config.oidc_issuer or not config.oidc_client_id:
        raise ApiError(503, "OIDC_CONFIG", "Провайдер входа OIDC еще не настроен.")
    endpoint(config.oidc_issuer, config)
    endpoint(config.oidc_redirect_uri, config)
    if urlsplit(config.oidc_issuer).query:
        raise ApiError(503, "OIDC_CONFIG", "Некорректный issuer OIDC.")


def safe_next(value):
    # Only application-relative paths, without encoded delimiters or browser URL ambiguity.
    if not isinstance(value, str) or len(value) > 1000 or not value.startswith("/") or value.startswith("//"):
        return "/"
    if any(c in value for c in ("\\", "%")) or any(ord(c) <= 32 or ord(c) == 127 for c in value):
        return "/"
    if value.startswith(("/api", "/login", "/auth")):
        return "/"
    return value


def transaction(key, next_path="/"):
    stamp = int(time.time())
    data = {"state": secrets.token_urlsafe(32), "nonce": secrets.token_urlsafe(32), "verifier": secrets.token_urlsafe(48),
            "next": safe_next(next_path), "iat": stamp, "exp": stamp + TTL, "purpose": "oidc"}
    return data, jwt.encode(data, key, algorithm="HS256")


def read_transaction(cookie, state, key):
    try:
        data = jwt.decode(cookie, key, algorithms=["HS256"], options={"require": ["exp", "iat", "state", "nonce", "verifier", "purpose"]})
        if data["purpose"] != "oidc" or data["exp"] - data["iat"] > TTL:
            raise ValueError()
        if not isinstance(state, str) or not isinstance(data["state"], str) or not hmac.compare_digest(data["state"], state):
            raise ValueError()
        if not all(isinstance(data[x], str) and len(data[x]) >= 32 for x in ("nonce", "verifier")):
            raise ValueError()
        return data
    except (jwt.PyJWTError, ValueError, TypeError):
        raise failed() from None


def json_response(response):
    response.raise_for_status()
    result = response.json()
    if not isinstance(result, dict):
        raise ValueError("Invalid provider response")
    return result


def discovery(client, config):
    data = json_response(client.get(config.oidc_issuer.rstrip("/") + "/.well-known/openid-configuration"))
    if data.get("issuer") != config.oidc_issuer:
        raise failed()
    for field in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
        endpoint(data.get(field), config)
    if "code" not in data.get("response_types_supported", []):
        raise failed()
    return data


def authorization_url(metadata, config, data):
    challenge = base64.urlsafe_b64encode(hashlib.sha256(data["verifier"].encode()).digest()).rstrip(b"=").decode()
    params = {"client_id": config.oidc_client_id, "redirect_uri": config.oidc_redirect_uri, "response_type": "code",
              "scope": "openid profile email", "state": data["state"], "nonce": data["nonce"],
              "code_challenge": challenge, "code_challenge_method": "S256", "response_mode": "query"}
    url = metadata["authorization_endpoint"]
    return url + ("&" if "?" in url else "?") + urlencode(params)


def verify_id_token(token, jwks, config, nonce, metadata):
    try:
        header = jwt.get_unverified_header(token)
        alg = header.get("alg")
        if alg not in ALGORITHMS or alg not in metadata.get("id_token_signing_alg_values_supported", ["RS256"]):
            raise ValueError()
        keys = [k for k in jwks.get("keys", []) if isinstance(k, dict)
                and (header.get("kid") is None or k.get("kid") == header["kid"])
                and k.get("use", "sig") == "sig" and "verify" in k.get("key_ops", ["verify"])
                and k.get("alg", alg) == alg]
        if len(keys) != 1:
            raise ValueError()
        key = jwt.PyJWK.from_dict(keys[0], algorithm=alg).key
        claims = jwt.decode(token, key, algorithms=[alg], audience=config.oidc_client_id, issuer=config.oidc_issuer,
                            options={"require": ["exp", "iat", "iss", "aud", "sub", "nonce"]})
        if not isinstance(claims["nonce"], str) or not hmac.compare_digest(claims["nonce"], nonce):
            raise ValueError()
        aud = claims["aud"]
        if (isinstance(aud, list) and len(aud) > 1 and claims.get("azp") != config.oidc_client_id) or ("azp" in claims and claims["azp"] != config.oidc_client_id):
            raise ValueError()
        if not isinstance(claims["sub"], str) or not 1 <= len(claims["sub"]) <= 300:
            raise ValueError()
        return claims
    except (jwt.PyJWTError, ValueError, TypeError, KeyError):
        raise failed() from None


def exchange(client, metadata, config, code, data):
    payload = {"grant_type": "authorization_code", "code": code, "redirect_uri": config.oidc_redirect_uri,
               "client_id": config.oidc_client_id, "code_verifier": data["verifier"]}
    auth = None
    if config.oidc_client_secret:
        methods = metadata.get("token_endpoint_auth_methods_supported", ["client_secret_basic"])
        if "client_secret_basic" in methods:
            auth = httpx.BasicAuth(quote_plus(config.oidc_client_id), quote_plus(config.oidc_client_secret))
        elif "client_secret_post" in methods:
            payload["client_secret"] = config.oidc_client_secret
        else:
            raise ApiError(503, "OIDC_CONFIG", "Метод аутентификации OIDC не поддерживается.")
    tokens = json_response(client.post(metadata["token_endpoint"], data=payload, auth=auth))
    jwks = json_response(client.get(metadata["jwks_uri"]))
    return verify_id_token(tokens.get("id_token", ""), jwks, config, data["nonce"], metadata)
