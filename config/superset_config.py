"""The bi-superset module's Superset configuration (core decision 0089).

Sign-in with the core's OIDC provider, Superset roles from its `bi_roles`
claim, every query to Trino as the person (the connection mutator exchanges
the person's token for a Trino token), caches per person in Valkey, served
under SUPERSET_APP_ROOT (`/bi`). Secrets come from the files the
installation's agent writes (`/run/secrets/<name>`, quality-sdk decision
0009); the other settings from its `.env` (`QD_*`). Nothing here logs a
token or a secret.
"""

import hashlib
import os
import threading
import time
from urllib.parse import quote

import requests
from flask import g, has_request_context, request, session
from flask_appbuilder.security.manager import AUTH_OAUTH
from superset.security import SupersetSecurityManager

E = os.environ.get
SECRETS = E("QD_SECRETS_PATH", "/run/secrets")


def secret(name):
    with open(os.path.join(SECRETS, name)) as f:
        return f.read().strip()


def required(name):
    value = E(name)
    if not value:
        raise RuntimeError(f"{name} is not set")
    return value


# --- The application: its key, its metadata database, behind Traefik ----------
SECRET_KEY = secret("secret-key")
_DB = (f"postgresql+psycopg2://{quote(required('QD_DB_USER'))}:{quote(secret('database-password'), safe='')}"
       f"@{required('QD_DB_HOST')}:{E('QD_DB_PORT', '5432')}/{required('QD_DB_NAME')}")
SQLALCHEMY_DATABASE_URI = _DB + f"?sslmode=verify-full&sslrootcert={quote(required('QD_DB_CA_FILE'))}"
ENABLE_PROXY_FIX = True
PROXY_FIX_CONFIG = {"x_for": 1, "x_proto": 1, "x_host": 1, "x_port": 1, "x_prefix": 0}
SESSION_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
WTF_CSRF_ENABLED = True

# Superset's own Content-Security-Policy, kept under /bi (the route's
# middleware sets none) and framed by the application only (decision 0089,
# point 4.1 as ruled): no third-party origin, a nonce for scripts.
TALISMAN_ENABLED = True
TALISMAN_CONFIG = {
    "content_security_policy": {
        "base-uri": ["'self'"],
        "default-src": ["'self'"],
        "img-src": ["'self'", "blob:", "data:"],
        "worker-src": ["'self'", "blob:"],
        "connect-src": ["'self'"],
        "object-src": "'none'",
        "style-src": ["'self'", "'unsafe-inline'"],
        "font-src": ["'self'"],
        "script-src": ["'self'", "'strict-dynamic'"],
        "frame-ancestors": ["'self'"],
    },
    "content_security_policy_nonce_in": ["script-src"],
    "frame_options": "SAMEORIGIN",
    "force_https": False,
    "session_cookie_secure": True,
}

# --- Sign-in: the core's provider, the only one; roles from bi_roles -----------
ISSUER = required("QD_OIDC_ISSUER").rstrip("/")
AUTH_TYPE = AUTH_OAUTH
AUTH_USER_REGISTRATION = True
AUTH_USER_REGISTRATION_ROLE = None
AUTH_ROLES_SYNC_AT_LOGIN = True
AUTH_ROLES_MAPPING = {"viewer": ["QD Viewer"], "author": ["QD Author"], "admin": ["Admin"]}
ROLE_CLAIM = "bi_roles"
OAUTH_PROVIDERS = [{
    "name": "qd", "icon": "fa-key", "token_key": "access_token",
    "remote_app": {
        "client_id": required("QD_OIDC_PEOPLE_CLIENT_ID"), "client_secret": secret("oidc-people-secret"),
        "server_metadata_url": ISSUER + "/.well-known/openid-configuration",
        "client_kwargs": {"scope": "openid email profile", "code_challenge_method": "S256"},
    },
}]


class QdSecurityManager(SupersetSecurityManager):
    """The username is the account id; no role claim, no entry."""

    def oauth_user_info(self, provider, response=None):
        claims = (response or {}).get("userinfo") or {}
        roles = claims.get(ROLE_CLAIM) or []
        # Flask-AppBuilder would register a person with no mapped role as a
        # user with no role: no username refuses the sign-in instead.
        if not roles:
            return {"username": None}
        return {"username": claims["sub"], "email": claims.get("email", ""),
                "first_name": claims.get("name", ""), "last_name": "", "role_keys": roles}


CUSTOM_SECURITY_MANAGER = QdSecurityManager

_LOCK = threading.Lock()
_BY_USER = {}  # account id -> the person's latest access token: this process's memory only


def _session_token():
    """The person's access token, where Flask-AppBuilder keeps it."""
    pair = session.get("oauth")
    return pair[0] if pair else None


def _token_exp(token):
    import jwt

    try:
        return jwt.decode(token, options={"verify_signature": False})["exp"]
    except Exception:  # noqa: BLE001
        return None


def _before_request():
    """Ends Superset's session once the provider's token has expired (Flask
    refreshes the session on every request, so its lifetime alone does not),
    and remembers a signed-in person's token by account id for SQL Lab, which
    runs in a request context of its own with no session."""
    token = _session_token()
    if token is None:
        return None
    exp = _token_exp(token)
    if exp is not None and exp <= time.time():
        from flask_login import logout_user

        logout_user()
        session.clear()
        return None
    from flask_login import current_user

    if getattr(current_user, "is_authenticated", False) and not getattr(current_user, "is_guest_user", False):
        with _LOCK:
            _BY_USER[current_user.username] = token
    return None


def FLASK_APP_MUTATOR(app):  # noqa: N802
    app.before_request(_before_request)


# --- Caches: Valkey, per person; no async queries, no Celery -------------------
_VALKEY = f"redis://:{quote(secret('valkey-password'), safe='')}@{E('QD_VALKEY_HOST', 'valkey')}:6379"
DATA_CACHE_SECONDS = 60  # decision 0089 point 3.6 as ruled: a withdrawn permission within a minute
CACHE_CONFIG = {"CACHE_TYPE": "RedisCache", "CACHE_DEFAULT_TIMEOUT": 300, "CACHE_KEY_PREFIX": "superset_",
                "CACHE_REDIS_URL": _VALKEY + "/0"}
DATA_CACHE_CONFIG = {"CACHE_TYPE": "RedisCache", "CACHE_DEFAULT_TIMEOUT": DATA_CACHE_SECONDS,
                     "CACHE_KEY_PREFIX": "data_", "CACHE_REDIS_URL": _VALKEY + "/1"}
FILTER_STATE_CACHE_CONFIG = dict(CACHE_CONFIG, CACHE_KEY_PREFIX="filter_")
EXPLORE_FORM_DATA_CACHE_CONFIG = dict(CACHE_CONFIG, CACHE_KEY_PREFIX="explore_")
RATELIMIT_STORAGE_URI = _VALKEY + "/2"

# Sessions server-side in Valkey (decision 0089, point 5 as ruled): the
# cookie holds a session id; the person's access token never travels in it.
SESSION_SERVER_SIDE = True
SESSION_TYPE = "redis"


def _session_store():
    from redis import Redis

    return Redis.from_url(_VALKEY + "/3")


SESSION_REDIS = _session_store()

FEATURE_FLAGS = {
    "EMBEDDED_SUPERSET": True,
    "CACHE_QUERY_BY_USER": True,
    "GLOBAL_ASYNC_QUERIES": False,
    "ALERT_REPORTS": False,
    "ENABLE_TEMPLATE_PROCESSING": False,
}

# --- Embedded: the core signs guest tokens (ES256); Superset holds its public key
if E("QD_GUEST_PUBLIC_KEY_FILE"):
    with open(E("QD_GUEST_PUBLIC_KEY_FILE")) as _f:
        GUEST_TOKEN_JWT_SECRET = _f.read()
    GUEST_TOKEN_JWT_ALGO = "ES256"
    GUEST_TOKEN_JWT_AUDIENCE = required("QD_OIDC_PEOPLE_CLIENT_ID")
    GUEST_ROLE_NAME = "QD Guest"  # no datasource permission: a guest reads through its dashboard only

# --- The connection mutator: each statement with the person's own Trino token ---
_TRINO = {}  # sha256(subject token) -> (Trino token, exp): this process's memory only
_TOKEN_URL = []


def _token_url():
    if not _TOKEN_URL:
        meta = requests.get(ISSUER + "/.well-known/openid-configuration", timeout=10)
        meta.raise_for_status()
        _TOKEN_URL.append(meta.json()["token_endpoint"])
    return _TOKEN_URL[0]


def _issue(data):
    auth = (required("QD_OIDC_MACHINE_CLIENT_ID"), secret("oidc-machine-secret"))
    r = requests.post(_token_url(), data=data, auth=auth, timeout=10)
    r.raise_for_status()
    body = r.json()
    return body["access_token"], time.time() + body["expires_in"]


def _trino_token(subject):
    key = hashlib.sha256((subject or "client").encode()).hexdigest()
    with _LOCK:
        hit = _TRINO.get(key)
    if hit and hit[1] - 30 > time.time():
        return hit[0]
    if subject:
        tok = _issue({"grant_type": "urn:ietf:params:oauth:grant-type:token-exchange", "audience": "trino",
                      "subject_token": subject,
                      "subject_token_type": "urn:ietf:params:oauth:token-type:access_token"})
    else:
        tok = _issue({"grant_type": "client_credentials", "audience": "trino"})
    with _LOCK:
        _TRINO[key] = tok
    return tok[0]


def _subject():
    """The subject token of this connection: the guest token, the session's,
    or the person's remembered by account id; None for no person."""
    if not has_request_context():
        return None
    user = getattr(g, "user", None)
    if getattr(user, "is_guest_user", False):
        return request.headers.get("X-GuestToken") or request.form.get("guest_token")
    token = _session_token()
    if token:
        return token
    with _LOCK:
        return _BY_USER.get(getattr(user, "username", None))


def DB_CONNECTION_MUTATOR(uri, params, username, security_manager, source):  # noqa: N802
    import jwt
    from trino.auth import JWTAuthentication

    token = _trino_token(_subject())
    trino_user = jwt.decode(token, options={"verify_signature": False})["sub"]
    http = requests.Session()
    http.verify = E("QD_TRINO_CA_FILE") or required("QD_DB_CA_FILE")
    if E("QD_MACHINE_CERT_FILE"):
        http.cert = (E("QD_MACHINE_CERT_FILE"), required("QD_MACHINE_KEY_FILE"))
    args = params.setdefault("connect_args", {})
    args.update({"http_scheme": "https", "auth": JWTAuthentication(token), "http_session": http})
    return uri.set(username=trino_user, password=None), params
