################################################################################
# Ocular POC
################################################################################
"""Ocular IQ controls."""

from homeassistant.components.select import SelectEntity
from homeassistant.components.sensor import DOMAIN as SENSOR_DOMAIN
from homeassistant.components.switch import SwitchEntity
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo, Entity

from .chargepoint import SetVariableResult
from .const import CONF_CPID, CONF_CPIDS, DATA_UPDATED, DOMAIN, sensor_unique_id

# The Ocular IQ devices, as their BootNotification identifies them
# (chargePointVendor / chargePointModel, kept on the device registry entry).
OCULAR_VENDOR = "Ocular"
OCULAR_MODEL = "IOCAH30-7SE-RW"  # the charger
OCULAR_METER_MODEL = "M_IOCAH30-7SE-RW"  # its grid meter


def is_ocular_charger(device) -> bool:
    """Return whether a device registry entry is the Ocular IQ charger."""
    return (
        device is not None
        and (device.manufacturer or "").strip() == OCULAR_VENDOR
        and (device.model or "").strip() == OCULAR_MODEL
    )


def is_ocular_meter(device) -> bool:
    """Return whether a device registry entry is the Ocular IQ grid meter.

    Matched on the model alone: the meter's vendor has not been checked.
    """
    return device is not None and (device.model or "").strip() == OCULAR_METER_MODEL


def _device_for(hass, cp_ident):
    """Return the device registry entry of a charge point, by cpid or cp_id."""
    return dr.async_get(hass).async_get_device(identifiers={(DOMAIN, cp_ident)})


def find_meter_cpid(hass, entry) -> str | None:
    """Return the cpid of the config entry's Ocular IQ meter, if it has one."""
    for charger in entry.data[CONF_CPIDS]:
        cpid = list(charger.values())[0][CONF_CPID]
        if is_ocular_meter(_device_for(hass, cpid)):
            return cpid
    return None


@callback
def async_add_when_ocular(
    hass, entry, cpid, make_entities, async_add_entities, is_match=is_ocular_charger
):
    """Add entities for a charge point once it is known to be an Ocular IQ device.

    is_match picks the device: the charger by default, or is_ocular_meter.
    Any other charge point gets nothing. The vendor and model come from the
    device registry, which keeps them from the last BootNotification, so a
    known device gets its entities at startup. One that has not booted yet
    gets them as soon as its BootNotification fills those fields in.
    """

    def _device():
        return _device_for(hass, cpid)

    if is_match(_device()):
        async_add_entities(make_entities())
        return

    unsub = None

    @callback
    def _on_device_update(event):
        nonlocal unsub
        if unsub is None or not is_match(_device()):
            return
        unsub()
        unsub = None
        async_add_entities(make_entities())

    unsub = hass.bus.async_listen(
        dr.EVENT_DEVICE_REGISTRY_UPDATED, _on_device_update
    )

    @callback
    def _on_unload():
        if unsub is not None:
            unsub()

    entry.async_on_unload(_on_unload)

MODES = {
    "Fast": ("0", "Fast"),
    "Solar Only": ("1", "PV"),
    "Solar Assist": ("2", "PV_plus"),
}


class OcularControl(Entity):
    """Common Ocular control behaviour."""

    # State is pushed: the entity redraws when the integration dispatches an
    # update naming it or the meter sensor its state is read from.
    _attr_should_poll = False
    # The meter metric this control's state is read from.
    state_metric: str

    def __init__(self, central_system, cpid, name, key):
        super().__init__()
        self.central_system = central_system
        self.cpid = cpid
        self._attr_name = name
        self._attr_unique_id = f"{DOMAIN}.{cpid}.ocular_{key}"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, cpid)})

    @property
    def meter_cpid(self) -> str | None:
        """Return the cpid of the Ocular IQ meter this control reads from."""
        if self.hass is None or self.platform is None:
            return None
        return find_meter_cpid(self.hass, self.platform.config_entry)

    def meter_reading(self):
        """Return the meter's last value of this control's state_metric."""
        meter = self.meter_cpid
        if meter is None:
            return None
        return self.central_system.get_metric(meter, self.state_metric)

    @property
    def available(self):
        meter = self.meter_cpid
        return bool(
            meter is not None
            and self.central_system.get_available(self.cpid)
            and self.central_system.get_available(meter)
        )

    async def async_added_to_hass(self):
        await super().async_added_to_hass()

        @callback
        def _maybe_update(*args):
            # The meter's DataTransfer refreshes only the sensors it changed,
            # so this entity's own id is never in that list: also redraw
            # when the meter sensor backing this control is. Looked up by
            # unique_id on each update, so a renamed sensor still matches.
            changed = None
            if args:
                try:
                    changed = set(args[0])
                except TypeError:
                    changed = None
            if changed is not None:
                watched = {self.entity_id}
                meter = self.meter_cpid
                sensor_id = (
                    er.async_get(self.hass).async_get_entity_id(
                        SENSOR_DOMAIN,
                        DOMAIN,
                        sensor_unique_id(meter, self.state_metric),
                    )
                    if meter is not None
                    else None
                )
                if sensor_id is not None:
                    watched.add(sensor_id)
                if not changed & watched:
                    return
            self.async_write_ha_state()

        self.async_on_remove(
            async_dispatcher_connect(self.hass, DATA_UPDATED, _maybe_update)
        )

    async def set_config(self, key, value):
        cp_id = self.central_system.cpids.get(self.cpid, self.cpid)
        cp = self.central_system.charge_points.get(cp_id)
        if cp is None or not self.available:
            raise HomeAssistantError("Ocular charger or meter is unavailable")

        result = await cp.configure(key, value)
        if result not in (
            None,
            SetVariableResult.accepted,
            SetVariableResult.reboot_required,
        ):
            raise HomeAssistantError(f"Unable to set {key}: {result}")


class OcularModeSelect(OcularControl, SelectEntity):
    """Select the Ocular charging mode."""

    _attr_options = list(MODES)
    state_metric = "Ocular.EcoMode"

    def __init__(self, central_system, cpid):
        super().__init__(central_system, cpid, "Ocular charging mode", "mode")

    @property
    def current_option(self):
        reading = self.meter_reading()
        return next(
            (name for name, (_, meter_value) in MODES.items() if reading == meter_value),
            None,
        )

    async def async_select_option(self, option):
        if option not in MODES:
            raise HomeAssistantError(f"Unknown Ocular mode: {option}")
        await self.set_config("EcoMode", MODES[option][0])


class OcularSolarSwitch(OcularControl, SwitchEntity):
    """Enable or disable the Ocular solar feature."""

    state_metric = "Ocular.SolarEnabled"

    def __init__(self, central_system, cpid):
        super().__init__(central_system, cpid, "Ocular solar enabled", "solar")

    @property
    def is_on(self):
        reading = self.meter_reading()
        if reading == "Enabled":
            return True
        if reading == "Disabled":
            return False
        return None

    async def async_turn_on(self, **kwargs):
        await self.set_config("enableSolar", "1")

    async def async_turn_off(self, **kwargs):
        await self.set_config("enableSolar", "0")


async def async_setup_entry(hass, entry, async_add_entities):
    central_system = hass.data[DOMAIN][entry.entry_id]

    for charger in entry.data[CONF_CPIDS]:
        cpid = list(charger.values())[0][CONF_CPID]
        async_add_when_ocular(
            hass,
            entry,
            cpid,
            lambda cpid=cpid: [OcularModeSelect(central_system, cpid)],
            async_add_entities,
        )