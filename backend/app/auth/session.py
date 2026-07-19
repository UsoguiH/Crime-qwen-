from itsdangerous import BadSignature, URLSafeTimedSerializer

COOKIE_NAME = "athar_session"
MAX_AGE_S = 12 * 3600


def _serializer(secret_key: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(secret_key, salt="athar.session")


def encode_session(secret_key: str, user_id: str) -> str:
    return _serializer(secret_key).dumps({"uid": user_id})


def decode_session(secret_key: str, token: str) -> str | None:
    try:
        data = _serializer(secret_key).loads(token, max_age=MAX_AGE_S)
        return data.get("uid")
    except (BadSignature, Exception):
        return None
