from abc import ABC, abstractmethod
from dataclasses import dataclass
import httpx

class ProviderError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code

@dataclass(slots=True)
class RemoteFile:
    path: str
    name: str
    size: int = 0
    sha: str | None = None
    download_url: str | None = None
    type: str = "file"

class GitProvider(ABC):
    def __init__(self, owner: str, repo: str, branch: str, token: str):
        self.owner, self.repo, self.branch, self.token = owner, repo, branch, token
        self.client = httpx.Client(timeout=httpx.Timeout(60, connect=15), follow_redirects=True)

    def close(self) -> None:
        self.client.close()

    @abstractmethod
    def list_path(self, path: str = "") -> list[RemoteFile]: ...
    @abstractmethod
    def get_file(self, path: str) -> tuple[bytes, str | None]: ...
    @abstractmethod
    def put_file(self, path: str, content: bytes, message: str, sha: str | None = None) -> dict: ...
    @abstractmethod
    def test_connection(self) -> None: ...

    def list_images(self, base_path: str) -> list[RemoteFile]:
        from gitnest.images import is_image_path, safe_remote_path
        root = safe_remote_path(base_path) if base_path.strip("/") else ""
        pending = [root]
        found: list[RemoteFile] = []
        visited: set[str] = set()
        while pending:
            current = pending.pop()
            if current in visited:
                continue
            visited.add(current)
            for item in self.list_path(current):
                if item.type == "dir":
                    pending.append(item.path)
                elif is_image_path(item.path):
                    found.append(item)
        return sorted(found, key=lambda x: x.path.casefold())
