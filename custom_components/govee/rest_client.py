"""REST API helpers for the Govee Ultimate integration."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .auth import GoveeAuthManager

_LOGGER = logging.getLogger(__name__)

_REST_CONTROL_URL = "https://app2.govee.com/device/rest/devices/v1/control"
_EFFECTS_URL = "https://app2.govee.com/appsku/v1/light-effect-libraries"
_SCENES_URL = "https://app2.govee.com/appsku/v2/devices/scenes/attributes"
_DIY_URL = "https://app2.govee.com/appsku/v1/diys/groups-diys"
_ONE_CLICKS_URL = "https://app2.govee.com/bff-app/v1/exec-plat/one-click-rules"

_CACHE_VERSION = 1
_EFFECT_CACHE_PREFIX = "govee_effects"
_DIY_CACHE_PREFIX = "govee_diys"
_CACHE_TTL = timedelta(hours=1)

_APP_VERSION = "5.6.01"
_USER_AGENT = (
    f"GoveeHome/{_APP_VERSION}"
    " (com.ihoment.GoVeeSensor; build:2; iOS 16.5.0) Alamofire/5.6.4"
)


class GoveeRestClient:
    """REST helper providing command publishing and effect/DIY retrieval."""

    def __init__(
        self,
        hass: HomeAssistant,
        auth: GoveeAuthManager,
        http_client_getter: Callable[[], httpx.AsyncClient | None],
    ) -> None:
        """Initialise the rest client with Home Assistant and auth helpers."""

        self._hass = hass
        self._auth = auth
        self._http_client_getter = http_client_getter
        self._effects_cache: dict[str, tuple[datetime, list[dict[str, Any]]]] = {}
        self._diy_cache: dict[str, tuple[datetime, list[dict[str, Any]]]] = {}
        self._lock = asyncio.Lock()

    async def async_publish_command(
        self,
        *,
        device_id: str,
        channel_info: Mapping[str, Any],
        message: Mapping[str, Any],
    ) -> None:
        """Publish a command to the REST control endpoint."""

        client = self._require_http_client()
        headers = await self._account_headers()
        body = self._build_command_payload(device_id, channel_info, message)
        try:
            response = await client.post(_REST_CONTROL_URL, json=body, headers=headers)
            response.raise_for_status()
            payload = response.json()
            status = payload.get("status") if isinstance(payload, Mapping) else 200
            if status not in (None, 200):
                raise httpx.HTTPStatusError(
                    f"REST command returned status {status}",
                    request=response.request,
                    response=response,
                )
        except Exception as err:  # pragma: no cover - network failure logging
            _LOGGER.error("REST command failed for %s: %s", device_id, err)
            raise

    async def async_get_light_effects(
        self, *, model: str, goods_type: int, device_id: str
    ) -> list[dict[str, Any]]:
        """Retrieve light effects for the provided device."""

        cache_key = f"{model}_{goods_type}"
        cached = await self._load_effects_from_cache(cache_key)
        if cached is not None:
            return cached

        client = self._require_http_client()
        headers = await self._account_headers()
        params = {"sku": model, "goodsType": goods_type, "device": device_id}
        try:
            effects_resp = await client.get(
                _EFFECTS_URL, params=params, headers=headers
            )
            effects_resp.raise_for_status()
            scenes_resp = await client.get(_SCENES_URL, params=params, headers=headers)
            scenes_resp.raise_for_status()
        except Exception as err:  # pragma: no cover - network failure logging
            _LOGGER.warning("Unable to fetch light effects for %s: %s", model, err)
            return cached or []

        effects = self._extract_effects(
            effects_resp.json() if effects_resp.content else {}
        )
        scenes = self._extract_scenes(scenes_resp.json() if scenes_resp.content else {})
        combined = self._merge_effects_and_scenes(model, effects, scenes)
        await self._store_effects(cache_key, combined)
        return combined

    async def async_get_diy_effects(
        self, *, model: str, goods_type: int, device_id: str
    ) -> list[dict[str, Any]]:
        """Retrieve DIY effect definitions for the provided device."""

        cache_key = f"{model}_{goods_type}"
        cached = await self._load_diy_from_cache(cache_key)
        if cached is not None:
            return cached

        headers = await self._bff_headers()
        if headers is None:
            _LOGGER.debug("DIY effects unavailable; missing BFF credentials")
            return cached or []

        client = self._require_http_client()
        payload = {
            "sku": model,
            "goodsType": goods_type,
            "device": device_id,
        }
        try:
            response = await client.get(_DIY_URL, params=payload, headers=headers)
            response.raise_for_status()
        except Exception as err:  # pragma: no cover - network failure logging
            _LOGGER.warning("Unable to fetch DIY effects for %s: %s", model, err)
            return cached or []

        diy_effects = self._extract_diy_effects(
            response.json() if response.content else {}
        )
        await self._store_diy(cache_key, diy_effects)
        return diy_effects

    async def async_get_one_clicks(self) -> list[dict[str, Any]]:
        """Retrieve One-Click automations (currently unused, cached for parity)."""

        headers = await self._bff_headers()
        if headers is None:
            return []
        client = self._require_http_client()
        try:
            response = await client.get(_ONE_CLICKS_URL, headers=headers)
            response.raise_for_status()
        except Exception as err:  # pragma: no cover - network failure logging
            _LOGGER.debug("Unable to fetch one-click automations: %s", err)
            return []
        payload = response.json() if response.content else {}
        data = payload.get("data")
        if isinstance(data, list):
            return data
        return []

    def _require_http_client(self) -> httpx.AsyncClient:
        client = self._http_client_getter()
        if client is None:
            raise RuntimeError("HTTP client is not initialised")
        return client

    async def _account_headers(self, client_type: str = "1") -> dict[str, str]:
        access_token = await self._auth.async_get_access_token()
        tokens = self._auth.tokens
        if tokens is None:
            raise RuntimeError("No authentication tokens available")
        headers = {
            "clientType": client_type,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "iotVersion": "0",
            "clientId": tokens.client_id,
            "User-Agent": _USER_AGENT,
            "appVersion": _APP_VERSION,
            "AppVersion": _APP_VERSION,
            "Authorization": f"Bearer {access_token}",
        }
        return headers

    async def _bff_headers(self) -> dict[str, str] | None:
        bundle = await self._auth.async_get_bff_bundle()
        if bundle is None:
            return None
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "clientId": bundle.client_id,
            "User-Agent": _USER_AGENT,
            "appVersion": _APP_VERSION,
            "AppVersion": _APP_VERSION,
            "Authorization": f"Bearer {bundle.access_token}",
        }
        return headers

    def _build_command_payload(
        self,
        device_id: str,
        channel_info: Mapping[str, Any],
        message: Mapping[str, Any],
    ) -> dict[str, Any]:
        payload = {
            "device": device_id,
            "msg": dict(message),
        }
        topic = channel_info.get("topic") or channel_info.get("command_topic")
        if isinstance(topic, str) and topic:
            payload["msg"].setdefault("topic", topic)
        account_topic = channel_info.get("account_topic")
        if isinstance(account_topic, str) and account_topic:
            payload["msg"].setdefault("accountTopic", account_topic)
        command_id = message.get("command_id")
        if isinstance(command_id, str):
            payload["commandId"] = command_id
        return payload

    async def _load_effects_from_cache(
        self, cache_key: str
    ) -> list[dict[str, Any]] | None:
        entry = self._effects_cache.get(cache_key)
        if entry and not self._is_expired(entry[0]):
            return entry[1]

        data = await self._load_from_store(_EFFECT_CACHE_PREFIX, cache_key)
        if not data:
            return None
        timestamp = self._parse_timestamp(data.get("updated_at"))
        effects = data.get("data")
        if timestamp is None or not isinstance(effects, list):
            return None
        if self._is_expired(timestamp):
            return None
        self._effects_cache[cache_key] = (timestamp, effects)
        return effects

    async def _store_effects(
        self, cache_key: str, effects: list[dict[str, Any]]
    ) -> None:
        timestamp = datetime.now(timezone.utc)
        self._effects_cache[cache_key] = (timestamp, effects)
        await self._save_to_store(
            _EFFECT_CACHE_PREFIX,
            cache_key,
            {"updated_at": timestamp.isoformat(), "data": effects},
        )

    async def _load_diy_from_cache(self, cache_key: str) -> list[dict[str, Any]] | None:
        entry = self._diy_cache.get(cache_key)
        if entry and not self._is_expired(entry[0]):
            return entry[1]
        data = await self._load_from_store(_DIY_CACHE_PREFIX, cache_key)
        if not data:
            return None
        timestamp = self._parse_timestamp(data.get("updated_at"))
        diy = data.get("data")
        if timestamp is None or not isinstance(diy, list):
            return None
        if self._is_expired(timestamp):
            return None
        self._diy_cache[cache_key] = (timestamp, diy)
        return diy

    async def _store_diy(self, cache_key: str, diy: list[dict[str, Any]]) -> None:
        timestamp = datetime.now(timezone.utc)
        self._diy_cache[cache_key] = (timestamp, diy)
        await self._save_to_store(
            _DIY_CACHE_PREFIX,
            cache_key,
            {"updated_at": timestamp.isoformat(), "data": diy},
        )

    async def _load_from_store(
        self, prefix: str, cache_key: str
    ) -> dict[str, Any] | None:
        store = Store(
            self._hass,
            _CACHE_VERSION,
            f"{prefix}_{cache_key}",
            private=True,
        )
        return await store.async_load()

    async def _save_to_store(
        self, prefix: str, cache_key: str, data: dict[str, Any]
    ) -> None:
        store = Store(
            self._hass,
            _CACHE_VERSION,
            f"{prefix}_{cache_key}",
            private=True,
        )
        await store.async_save(data)

    def _is_expired(self, timestamp: datetime) -> bool:
        return datetime.now(timezone.utc) - timestamp >= _CACHE_TTL

    def _parse_timestamp(self, value: Any) -> datetime | None:
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                return None
        return None

    def _extract_effects(self, payload: Mapping[str, Any]) -> list[dict[str, Any]]:
        effect_data = (
            payload.get("data", {}).get("effectData")
            if isinstance(payload.get("data"), Mapping)
            else payload.get("effectData")
        )
        categories = []
        if isinstance(effect_data, Mapping):
            categories = effect_data.get("categories", [])  # type: ignore[assignment]
        elif effect_data is not None:
            categories = effect_data

        results: list[dict[str, Any]] = []
        for category in categories or []:
            scenes = category.get("scenes") if isinstance(category, Mapping) else None
            if not isinstance(scenes, Sequence):
                continue
            for scene in scenes:
                if not isinstance(scene, Mapping):
                    continue
                scene_name = (
                    scene.get("sceneName")
                    or scene.get("scene_name")
                    or scene.get("name")
                    or ""
                )
                scene_code = scene.get("sceneCode") or scene.get("scene_code")
                scene_type = scene.get("sceneType") or scene.get("scene_type")
                light_effects = scene.get("lightEffects")
                if not isinstance(light_effects, Sequence):
                    continue
                for effect in light_effects:
                    if not isinstance(effect, Mapping):
                        continue
                    effect_name = (
                        effect.get("scenceName")
                        or effect.get("sceneName")
                        or effect.get("name")
                        or ""
                    )
                    name = (
                        " ".join(
                            part for part in (scene_name, effect_name) if part
                        ).strip()
                        or effect_name
                        or scene_name
                    )
                    code = effect.get("sceneCode") or effect.get("code") or scene_code
                    try:
                        code = int(code)
                    except (TypeError, ValueError):
                        continue
                    cmd_version = effect.get("cmdVersion") or effect.get(
                        "cmd_version", 0
                    )
                    op_code_base64 = (
                        effect.get("opCodeBase64")
                        or effect.get("scenceParam")
                        or effect.get("op_code_base64")
                        or ""
                    )
                    results.append(
                        {
                            "name": name,
                            "code": code,
                            "opCodeBase64": op_code_base64,
                            "cmdVersion": cmd_version,
                            "type": scene_type,
                        }
                    )
        return results

    def _extract_scenes(self, payload: Mapping[str, Any]) -> list[dict[str, Any]]:
        scene_data = (
            payload.get("data", {}).get("sceneData")
            if isinstance(payload.get("data"), Mapping)
            else payload.get("sceneData")
        )
        categories = []
        if isinstance(scene_data, Mapping):
            categories = scene_data.get("categories", [])  # type: ignore[assignment]
        elif scene_data is not None:
            categories = scene_data

        results: list[dict[str, Any]] = []
        for category in categories or []:
            scenes = category.get("scenes") if isinstance(category, Mapping) else None
            if not isinstance(scenes, Sequence):
                continue
            for scene in scenes:
                if not isinstance(scene, Mapping):
                    continue
                name = scene.get("sceneName") or scene.get("name")
                code = scene.get("sceneCode") or scene.get("code")
                scene_type = scene.get("sceneType") or scene.get("type")
                try:
                    code_int = int(code)
                except (TypeError, ValueError):
                    continue
                results.append(
                    {
                        "name": name,
                        "code": code_int,
                        "opCode": scene.get("opCode") or scene.get("op_code"),
                        "cmdVersion": 0,
                        "type": scene_type,
                    }
                )
        return results

    def _merge_effects_and_scenes(
        self,
        _model: str,
        effects: Sequence[Mapping[str, Any]],
        scenes: Sequence[Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        existing_codes = {
            self._coerce_int(effect.get("code"))
            for effect in effects
            if isinstance(effect, Mapping)
        }
        merged: list[dict[str, Any]] = [dict(effect) for effect in effects]  # type: ignore[arg-type]
        for scene in scenes:
            if not isinstance(scene, Mapping):
                continue
            code = self._coerce_int(scene.get("code"))
            if code in existing_codes:
                continue
            scene_dict = dict(scene.items())
            scene_dict["code"] = code
            merged.append(scene_dict)
        return merged

    def _coerce_int(self, value: Any) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _extract_diy_effects(self, payload: Mapping[str, Any]) -> list[dict[str, Any]]:
        data = (
            payload.get("data", {}).get("diys")
            if isinstance(payload.get("data"), Mapping)
            else payload.get("diys")
        )
        groups = []
        if isinstance(data, Mapping):
            groups = data.get("diyGroups", [])  # type: ignore[assignment]
        elif data is not None:
            groups = data

        results: list[dict[str, Any]] = []
        for group in groups or []:
            diys = group.get("diys") if isinstance(group, Mapping) else None
            if not isinstance(diys, Sequence):
                continue
            for diy in diys:
                if not isinstance(diy, Mapping):
                    continue
                code = diy.get("code") or diy.get("diyCode")
                name = diy.get("name") or diy.get("diyName")
                opcode = diy.get("diyOpCodeBase64") or diy.get("effectStr")
                try:
                    code_int = int(code)
                except (TypeError, ValueError):
                    continue
                results.append(
                    {
                        "code": code_int,
                        "name": name,
                        "diyOpCodeBase64": opcode,
                        "effectType": diy.get("effectType"),
                    }
                )
        return results
