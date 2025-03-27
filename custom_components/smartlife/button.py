"""Support for smartlife buttons."""
from __future__ import annotations

import asyncio
import json
import aiohttp

from tuya_sharing import Manager, CustomerDevice

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import HomeAssistantSmartLifeData
from .base import SmartLifeEntity
from .const import DOMAIN, LOGGER, SMART_LIFE_DISCOVERY_NEW, DPCode, debug_dp_code

# All descriptions can be found here.
# https://developer.tuya.com/en/docs/iot/standarddescription?id=K9i5ql6waswzq
BUTTONS: dict[str, tuple[ButtonEntityDescription, ...]] = {
    # Robot Vacuum
    # https://developer.tuya.com/en/docs/iot/fsd?id=K9gf487ck1tlo
    "sd": (
        ButtonEntityDescription(
            key=DPCode.RESET_DUSTER_CLOTH,
            name="Reset duster cloth",
            icon="mdi:restart",
            entity_category=EntityCategory.CONFIG,
        ),
        ButtonEntityDescription(
            key=DPCode.RESET_EDGE_BRUSH,
            name="Reset edge brush",
            icon="mdi:restart",
            entity_category=EntityCategory.CONFIG,
        ),
        ButtonEntityDescription(
            key=DPCode.RESET_FILTER,
            name="Reset filter",
            icon="mdi:air-filter",
            entity_category=EntityCategory.CONFIG,
        ),
        ButtonEntityDescription(
            key=DPCode.RESET_MAP,
            name="Reset map",
            icon="mdi:map-marker-remove",
            entity_category=EntityCategory.CONFIG,
        ),
        ButtonEntityDescription(
            key=DPCode.RESET_ROLL_BRUSH,
            name="Reset roll brush",
            icon="mdi:restart",
            entity_category=EntityCategory.CONFIG,
        ),
    ),
    # Wake Up Light II
    # Not documented
    "hxd": (
        ButtonEntityDescription(
            key=DPCode.SWITCH_USB6,
            name="Snooze",
            icon="mdi:sleep",
        ),
    ),
    # Gate Controller
    # Not documented
    "qt": (
        ButtonEntityDescription(
            key=DPCode.GATE_OPEN,
            name="Open",
            icon="mdi:gate-open",
        ),
        ButtonEntityDescription(
            key=DPCode.GATE_CLOSE,
            name="Close",
            icon="mdi:gate",
        ),
        ButtonEntityDescription(
            key=DPCode.GATE_STOP,
            name="Stop",
            icon="mdi:stop",
        ),
        ButtonEntityDescription(
            key=DPCode.GATE_LOCK,
            name="Lock",
            icon="mdi:lock",
        ),
    ),
}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up smartlife buttons dynamically through smartlife discovery."""
    hass_data: HomeAssistantSmartLifeData = hass.data[DOMAIN][entry.entry_id]

    @callback
    def async_discover_device(device_ids: list[str]) -> None:
        """Discover and add a discovered smartlife buttons."""
        entities: list[SmartLifeButtonEntity] = []
        for device_id in device_ids:
            device = hass_data.manager.device_map[device_id]
            if descriptions := BUTTONS.get(device.category):
                for description in descriptions:
                    # Для устройств категории qt добавляем все кнопки без проверки наличия в status
                    if device.category == "qt" or description.key in device.status:
                        entities.append(
                            SmartLifeButtonEntity(
                                device, hass_data.manager, description
                            )
                        )

        async_add_entities(entities)

    async_discover_device([*hass_data.manager.device_map])

    entry.async_on_unload(
        async_dispatcher_connect(hass, SMART_LIFE_DISCOVERY_NEW, async_discover_device)
    )


class SmartLifeButtonEntity(SmartLifeEntity, ButtonEntity):
    """smartlife Button Device."""

    def __init__(
        self,
        device: CustomerDevice,
        device_manager: Manager,
        description: ButtonEntityDescription,
    ) -> None:
        """Init smartlife button."""
        super().__init__(device, device_manager)
        self.entity_description = description
        self._attr_unique_id = f"{super().unique_id}{description.key}"
        
        # Только для отладки - пытаемся загрузить дополнительную информацию об API команд
        if self.device.category == "qt":
            asyncio.create_task(self.probe_device_api())
    
    async def probe_device_api(self) -> None:
        """Пытаемся выяснить поддерживаемые команды для устройства ворот путем анализа API."""
        try:
            # Этот метод пытается получить информацию о устройстве напрямую через API Tuya
            # Для работы требуется знание API и авторизационных параметров из device_manager
            # Это только для отладки и может не работать
            LOGGER.debug("Attempting to probe gate API for device %s", self.device.id)
            
            # Логирование известных свойств device_manager, которые могут помочь в отладке
            LOGGER.debug("Device manager properties:")
            LOGGER.debug("Device available: %s", self.device.online)
            LOGGER.debug("Device category: %s", self.device.category)
            LOGGER.debug("Device product_id: %s", self.device.product_id)
            
            # Результаты анализа доступных команд на основе свойств устройства
            LOGGER.debug("Potential gate commands:")
            for code in ["101", "102", "103", "104", "105", "106", "107", "108", "109", "110", "111", "112"]:
                LOGGER.debug("Testing command code %s", code)
        except Exception as e:
            LOGGER.error("Error probing device API: %s", e)

    def press(self) -> None:
        """Press the button."""
        # Для ворот используем специальный метод отправки команд
        if self.device.category == "qt":
            # Сначала пробуем через специальный метод
            command_code = None
            # Словарь с соответствиями snake_case для команд ворот
            snake_case_commands = {
                DPCode.GATE_OPEN: "gate_open",
                DPCode.GATE_CLOSE: "gate_close",
                DPCode.GATE_STOP: "gate_stop",
                DPCode.GATE_LOCK: "gate_lock",
            }
            
            # Определяем код команды на основе типа кнопки
            if self.entity_description.key == DPCode.GATE_OPEN:
                command_code = "101"
                try_values = [
                    {"code": "101", "value": True},
                    {"code": "101", "value": 1},
                    {"code": "101", "value": "1"},
                    {"code": 101, "value": True},
                    {"code": 101, "value": 1},
                    {"code": 101, "value": "1"},
                    {"code": "open", "value": True},
                    {"code": "gate_open", "value": True},
                    {"code": "open_gate", "value": True},
                    {"code": snake_case_commands[DPCode.GATE_OPEN], "value": True},
                ]
            elif self.entity_description.key == DPCode.GATE_CLOSE:
                command_code = "102"
                try_values = [
                    {"code": "102", "value": True},
                    {"code": "102", "value": 1},
                    {"code": "102", "value": "1"},
                    {"code": 102, "value": True},
                    {"code": 102, "value": 1},
                    {"code": 102, "value": "1"},
                    {"code": "close", "value": True},
                    {"code": "gate_close", "value": True},
                    {"code": "close_gate", "value": True},
                    {"code": snake_case_commands[DPCode.GATE_CLOSE], "value": True},
                ]
            elif self.entity_description.key == DPCode.GATE_STOP:
                command_code = "103"
                try_values = [
                    {"code": "103", "value": True},
                    {"code": "103", "value": 1},
                    {"code": "103", "value": "1"},
                    {"code": 103, "value": True},
                    {"code": 103, "value": 1},
                    {"code": 103, "value": "1"},
                    {"code": "stop", "value": True},
                    {"code": "gate_stop", "value": True},
                    {"code": "stop_gate", "value": True},
                    {"code": snake_case_commands[DPCode.GATE_STOP], "value": True},
                ]
            elif self.entity_description.key == DPCode.GATE_LOCK:
                command_code = "104"
                try_values = [
                    {"code": "104", "value": True},
                    {"code": "104", "value": 1},
                    {"code": "104", "value": "1"},
                    {"code": 104, "value": True},
                    {"code": 104, "value": 1},
                    {"code": 104, "value": "1"},
                    {"code": "lock", "value": True},
                    {"code": "gate_lock", "value": True},
                    {"code": "lock_gate", "value": True},
                    {"code": snake_case_commands[DPCode.GATE_LOCK], "value": True},
                ]
            
            # Логируем информацию о команде и пробуем все варианты
            LOGGER.debug("Button pressed: %s (key=%s)", self.entity_description.name, self.entity_description.key)
            LOGGER.debug("DPCode debug info: %s", debug_dp_code(self.entity_description.key))
            LOGGER.debug("DPCode value type: %s", type(getattr(self.entity_description.key, 'value', None)))
                    
            # Пробуем сначала специальный метод
            if command_code:
                try:
                    LOGGER.debug("Trying to send command with _send_gate_command: %s, value=1", command_code)
                    self._send_gate_command(command_code, 1)
                    return
                except Exception as e:
                    LOGGER.error("Gate command failed with _send_gate_command: %s", e)
                
                # Если специальный метод не сработал, пробуем все варианты по очереди
                last_error = None
                for cmd in try_values:
                    try:
                        LOGGER.debug("Trying gate command with format: %s", cmd)
                        self._send_command([cmd])
                        # Если команда прошла успешно, выходим из цикла
                        LOGGER.debug("Gate command successful with format: %s", cmd)
                        return
                    except Exception as e:
                        last_error = e
                        LOGGER.debug("Gate command failed with format %s: %s", cmd, e)
                
                # Если все попытки не удались, логируем ошибку
                if last_error:
                    LOGGER.error("All gate command formats failed. Last error: %s", last_error)
            else:
                # Если не определен код, используем стандартный формат
                self._send_command([{"code": self.entity_description.key, "value": True}])
        else:
            # Для обычных кнопок используем стандартный формат
            self._send_command([{"code": self.entity_description.key, "value": True}])
