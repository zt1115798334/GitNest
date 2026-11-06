import base64
from urllib.parse import quote
import httpx
from gitnest.providers.base import GitProvider, ProviderError, RemoteFile

class GitHubProvider(GitProvider):
    API = "https://api.github.com"

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
                   "Authorization": f"Bearer {self.token}"}
        response = self.client.request(method, self.API + path, headers=headers, **kwargs)
        if response.is_error:
            raise ProviderError(f"GitHub API {response.status_code}: {response.text[:500]}", response.status_code)
        return response

    def test_connection(self) -> None:
        self._request("GET", f"/repos/{quote(self.owner)}/{quote(self.repo)}")
        self._request("GET", f"/repos/{quote(self.owner)}/{quote(self.repo)}/branches/{quote(self.branch, safe='')}")

    def list_path(self, path: str = "") -> list[RemoteFile]:
        suffix = "/" + quote(path, safe="/") if path else ""
        data = self._request("GET", f"/repos/{quote(self.owner)}/{quote(self.repo)}/contents{suffix}",
                             params={"ref": self.branch}).json()
        if isinstance(data, dict): data = [data]
        return [RemoteFile(path=x["path"], name=x["name"], size=x.get("size",0), sha=x.get("sha"),
                           download_url=x.get("download_url"), type="dir" if x.get("type")=="dir" else "file")
                for x in data]

    def get_file(self, path: str) -> tuple[bytes, str | None]:
        data = self._request("GET", f"/repos/{quote(self.owner)}/{quote(self.repo)}/contents/{quote(path, safe='/')}",
                             params={"ref": self.branch}).json()
        if data.get("encoding") == "base64" and data.get("content"):
            return base64.b64decode(data["content"]), data.get("sha")
        url = data.get("download_url")
        if not url: raise ProviderError("GitHub 未返回文件内容或下载地址")
        response = self.client.get(url)
        if response.is_error: raise ProviderError(f"下载失败：HTTP {response.status_code}", response.status_code)
        return response.content, data.get("sha")

    def put_file(self, path: str, content: bytes, message: str, sha: str | None = None) -> dict:
        payload = {"message": message, "content": base64.b64encode(content).decode("ascii"), "branch": self.branch}
        if sha: payload["sha"] = sha
        return self._request("PUT", f"/repos/{quote(self.owner)}/{quote(self.repo)}/contents/{quote(path, safe='/')}",
                             json=payload).json()
