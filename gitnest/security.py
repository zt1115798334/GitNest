import keyring
from gitnest.config import KEYRING_SERVICE

def credential_key(repository: dict) -> str:
    return f"{repository['platform']}:{repository['owner']}/{repository['repo']}:{repository['branch']}"

def save_token(repository: dict, token: str) -> None:
    token = token.strip()
    if not token:
        raise ValueError("Token 不能为空")
    keyring.set_password(KEYRING_SERVICE, credential_key(repository), token)

def get_token(repository: dict) -> str | None:
    return keyring.get_password(KEYRING_SERVICE, credential_key(repository))

def delete_token(repository: dict) -> None:
    try:
        keyring.delete_password(KEYRING_SERVICE, credential_key(repository))
    except keyring.errors.PasswordDeleteError:
        pass
