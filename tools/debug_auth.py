"""Debug authentication flow to generate tokens."""

import asyncio
from pathlib import Path
from types import SimpleNamespace

import httpx

from custom_components.govee.auth import GoveeAuthManager

P12_BUNDLE = """(P12 removed)"""


class StubHass:
    """Minimal Home Assistant stub for auth debugging."""

    def __init__(self, loop, config_dir):
        """Initialize the stub hass."""
        self.loop = loop

        def _path(*parts):
            """Construct a path within the config directory."""
            return str(Path(config_dir).joinpath(*parts))

        self.config = SimpleNamespace(config_dir=config_dir, path=_path)
        self.state = SimpleNamespace(name="running")
        self.data = {}

    async def async_add_executor_job(self, func, *args):
        """Run a function in an executor."""
        return await asyncio.get_running_loop().run_in_executor(None, func, *args)


async def main():
    """Run a debug authentication flow to generate tokens."""
    # trunk-ignore(bandit/B108)
    tmp = Path("/tmp")
    loop = asyncio.get_running_loop()
    hass = StubHass(loop, str(tmp))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "status": 200,
                "client": {
                    "accountId": "123",
                    "client": "generated-client",
                    "topic": "topic/123",
                    "token": "access",
                    "refreshToken": "refresh",
                    "tokenExpireCycle": 120,
                },
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    manager = GoveeAuthManager(hass, client)
    await manager.async_initialize()
    # Not calling login because handler expects login else


if __name__ == "__main__":
    asyncio.run(main())
