"""Support for Vivint binary sensors."""
from __future__ import annotations

from datetime import datetime, timedelta

from vivintpy.devices import VivintDevice
from vivintpy.devices.camera import MOTION_DETECTED, Camera
from vivintpy.devices.wireless_sensor import WirelessSensor
from vivintpy.enums import EquipmentType, SensorType

from homeassistant.components.binary_sensor import (
    DOMAIN as PLATFORM_DOMAIN,
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later
from homeassistant.util.dt import utcnow

from .const import DOMAIN
from .hub import VivintEntity, VivintHub

MOTION_STOPPED_SECONDS = 30

ENTITY_DESCRIPTION_MOTION = BinarySensorEntityDescription(
    "motion", device_class=BinarySensorDeviceClass.MOTION
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Vivint binary sensors using config entry."""
    entities = []
    hub = hass.data[DOMAIN][config_entry.entry_id]

    for system in hub.account.systems:
        for alarm_panel in system.alarm_panels:
            for device in alarm_panel.devices:
                if isinstance(device, WirelessSensor):
                    entities.append(VivintBinarySensorEntity(device=device, hub=hub))
                elif isinstance(device, Camera):
                    entities.append(
                        VivintCameraBinarySensorEntity(
                            device=device,
                            hub=hub,
                            entity_description=ENTITY_DESCRIPTION_MOTION,
                        )
                    )
                elif hasattr(device, "node_online"):
                    entities.append(
                        VivintOnlineBinarySensorEntity(
                            device=device, hub=hub, key="node_online"
                        )
                    )
                elif hasattr(device, "is_online"):
                    entities.append(
                        VivintOnlineBinarySensorEntity(
                            device=device, hub=hub, key="is_online"
                        )
                    )

    if not entities:
        return

    async_add_entities(entities, True)

    @callback
    def async_add_sensor(device: VivintDevice) -> None:
        """Add Vivint binary sensor."""
        entities: list[VivintBinarySensorEntity] = []
        if isinstance(device, WirelessSensor):
            entities.append(VivintBinarySensorEntity(device=device, hub=hub))

        async_add_entities(entities)

    config_entry.async_on_unload(
        async_dispatcher_connect(
            hass,
            f"{DOMAIN}_{config_entry.entry_id}_add_{PLATFORM_DOMAIN}",
            async_add_sensor,
        )
    )


class VivintBinarySensorEntity(VivintEntity, BinarySensorEntity):
    """Vivint Binary Sensor."""

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"{self.device.alarm_panel.id}-{self.device.id}"

    @property
    def is_on(self) -> bool:
        """Return true if the binary sensor is on."""
        return self.device.is_on

    @property
    def device_class(self) -> BinarySensorDeviceClass:
        """Return the class of this device."""
        equipment_type = self.device.equipment_type

        if equipment_type == EquipmentType.MOTION:
            return BinarySensorDeviceClass.MOTION

        elif equipment_type == EquipmentType.FREEZE:
            return BinarySensorDeviceClass.COLD

        elif equipment_type == EquipmentType.WATER:
            return BinarySensorDeviceClass.MOISTURE

        elif equipment_type == EquipmentType.TEMPERATURE:
            return BinarySensorDeviceClass.HEAT

        elif equipment_type == EquipmentType.CONTACT:
            sensor_type = self.device.sensor_type

            if sensor_type == SensorType.EXIT_ENTRY_1:
                return (
                    BinarySensorDeviceClass.GARAGE_DOOR
                    if "TILT" in self.device.equipment_code.name
                    else BinarySensorDeviceClass.DOOR
                )

            elif sensor_type == SensorType.PERIMETER:
                return (
                    BinarySensorDeviceClass.SAFETY
                    if "GLASS_BREAK" in self.device.equipment_code.name
                    else BinarySensorDeviceClass.WINDOW
                )

            elif sensor_type in [SensorType.FIRE, SensorType.FIRE_WITH_VERIFICATION]:
                return BinarySensorDeviceClass.SMOKE

            elif sensor_type == SensorType.CARBON_MONOXIDE:
                return BinarySensorDeviceClass.GAS

        else:
            return BinarySensorDeviceClass.SAFETY


class VivintCameraBinarySensorEntity(VivintEntity, BinarySensorEntity):
    """Vivint Camera Binary Sensor."""

    def __init__(
        self,
        device: VivintDevice,
        hub: VivintHub,
        entity_description: BinarySensorEntityDescription,
    ) -> None:
        """Pass coordinator to CoordinatorEntity."""
        super().__init__(device=device, hub=hub)
        self.entity_description = entity_description
        self._last_motion_event: datetime | None = None
        self._motion_stopped_callback: CALLBACK_TYPE = None

    @property
    def name(self) -> str:
        """Return the name of this entity."""
        return f"{self.device.name} Motion"

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"{self.device.alarm_panel.id}-{self.device.id}"

    @property
    def is_on(self) -> bool:
        """Return true if the binary sensor is on."""
        return (
            self._last_motion_event is not None
            and self._last_motion_event >= utcnow() - timedelta(seconds=30)
        )

    async def async_added_to_hass(self) -> None:
        """Register callbacks."""
        await super().async_added_to_hass()
        self.async_on_remove(self.device.on(MOTION_DETECTED, self._motion_callback))

    async def async_will_remove_from_hass(self) -> None:
        """Disconnect callbacks."""
        await super().async_will_remove_from_hass()
        self.async_cancel_motion_stopped_callback()

    @callback
    def _motion_callback(self, _) -> None:
        """Call motion method."""
        self.async_cancel_motion_stopped_callback()

        self._last_motion_event = utcnow()
        self.async_write_ha_state()

        self._motion_stopped_callback = async_call_later(
            self.hass, MOTION_STOPPED_SECONDS, self.async_motion_stopped_callback
        )

    async def async_motion_stopped_callback(self, *_) -> None:
        """Motion stopped callback."""
        self._motion_stopped_callback = None
        self._last_motion_event = None
        self.async_write_ha_state()

    @callback
    def async_cancel_motion_stopped_callback(self) -> None:
        """Clear the motion stopped callback if it has not already fired."""
        if self._motion_stopped_callback is not None:
            self._motion_stopped_callback()
            self._motion_stopped_callback = None


class VivintOnlineBinarySensorEntity(VivintEntity, BinarySensorEntity):
    """Vivint online binary sensor entity."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = True
    _attr_name = "Online"

    def __init__(self, device: VivintDevice, hub: VivintHub, key: str) -> None:
        """Initialize a Vivint online binary sensor entity."""
        super().__init__(device=device, hub=hub)
        self._key = key

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"{self.device.alarm_panel.id}-{self.device.id}-online"

    @property
    def is_on(self) -> bool:
        """Return true if the binary sensor is on."""
        return getattr(self.device, self._key)
