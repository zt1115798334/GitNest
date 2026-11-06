from gitnest.providers.github import GitHubProvider
from gitnest.providers.gitee import GiteeProvider

def create_provider(repository: dict, token: str):
    platform = repository["platform"].lower()
    cls = {"github": GitHubProvider, "gitee": GiteeProvider}.get(platform)
    if cls is None: raise ValueError(f"不支持的平台：{platform}")
    return cls(repository["owner"], repository["repo"], repository["branch"], token)
