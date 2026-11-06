import base64
from urllib.parse import quote

from gitnest.providers.base import GitProvider, ProviderError, RemoteFile


class GitHubProvider(GitProvider):
    API = "https://api.github.com"

    def _request(self, method: str, path: str, **kwargs):
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Authorization": f"Bearer {self.token}",
        }
        response = self.client.request(method, self.API + path, headers=headers, **kwargs)
        if response.is_error:
            raise ProviderError(
                f"GitHub API {response.status_code}: {response.text[:500]}",
                response.status_code,
            )
        return response

    def _repository_info(self) -> dict:
        return self._request(
            "GET", f"/repos/{quote(self.owner)}/{quote(self.repo)}"
        ).json()

    def _branch_diagnostic(self, default_branch: str | None) -> str:
        try:
            data = self._request(
                "GET",
                f"/repos/{quote(self.owner)}/{quote(self.repo)}/branches",
                params={"per_page": 100},
            ).json()
            names = [item.get("name", "") for item in data if item.get("name")]
        except Exception:
            names = []
        details = []
        if default_branch:
            details.append(f"仓库默认分支：{default_branch}")
        if names:
            details.append("可用分支：" + "、".join(names[:20]))
            if len(names) > 20:
                details.append(f"（仅显示前 20 个，共 {len(names)} 个）")
        return "；".join(details)

    def test_connection(self) -> None:
        # Repository access and branch validation are deliberately separate:
        # a 404 here usually means a wrong branch name, not a bad token.
        info = self._repository_info()
        default_branch = info.get("default_branch")
        configured = (self.branch or "").strip()
        if not configured:
            if not default_branch:
                raise ProviderError("仓库接口未返回默认分支，请手动填写分支名称")
            self.branch = default_branch
            return

        try:
            self._request(
                "GET",
                f"/repos/{quote(self.owner)}/{quote(self.repo)}/branches/{quote(configured, safe='')}",
            )
        except ProviderError as exc:
            if exc.status_code != 404:
                raise
            diagnostic = self._branch_diagnostic(default_branch)
            suffix = f"。{diagnostic}" if diagnostic else ""
            raise ProviderError(
                f"仓库可访问，但分支“{configured}”不存在。请填写实际分支名称"
                f"（分支栏留空可自动使用默认分支）{suffix}",
                404,
            ) from exc

    def list_path(self, path: str = "") -> list[RemoteFile]:
        suffix = "/" + quote(path, safe="/") if path else ""
        data = self._request(
            "GET",
            f"/repos/{quote(self.owner)}/{quote(self.repo)}/contents{suffix}",
            params={"ref": self.branch},
        ).json()
        if isinstance(data, dict):
            data = [data]
        return [
            RemoteFile(
                path=x["path"],
                name=x["name"],
                size=x.get("size", 0),
                sha=x.get("sha"),
                download_url=x.get("download_url"),
                type="dir" if x.get("type") == "dir" else "file",
            )
            for x in data
        ]

    def get_file(self, path: str) -> tuple[bytes, str | None]:
        data = self._request(
            "GET",
            f"/repos/{quote(self.owner)}/{quote(self.repo)}/contents/{quote(path, safe='/')}",
            params={"ref": self.branch},
        ).json()
        if data.get("encoding") == "base64" and data.get("content"):
            return base64.b64decode(data["content"]), data.get("sha")
        url = data.get("download_url")
        if not url:
            raise ProviderError("GitHub 未返回文件内容或下载地址")
        response = self.client.get(url)
        if response.is_error:
            raise ProviderError(f"下载失败：HTTP {response.status_code}", response.status_code)
        return response.content, data.get("sha")

    def put_file(self, path: str, content: bytes, message: str, sha: str | None = None) -> dict:
        payload = {
            "message": message,
            "content": base64.b64encode(content).decode("ascii"),
            "branch": self.branch,
        }
        if sha:
            payload["sha"] = sha
        return self._request(
            "PUT",
            f"/repos/{quote(self.owner)}/{quote(self.repo)}/contents/{quote(path, safe='/')}",
            json=payload,
        ).json()
