"""SmartLife Home Assistant Base Device Model."""
from __future__ import annotations

import base64
from dataclasses import dataclass
import json
import struct
from typing import Any, Literal, overload

from tuya_sharing import Manager, CustomerDevice
from typing_extensions import Self

from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo, Entity

from .const import DOMAIN, LOGGER, SMART_LIFE_HA_SIGNAL_UPDATE_ENTITY, DPCode, DPType, debug_dp_code
from .util import remap_value


@dataclass
class IntegerTypeData:
    """Integer Type Data."""

    dpcode: DPCode
    min: int
    max: int
    scale: float
    step: float
    unit: str | None = None
    type: str | None = None

    @property
    def max_scaled(self) -> float:
        """Return the max scaled."""
        return self.scale_value(self.max)

    @property
    def min_scaled(self) -> float:
        """Return the min scaled."""
        return self.scale_value(self.min)

    @property
    def step_scaled(self) -> float:
        """Return the step scaled."""
        return self.step / (10 ** self.scale)

    def scale_value(self, value: float | int) -> float:
        """Scale a value."""
        return value / (10 ** self.scale)

    def scale_value_back(self, value: float | int) -> int:
        """Return raw value for scaled."""
        return int(value * (10 ** self.scale))

    def remap_value_to(
            self,
            value: float,
            to_min: float | int = 0,
            to_max: float | int = 255,
            reverse: bool = False,
    ) -> float:
        """Remap a value from this range to a new range."""
        return remap_value(value, self.min, self.max, to_min, to_max, reverse)

    def remap_value_from(
            self,
            value: float,
            from_min: float | int = 0,
            from_max: float | int = 255,
            reverse: bool = False,
    ) -> float:
        """Remap a value from its current range to this range."""
        return remap_value(value, from_min, from_max, self.min, self.max, reverse)

    @classmethod
    def from_json(cls, dpcode: DPCode, data: str) -> IntegerTypeData | None:
        """Load JSON string and return a IntegerTypeData object."""
        if not (parsed := json.loads(data)):
            return None

        return cls(
            dpcode,
            min=int(parsed["min"]),
            max=int(parsed["max"]),
            scale=float(parsed["scale"]),
            step=max(float(parsed["step"]), 1),
            unit=parsed.get("unit"),
            type=parsed.get("type"),
        )


@dataclass
class EnumTypeData:
    """Enum Type Data."""

    dpcode: DPCode
    range: list[str]

    @classmethod
    def from_json(cls, dpcode: DPCode, data: str) -> EnumTypeData | None:
        """Load JSON string and return a EnumTypeData object."""
        if not (parsed := json.loads(data)):
            return None
        return cls(dpcode, **parsed)


@dataclass
class ElectricityTypeData:
    """Electricity Type Data."""

    electriccurrent: str | None = None
    power: str | None = None
    voltage: str | None = None

    @classmethod
    def from_json(cls, data: str) -> Self:
        """Load JSON string and return a ElectricityTypeData object."""
        return cls(**json.loads(data.lower()))

    @classmethod
    def from_raw(cls, data: str) -> Self:
        """Decode base64 string and return a ElectricityTypeData object."""
        raw = base64.b64decode(data)
        voltage = struct.unpack(">H", raw[0:2])[0] / 10.0
        electriccurrent = struct.unpack(">L", b"\x00" + raw[2:5])[0] / 1000.0
        power = struct.unpack(">L", b"\x00" + raw[5:8])[0] / 1000.0
        return cls(
            electriccurrent=str(electriccurrent), power=str(power), voltage=str(voltage)
        )


class SmartLifeEntity(Entity):
    """SmartLife base device."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, device: CustomerDevice, device_manager: Manager) -> None:
        """Init SmartLifeHaEntity."""
        self._attr_unique_id = f"smartlife.{device.id}"
        device.set_up = True
        self.device = device
        self.device_manager = device_manager

    @property
    def device_info(self) -> DeviceInfo:
        """Return a device description for device registry."""
        return DeviceInfo(
            identifiers={(DOMAIN, self.device.id)},
            manufacturer="smartlife",
            name=self.device.name,
            model=f"{self.device.product_name} ({self.device.product_id})",
        )

    @property
    def available(self) -> bool:
        """Return if the device is available."""
        return self.device.online

    @overload
    def find_dpcode(
            self,
            dpcodes: str | DPCode | tuple[DPCode, ...] | None,
            *,
            prefer_function: bool = False,
            dptype: Literal[DPType.ENUM],
    ) -> EnumTypeData | None:
        ...

    @overload
    def find_dpcode(
            self,
            dpcodes: str | DPCode | tuple[DPCode, ...] | None,
            *,
            prefer_function: bool = False,
            dptype: Literal[DPType.INTEGER],
    ) -> IntegerTypeData | None:
        ...

    @overload
    def find_dpcode(
            self,
            dpcodes: str | DPCode | tuple[DPCode, ...] | None,
            *,
            prefer_function: bool = False,
    ) -> DPCode | None:
        ...

    def find_dpcode(
            self,
            dpcodes: str | DPCode | tuple[DPCode, ...] | None,
            *,
            prefer_function: bool = False,
            dptype: DPType | None = None,
    ) -> DPCode | EnumTypeData | IntegerTypeData | None:
        """Find a matching DP code available on for this device."""
        if dpcodes is None:
            return None

        if isinstance(dpcodes, str):
            dpcodes = (DPCode(dpcodes),)
        elif not isinstance(dpcodes, tuple):
            dpcodes = (dpcodes,)

        order = ["status_range", "function"]
        if prefer_function:
            order = ["function", "status_range"]

        # When we are not looking for a specific datatype, we can append status for
        # searching
        if not dptype:
            order.append("status")

        for dpcode in dpcodes:
            for key in order:
                if dpcode not in getattr(self.device, key):
                    continue
                if (
                        dptype == DPType.ENUM
                        and getattr(self.device, key)[dpcode].type == DPType.ENUM
                ):
                    if not (
                            enum_type := EnumTypeData.from_json(
                                dpcode, getattr(self.device, key)[dpcode].values
                            )
                    ):
                        continue
                    return enum_type

                LOGGER.debug("dpcode get device=%s dpcode=%s key=%s", self.device, dpcode, key)

                if (
                        dptype == DPType.INTEGER
                        and getattr(self.device, key)[dpcode].type == DPType.INTEGER
                ):
                    if not (
                            integer_type := IntegerTypeData.from_json(
                                dpcode, getattr(self.device, key)[dpcode].values
                            )
                    ):
                        continue
                    return integer_type

                if dptype not in (DPType.ENUM, DPType.INTEGER):
                    return dpcode

        return None

    def get_dptype(
            self, dpcode: DPCode | None, prefer_function: bool = False
    ) -> DPType | None:
        """Find a matching DPCode data type available on for this device."""
        if dpcode is None:
            return None

        order = ["status_range", "function"]
        if prefer_function:
            order = ["function", "status_range"]
        for key in order:
            if dpcode in getattr(self.device, key):
                return DPType(getattr(self.device, key)[dpcode].type)

        return None

    def dump_device_info(self) -> None:
        """Dump detailed device information to logs for debugging."""
        LOGGER.debug("=== Device Info for %s ===", self.device.id)
        LOGGER.debug("Category: %s", self.device.category)
        LOGGER.debug("Product ID: %s", self.device.product_id)
        LOGGER.debug("Product Name: %s", self.device.product_name)
        
        # Вывод информации о статусе
        LOGGER.debug("Status: %s", self.device.status)
        
        # Вывод информации о функциях
        LOGGER.debug("Functions:")
        for key, value in self.device.function.items():
            LOGGER.debug("  - %s: type=%s, values=%s", key, value.type, value.values)
        
        # Вывод информации о диапазонах статусов
        LOGGER.debug("Status Ranges:")
        for key, value in self.device.status_range.items():
            LOGGER.debug("  - %s: type=%s, values=%s", key, value.type, value.values)
        
        LOGGER.debug("=== End Device Info ===")

    async def async_added_to_hass(self) -> None:
        """Call when entity is added to hass."""
        # Логируем информацию о свойствах устройства при добавлении
        if self.device.category == "qt":
            self.dump_device_info()
        
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{SMART_LIFE_HA_SIGNAL_UPDATE_ENTITY}_{self.device.id}",
                self.async_write_ha_state,
            )
        )

    def _send_command(self, commands: list[dict[str, Any]]) -> None:
        """Send command to the device."""
        LOGGER.debug(
            "Sending commands for device %s (category: %s, product_id: %s): %s", 
            self.device.id, 
            self.device.category,
            self.device.product_id,
            commands
        )
        
        # Расширенное логирование типов и значений
        for cmd in commands:
            LOGGER.debug(
                "Command details - code: %s, type: %s, value: %s, value_type: %s",
                cmd.get("code"),
                type(cmd.get("code")),
                cmd.get("value"),
                type(cmd.get("value"))
            )
        
        # Для ворот пробуем различные форматы команд
        if self.device.category == "qt":
            # Преобразование команд для устройств ворот
            string_commands = []
            for command in commands:
                # Преобразуем DPCode в строку если нужно
                if isinstance(command["code"], DPCode):
                    command["code"] = command["code"].value
                
                # Логирование измененной команды
                LOGGER.debug(
                    "Modified command for gate - code: %s, type: %s, value: %s, value_type: %s",
                    command.get("code"),
                    type(command.get("code")),
                    command.get("value"),
                    type(command.get("value"))
                )
                
                string_commands.append(command)
            
            try:
                self.device_manager.send_commands(self.device.id, string_commands)
            except Exception as e:
                LOGGER.error("Error sending command to gate: %s", e)
                # Попробуем другой формат если первый не сработал
                try:
                    # Возможно API ожидает числовые значения для кодов вместо строк
                    numeric_commands = []
                    for cmd in string_commands:
                        if cmd["code"].isdigit():
                            cmd["code"] = int(cmd["code"])
                        numeric_commands.append(cmd)
                    LOGGER.debug("Trying with numeric codes: %s", numeric_commands)
                    self.device_manager.send_commands(self.device.id, numeric_commands)
                except Exception as e2:
                    LOGGER.error("Second attempt also failed: %s", e2)
        else:
            self.device_manager.send_commands(self.device.id, commands)

    def _send_gate_command(self, command_code: str, value: int) -> None:
        """Send a simplified command to gate device.
        
        Args:
            command_code: Command code as string (101, 102, 103, etc.)
            value: Command value as integer (typically 1 for ON, 0 for OFF)
        """
        if self.device.category != "qt":
            LOGGER.error("_send_gate_command called for non-gate device")
            return
        
        # Возможные форматы для командных кодов
        possible_commands = []
        
        # 1. Числовые значения (строковые)
        possible_commands.append({"code": command_code, "value": value})
        
        # 2. Числовые значения (целые числа)
        if command_code.isdigit():
            possible_commands.append({"code": int(command_code), "value": value})
        
        # 3. Преобразование в snake_case в зависимости от кода
        snake_case_code = None
        if command_code == "101":
            snake_case_code = "gate_open"
        elif command_code == "102":
            snake_case_code = "gate_close"
        elif command_code == "103":
            snake_case_code = "gate_stop"
        elif command_code == "104":
            snake_case_code = "gate_lock"
        elif command_code == "110":
            snake_case_code = "gate_fast_open"
        
        if snake_case_code:
            possible_commands.append({"code": snake_case_code, "value": value})
            
            # Также пробуем другие варианты snake_case
            if command_code == "101":
                possible_commands.append({"code": "open", "value": value})
                possible_commands.append({"code": "open_gate", "value": value})
            elif command_code == "102":
                possible_commands.append({"code": "close", "value": value})
                possible_commands.append({"code": "close_gate", "value": value})
            elif command_code == "103":
                possible_commands.append({"code": "stop", "value": value})
            elif command_code == "104":
                possible_commands.append({"code": "lock", "value": value})
            elif command_code == "110":
                possible_commands.append({"code": "fast_open", "value": value})
                possible_commands.append({"code": "fast_opening", "value": value})
        
        # Перебираем все возможные форматы команд
        last_error = None
        LOGGER.debug("Trying all possible command formats for gate command %s, value=%s", command_code, value)
        for cmd in possible_commands:
            try:
                LOGGER.debug("Sending gate command: %s", cmd)
                self.device_manager.send_commands(self.device.id, [cmd])
                LOGGER.debug("Command successful: %s", cmd)
                return
            except Exception as e:
                last_error = e
                LOGGER.debug("Command failed: %s with error: %s", cmd, e)
        
        # Если все команды не сработали, выбрасываем последнюю ошибку
        if last_error:
            LOGGER.error("All command formats failed for gate %s. Last error: %s", command_code, last_error)
            raise last_error
