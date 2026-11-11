import base64
from urllib.parse import quote
import httpx
from gitnest.providers.base import GitProvider, ProviderError, RemoteFile

class GiteeProvider(GitProvider):
    API = "https://gitee.com/api/v5"

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        params = dict(kwargs.pop("params", {}) or {})
        params["access_token"] = self.token
        response = self.client.request(method, self.API + path, params=params, **kwargs)
        if response.is_error:
            raise ProviderError(f"Gitee API {response.status_code}: {response.text[:500]}", response.status_code)
        return response

    def _ensure_branch(self) -> None:
        if self.branch:
            return
        info = self._request("GET", f"/repos/{quote(self.owner)}/{quote(self.repo)}").json()
        self.branch = info.get("default_branch") or ""
        if not self.branch:
            raise ProviderError("Gitee 仓库未返回默认分支，请在仓库配置中手动填写分支")

    def test_connection(self) -> None:
        self._ensure_branch()
        self._request("GET", f"/repos/{quote(self.owner)}/{quote(self.repo)}/branches/{quote(self.branch, safe='')}")

    def list_path(self, path: str = "") -> list[RemoteFile]:
        self._ensure_branch()
        suffix = "/" + quote(path, safe="/") if path else ""
        data = self._request("GET", f"/repos/{quote(self.owner)}/{quote(self.repo)}/contents{suffix}",
                             params={"ref": self.branch}).json()
        if isinstance(data, dict): data = [data]
        result = []
        for x in data:
            kind = x.get("type", "file")
            result.append(RemoteFile(path=x.get("path", ""), name=x.get("name", ""),
                size=x.get("size",0), sha=x.get("sha"), download_url=x.get("download_url"),
                type="dir" if kind in ("dir", "tree") else "file"))
        return result

    def get_file(self, path: str) -> tuple[bytes, str | None]:
        self._ensure_branch()
        data = self._request("GET", f"/repos/{quote(self.owner)}/{quote(self.repo)}/contents/{quote(path, safe='/')}",
                             params={"ref": self.branch}).json()
        encoded = data.get("content")
        if encoded:
            try: return base64.b64decode(encoded), data.get("sha")
            except Exception: pass
        url = data.get("download_url")
        if not url: raise ProviderError("Gitee 未返回文件内容或下载地址")
        response = self.client.get(url)
        if response.is_error: raise ProviderError(f"下载失败：HTTP {response.status_code}", response.status_code)
        return response.content, data.get("sha")

    def put_file(self, path: str, content: bytes, message: str, sha: str | None = None) -> dict:
        self._ensure_branch()
        payload = {"access_token": self.token, "content": base64.b64encode(content).decode("ascii"),
                   "message": message, "branch": self.branch}
        if sha: payload["sha"] = sha
        response = self.client.put(f"{self.API}/repos/{quote(self.owner)}/{quote(self.repo)}/contents/{quote(path, safe='/')}",
                                   data=payload, timeout=60)
        if response.is_error:
            raise ProviderError(f"Gitee API {response.status_code}: {response.text[:500]}", response.status_code)
        return response.json()
