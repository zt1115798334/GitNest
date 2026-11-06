from gitnest.providers.factory import create_provider
from gitnest.providers.github import GitHubProvider
from gitnest.providers.gitee import GiteeProvider

def test_provider_factory():
    common={"owner":"someone","repo":"images","branch":"main"}
    assert isinstance(create_provider({**common,"platform":"github"},"token"),GitHubProvider)
    assert isinstance(create_provider({**common,"platform":"gitee"},"token"),GiteeProvider)
