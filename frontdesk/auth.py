"""Password and opaque session primitives. Never persist or log raw credentials."""
import hashlib
import secrets


def hash_password(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return "scrypt$" + salt.hex() + "$" + digest.hex()


def verify_password(password, encoded):
    # Missing/inactive accounts still do the same expensive password derivation.
    _, salt, expected = (encoded or DUMMY_HASH).split("$")
    actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=2**14, r=8, p=1, dklen=32)
    return secrets.compare_digest(actual, bytes.fromhex(expected))


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


DUMMY_HASH = hash_password(secrets.token_hex(32))

