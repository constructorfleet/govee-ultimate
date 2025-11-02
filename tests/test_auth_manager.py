"""Tests for the auth manager."""

from __future__ import annotations

import asyncio
import inspect
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from custom_components.govee.auth import (
    AccountAuthDetails,
    GoveeAuthManager,
    IoTBundle,
)

P12_BUNDLE = (
    "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"
    "BAgKTBxHyPmM+QICCAA="
)

EXPECTED_CERTIFICATE = """-----BEGIN CERTIFICATE-----
MIIDRTCCAi2gAwIBAgIUSso/geYoFJYoX1D2tLnsF2yaF2owDQYJKoZIhvcNAQEL
BQAwMjELMAkGA1UEBhMCVVMxDTALBgNVBAoMBFRlc3QxFDASBgNVBAMMC2V4YW1w
bGUuY29tMB4XDTI1MTEwMTEyMTMzMVoXDTI2MTEwMTEyMTMzMVowMjELMAkGA1UE
BhMCVVMxDTALBgNVBAoMBFRlc3QxFDASBgNVBAMMC2V4YW1wbGUuY29tMIIBIjAN
BgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAzl6FR6aI7YlzUNsTh2SVGuFAxNj+
sekNi99AhhTDXrAeKseMCL7v3UhCcEnFWuNC7QqTUEESkd/NriqZBCylXGYdxwR4
5yRhdOv5xCXk1UavopGklen8PluK5jtOuYUiBfoj+OhZGnyKPWYyXYQ7B6sfGcub
Uvl+OH/w9dVgU74GGx9GQn+UKOz3ZomGF6gzF1TQUpfhVKB1wFxgT0K8ixMPVBvF
aTnH2aB4XzVqWx43qovS8Y3H/GCrX/QAGYg2W6eXACC9nMB//fqGtIGyAjKRFSJB
wDAlAQyGFp2hlqK2LInlKQJXC75j8NfPwAGEu5QaKPbsdy2wAbodzKjI8wIDAQAB
o1MwUTAdBgNVHQ4EFgQUda+fEmKR5uVxFUC89ui9bEGWtgAwHwYDVR0jBBgwFoAU
da+fEmKR5uVxFUC89ui9bEGWtgAwDwYDVR0TAQH/BAUwAwEB/zANBgkqhkiG9w0B
AQsFAAOCAQEAuKq6vyH+oP+E8CtigFqFtdZJ3lbisL5q5IR1RlCZCuWenEBpvrbs
JFuUjSXk5h0EzKUPj/iWsceoZnBdVyPtmN0icm437Irnf378si2hHFuYKq4bOwVY
1+LSs0z4d8yCXwxWmnwmBtuU/dlFlWAQ/0ZlSVQNnploSs0goJT6vK0HWVk4jrZo
H3QWmtf/4A/FFj6nR8ym8boc58P1r7U48DwYc0pYzd4tSgwcZUsG5wr7cwoV+Nqb
Zqp0+WDOEzs8gvnopOU66wZ61AW+f/vS9M2Lf0r7yteD1TwMxRh3ty9t5fV2vK6l
dmEeOVLy9ri0iZVBAJJnqFEhVxAfmq0zgw==
-----END CERTIFICATE-----"""

EXPECTED_PRIVATE_KEY = """-----BEGIN PRIVATE KEY-----
MIIEvgIBADANBgkqhkiG9w0BAQEFAASCBKgwggSkAgEAAoIBAQDOXoVHpojtiXNQ
2xOHZJUa4UDE2P6x6Q2L30CGFMNesB4qx4wIvu/dSEJwScVa40LtCpNQQRKR382u
KpkELKVcZh3HBHjnJGF06/nEJeTVRq+ikaSV6fw+W4rmO065hSIF+iP46FkafIo9
ZjJdhDsHqx8Zy5tS+X44f/D11WBTvgYbH0ZCf5Qo7PdmiYYXqDMXVNBSl+FUoHXA
XGBPQryLEw9UG8VpOcfZoHhfNWpbHjeqi9Lxjcf8YKtf9AAZiDZbp5cAIL2cwH/9
+oa0gbICMpEVIkHAMCUBDIYWnaGWorYsieUpAlcLvmPw18/AAYS7lBoo9ux3LbAB
uh3MqMjzAgMBAAECggEAJdERWF9uoSS6cnsq2Xk3j5zuewQOrDh6SILpNojQgmYA
qTM2+JVQrDqlHiGOnkieB4UUGLVL+1pJPRzGPIsX5FY8J6+sniK/Dyd89hJBnEmf
Psm0oNonZJ/u1KDSnNGGOhUsCV0+ksl2pai4GwXzsUSM5vO2K17X3++mDs6Cn+WS
rvtV8y06cyxr9Evqo9IwA4dp0q+wyYi9gIjEDU0QTHfQkTkPoCLfpI/coxHebJNA
XnCokMfOtbmeNYO9NrTsVvA4T/a0VC2n5+C97pUcN8WAHk8MtHk01BVa5N0+8hby
O16aUvBEfMtbGZ8uYeHLLoGII3nclfMCJpcMYfnqRQKBgQDxTNha25OWCZX70pWc
cDzfVdFHLcuTxQnjSDu7BNAPpOmCyuv4sIaSKrNzIDQubunFvebA/DJuDS7x4HIK
REr71gxh+JAjGUOpRozwFZXPUtiWcLoKK+EkuJpaDVusvXSp3Fi6PO8sW/wRmbzm
HabOl+M1T/VohrjDX2SFbQDflwKBgQDa8Op1+uWbDmgWIjNEPm3ABzsYStOKXH32
JloUvhOczfHDVvZgWuWguatUX8+LqHfT2R5L9jkNpxhRGQ/Wd4ouFjHNdan8OFjz
YDKvM9Dkd6hXOUGflPMyAhOR71ACDrJ4QMimIWKoSt8iEdIVuddhIjcx+G/hSb/W
wubTJzxNBQKBgQDJOflPQ7+/Jn1SRNoJXLwWz104C6OytmW5iVpuauQLt84YCZth
h+yhZkTCJD//3PTMt8IAfBCeIBZfFXpkv3D8tRMcfInPC1mWh8QuzwFgpMkEJDux
Ecius9fcczlZQ6FPqfbAUOJvzsHV96xFBsM9lAKhSe3w3jCklR+h+TX6PwKBgHsA
jIiZ23MAZgPBVRILDLesmEuuhigejHnE1CkBHJ2kqiW3bpV1m7pvdUziwwRQMnnn
afj9LNJ5xNSTAu3XnN8FgxdN+qEDux2INxFtR/eDLiVKuo6ALR00Q3BihY2SWjvr
EY8cBIROBAvs/R1Nmi4s/dtqGtj0CP4L44hPa7ZNAoGBAMBnYPO5pmNSZJDeePlj
oYNLqaQJufDFRefDvEiKaIdhrBEoh/4WQH+o/ezMfKw4uNNblg6PT243ZjA8/KD2
9Nq5yjyOSVp5FuBIFbqHyiOQGm+QYe+v9eFjBV4hfkNt/jWOUZVo+vi6A8vhnbih
bsZ6XmvjSHYhT9iKdJXQmm4v
-----END PRIVATE KEY-----"""


class StubHass:
    """Minimal hass stub implementing storage API requirements."""

    def __init__(self, loop: asyncio.AbstractEventLoop, config_dir: str) -> None:
        """Store loop and config directory to mirror hass helpers."""

        self.loop = loop

        # Provide a `config` object with a `.path` helper used by storage.Store
        def _path(*parts: str) -> str:
            # Join parts under the provided config_dir
            return str(Path(config_dir).joinpath(*parts))

        self.config = SimpleNamespace(config_dir=config_dir, path=_path)
        # Provide a simplified `state` object used by Store to determine shutdown
        self.state = SimpleNamespace(name="running")
        # Provide `data` mapping expected by Home Assistant helpers (storage, etc.)
        self.data: dict[str, object] = {}
        # Emulate Home Assistant's loop thread id used by frame.report_usage
        import threading

        self.loop_thread_id = threading.get_ident()

    async def async_add_executor_job(self, func, *args):  # type: ignore[no-untyped-def]
        """Run executor jobs via the ambient event loop."""

        return await asyncio.get_running_loop().run_in_executor(None, func, *args)


@pytest.mark.asyncio
async def test_auth_manager_login_fetches_iot_bundle(
    tmp_path_factory, request, monkeypatch: pytest.MonkeyPatch
):
    """Login should persist account metadata and IoT credentials."""

    tmp_path = tmp_path_factory.mktemp("hass")
    loop = asyncio.get_running_loop()
    hass = StubHass(loop, str(tmp_path))

    generated_client_id = "generated-client-id"
    monkeypatch.setattr(
        "custom_components.govee.auth._generate_client_id",
        lambda: generated_client_id,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url == httpx.URL(
            "https://app2.govee.com/account/rest/account/v1/login"
        ):
            payload = json.loads(request.content.decode())
            assert payload == {
                "email": "user@example.com",
                "password": "secret",
                "client": generated_client_id,
            }
            headers = request.headers
            assert headers["clientType"] == "1"
            assert headers["clientId"] == generated_client_id
            assert headers["User-Agent"].startswith("GoveeHome/5.6.01")
            assert all(value == "5.6.01" for value in headers.get_list("AppVersion"))
            assert all(value == "5.6.01" for value in headers.get_list("appVersion"))
            assert headers["Accept"] == "application/json"
            assert headers["Content-Type"] == "application/json"
            assert headers["iotVersion"] == "0"
            return httpx.Response(
                200,
                json={
                    "status": 200,
                    "client": {
                        "accountId": "123",
                        "client": generated_client_id,
                        "topic": "topic/123",
                        "token": "access-token",
                        "refreshToken": "refresh-token",
                        "tokenExpireCycle": 120,
                    },
                },
            )
        if request.url == httpx.URL("https://app2.govee.com/app/v1/account/iot/key"):
            headers = request.headers
            assert headers["Authorization"] == "Bearer access-token"
            assert headers["clientType"] == "1"
            assert headers["clientId"] == generated_client_id
            assert headers["User-Agent"].startswith("GoveeHome/5.6.01")
            return httpx.Response(
                200,
                json={
                    "status": 200,
                    "data": {
                        "endpoint": "ssl://broker.example",
                        "p12": P12_BUNDLE,
                        "p12Pass": "password",
                    },
                },
            )
        raise AssertionError(f"Unexpected request to {request.url!r}")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    manager = GoveeAuthManager(hass, client)
    await manager.async_initialize()

    details = await manager.async_login("user@example.com", "secret")

    assert isinstance(details, AccountAuthDetails)
    assert details.account_id == "123"
    assert details.client_id == generated_client_id
    assert details.topic == "topic/123"
    assert details.access_token == "access-token"
    assert details.refresh_token == "refresh-token"
    assert details.iot_certificate == EXPECTED_CERTIFICATE
    assert details.iot_private_key == EXPECTED_PRIVATE_KEY
    assert details.iot_endpoint == "ssl://broker.example"
    assert details.expires_at > datetime.now(timezone.utc)

    bundle = await manager.async_get_iot_bundle()
    assert bundle == IoTBundle(
        account_id="123",
        client_id=generated_client_id,
        topic="topic/123",
        endpoint="ssl://broker.example",
        certificate=EXPECTED_CERTIFICATE,
        private_key=EXPECTED_PRIVATE_KEY,
    )

    storage_file = tmp_path / ".storage" / "govee_auth"
    stored = json.loads(storage_file.read_text())
    if isinstance(stored, dict) and "data" in stored:
        stored = stored["data"]
    assert stored == {
        "email": "user@example.com",
        "account_id": "123",
        "client_id": generated_client_id,
        "topic": "topic/123",
        "access_token": "access-token",
        "refresh_token": "refresh-token",
        "expires_at": details.expires_at.isoformat(),
        "iot_endpoint": "ssl://broker.example",
        "iot_certificate": EXPECTED_CERTIFICATE,
        "iot_private_key": EXPECTED_PRIVATE_KEY,
    }

    reload_client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200))
    )
    reload_manager = GoveeAuthManager(hass, reload_client)
    await reload_manager.async_initialize()

    assert reload_manager.tokens == details
    assert await reload_manager.async_get_iot_bundle() == bundle

    await client.aclose()
    await reload_client.aclose()


@pytest.mark.asyncio
async def test_auth_manager_refreshes_tokens_updates_iot_bundle(
    tmp_path_factory, request
):
    """Stored tokens nearing expiry should refresh and update IoT data."""

    tmp_path = tmp_path_factory.mktemp("hass_refresh")
    loop = asyncio.get_running_loop()
    hass = StubHass(loop, str(tmp_path))

    expires_at = datetime.now(timezone.utc) + timedelta(seconds=10)
    storage_payload = {
        "email": "user@example.com",
        "account_id": "123",
        "client_id": "existing-client",
        "topic": "topic/123",
        "access_token": "old-access",
        "refresh_token": "old-refresh",
        "expires_at": expires_at.isoformat(),
        "iot_endpoint": "ssl://old",
        "iot_certificate": "old-cert",
        "iot_private_key": "old-key",
    }

    storage_file = tmp_path / ".storage" / "govee_auth"
    storage_file.parent.mkdir(parents=True, exist_ok=True)
    # Persist using the Home Assistant Store envelope so the Store can read it
    envelope = {
        "version": 1,
        "minor_version": 1,
        "key": "govee_auth",
        "data": storage_payload,
    }
    storage_file.write_text(json.dumps(envelope))

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url == httpx.URL(
            "https://app2.govee.com/account/rest/v1/first/refresh-tokens"
        ):
            payload = json.loads(request.content.decode())
            assert payload == {"refreshToken": "old-refresh"}
            headers = request.headers
            assert headers["Authorization"] == "Bearer old-access"
            assert headers["clientType"] == "1"
            assert headers["clientId"] == "existing-client"
            return httpx.Response(
                200,
                json={
                    "status": 200,
                    "data": {
                        "token": "new-access",
                        "refreshToken": "new-refresh",
                        "tokenExpireCycle": 3600,
                    },
                },
            )
        if request.url == httpx.URL("https://app2.govee.com/app/v1/account/iot/key"):
            assert request.headers["Authorization"] == "Bearer new-access"
            return httpx.Response(
                200,
                json={
                    "status": 200,
                    "data": {
                        "endpoint": "ssl://broker.example",
                        "p12": P12_BUNDLE,
                        "p12Pass": "password",
                    },
                },
            )
        raise AssertionError(f"Unexpected request to {request.url!r}")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    manager = GoveeAuthManager(hass, client)
    await manager.async_initialize()

    token = await manager.async_get_access_token()

    assert token == "new-access"
    assert manager.tokens is not None
    assert manager.tokens.access_token == "new-access"
    assert manager.tokens.refresh_token == "new-refresh"
    assert manager.tokens.iot_certificate == EXPECTED_CERTIFICATE
    assert manager.tokens.iot_private_key == EXPECTED_PRIVATE_KEY

    bundle = await manager.async_get_iot_bundle()
    assert bundle == IoTBundle(
        account_id="123",
        client_id="existing-client",
        topic="topic/123",
        endpoint="ssl://broker.example",
        certificate=EXPECTED_CERTIFICATE,
        private_key=EXPECTED_PRIVATE_KEY,
    )

    updated = json.loads(storage_file.read_text())
    if isinstance(updated, dict) and "data" in updated:
        updated = updated["data"]
    assert updated["access_token"] == "new-access"
    assert updated["refresh_token"] == "new-refresh"
    assert updated["iot_certificate"] == EXPECTED_CERTIFICATE
    assert updated["iot_private_key"] == EXPECTED_PRIVATE_KEY

    await client.aclose()


@pytest.mark.asyncio
async def test_auth_manager_login_failure(tmp_path_factory, request):
    """A login failure should bubble up and not persist credentials."""

    tmp_path = tmp_path_factory.mktemp("hass_login_fail")
    loop = asyncio.get_running_loop()
    hass = StubHass(loop, str(tmp_path))

    existing = AccountAuthDetails(
        email="user@example.com",
        account_id="123",
        client_id="existing-client",
        topic="topic/123",
        access_token="cached-access",
        refresh_token="cached-refresh",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        iot_endpoint="ssl://broker.example",
        iot_certificate=EXPECTED_CERTIFICATE,
        iot_private_key=EXPECTED_PRIVATE_KEY,
    )
    storage_file = tmp_path / ".storage" / "govee_auth"
    storage_file.parent.mkdir(parents=True, exist_ok=True)
    envelope = {
        "version": 1,
        "minor_version": 1,
        "key": "govee_auth",
        "data": existing.as_storage(),
    }
    storage_file.write_text(json.dumps(envelope))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "invalid"})

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://app2.govee.com"
    )
    manager = GoveeAuthManager(hass, client)
    await manager.async_initialize()

    assert manager.tokens is not None  # loaded cached tokens

    with pytest.raises(httpx.HTTPStatusError):
        await manager.async_login("user@example.com", "bad")

    assert manager.tokens is None
    assert not storage_file.exists()


@pytest.mark.asyncio
async def test_auth_manager_refresh_failure_clears_state(tmp_path_factory, request):
    """A refresh error should clear stored credentials."""

    tmp_path = tmp_path_factory.mktemp("hass_refresh_fail")
    loop = asyncio.get_running_loop()
    hass = StubHass(loop, str(tmp_path))

    expiring = AccountAuthDetails(
        email="user@example.com",
        account_id="123",
        client_id="existing-client",
        topic="topic/123",
        access_token="old-access",
        refresh_token="old-refresh",
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=10),
        iot_endpoint="ssl://broker.example",
        iot_certificate=EXPECTED_CERTIFICATE,
        iot_private_key=EXPECTED_PRIVATE_KEY,
    )

    storage_file = tmp_path / ".storage" / "govee_auth"
    storage_file.parent.mkdir(parents=True, exist_ok=True)
    envelope = {
        "version": 1,
        "minor_version": 1,
        "key": "govee_auth",
        "data": expiring.as_storage(),
    }
    storage_file.write_text(json.dumps(envelope))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "expired"})

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://app2.govee.com"
    )
    manager = GoveeAuthManager(hass, client)
    await manager.async_initialize()

    with pytest.raises(httpx.HTTPStatusError):
        await manager.async_get_access_token()

    assert manager.tokens is None
    assert not storage_file.exists()

    await client.aclose()


@pytest.mark.asyncio
async def test_auth_manager_migrates_legacy_storage(tmp_path_factory, request):
    """Legacy storage files should be migrated to the new key on initialize."""

    tmp_path = tmp_path_factory.mktemp("hass_auth_migrate")
    loop = asyncio.get_running_loop()
    hass = StubHass(loop, str(tmp_path))

    legacy_file = tmp_path / ".storage" / "govee_ultimate_auth"
    legacy_file.parent.mkdir(parents=True, exist_ok=True)
    legacy_payload = AccountAuthDetails(
        email="user@example.com",
        account_id="123",
        client_id="existing-client",
        topic="topic/123",
        access_token="legacy-access",
        refresh_token="legacy-refresh",
        expires_at=datetime.now(timezone.utc),
        iot_endpoint="ssl://broker.example",
        iot_certificate=EXPECTED_CERTIFICATE,
        iot_private_key=EXPECTED_PRIVATE_KEY,
    ).as_storage()
    legacy_file.write_text(json.dumps(legacy_payload))

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200)),
        base_url="https://app2.govee.com",
    )

    manager = GoveeAuthManager(hass, client)
    await manager.async_initialize()

    new_file = tmp_path / ".storage" / "govee_auth"
    assert new_file.exists()
    assert not legacy_file.exists()
    assert manager.tokens == AccountAuthDetails.from_storage(legacy_payload)

    await client.aclose()


@pytest.mark.parametrize(
    "factory",
    (
        AccountAuthDetails.from_login_payload,
        AccountAuthDetails.from_storage,
    ),
)
def test_account_auth_details_return_annotations_are_concrete(factory) -> None:
    """Factories should declare concrete return annotations."""

    source = inspect.getsource(factory)

    assert '"AccountAuthDetails"' not in source
