"""Ocular IQ support (Ocular POC).

Everything the fork adds for the Ocular IQ charger and its grid meter lives
here and in select.py, so the upstream modules only carry one-line hooks:

- ocppv16.py calls handle_data_transfer() from on_data_transfer,
- sensor.py calls async_setup_sensors() from its platform setup,
- switch.py calls async_setup_switches() from its platform setup,
- const.py adds the select platform to PLATFORMS.

Nothing here acts on a charge point unless its device registry entry
identifies it as an Ocular IQ device.
"""

from __future__ import annotations

import json
import logging
import math

from homeassistant.core import callback
from homeassistant.helpers import device_registry as dr

from .const import CONF_CPID, CONF_CPIDS, DOMAIN

_LOGGER: logging.Logger = logging.getLogger(__package__)

# The Ocular IQ devices, as their BootNotification identifies them
# (chargePointVendor / chargePointModel, kept on the device registry entry).
OCULAR_VENDOR = "Ocular"
OCULAR_MODEL = "IOCAH30-7SE-RW"  # the charger
OCULAR_METER_MODEL = "M_IOCAH30-7SE-RW"  # its grid meter

# The metrics the meter's vendor DataTransfer carries, one sensor each.
METER_METRICS = (
    "Current.Ocular.Grid",
    "Power.Active.Ocular.Grid",
    "Ocular.EcoMode",
    "Ocular.SolarEnabled",
)


# ------------------------------------------------------------------
# Device detection
# ------------------------------------------------------------------


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


def configured_cpids(entry) -> list[str]:
    """Return the cpid of every charge point in a config entry."""
    return [list(charger.values())[0][CONF_CPID] for charger in entry.data[CONF_CPIDS]]


def find_meter_cpid(hass, entry) -> str | None:
    """Return the cpid of the config entry's Ocular IQ meter, if it has one."""
    for cpid in configured_cpids(entry):
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

    unsub = hass.bus.async_listen(dr.EVENT_DEVICE_REGISTRY_UPDATED, _on_device_update)

    @callback
    def _on_unload():
        if unsub is not None:
            unsub()

    entry.async_on_unload(_on_unload)


# ------------------------------------------------------------------
# Hooks called from the upstream modules
# ------------------------------------------------------------------


def handle_data_transfer(cp, vendor_id, kwargs) -> None:
    """Store the grid readings an Ocular IQ meter sends as DataTransfer.

    Called by ocppv16.ChargePoint.on_data_transfer for every DataTransfer,
    after upstream's own handling. Anything that is not an IoCharger
    meterValue from the Ocular IQ meter is left alone, and a malformed one
    is logged, so the charger's answer is never affected.
    """
    if vendor_id != "IoCharger" or kwargs.get("message_id") != "meterValue":
        return
    if not is_ocular_meter(_device_for(cp.hass, cp.id)):
        return
    try:
        payload = json.loads(kwargs["data"])
        grid = payload["sampledValue"]["powerGrid"][0]
        current = float(grid["current"][0])
        power = float(grid["powerToGrid"])
        eco_mode = payload["ecoMode"]
        solar_enabled = payload["enableSolar"]

        if not math.isfinite(current) or not math.isfinite(power):
            raise ValueError("Non-finite grid measurement")
        if not isinstance(eco_mode, str) or not isinstance(solar_enabled, bool):
            raise ValueError("Invalid eco mode or solar-enabled value")
    except (KeyError, IndexError, TypeError, ValueError) as err:
        _LOGGER.warning("Invalid Ocular meterValue from %s: %s", cp.id, err)
        return

    values = {
        "Current.Ocular.Grid": (current, "A"),
        "Power.Active.Ocular.Grid": (power, "W"),
        "Ocular.EcoMode": (eco_mode, None),
        "Ocular.SolarEnabled": ("Enabled" if solar_enabled else "Disabled", None),
    }
    for key, (value, unit) in values.items():
        cp._metrics[0][key].value = value
        cp._metrics[0][key].unit = unit
    cp._async_refresh_metric_entities(list(values))


@callback
def async_setup_sensors(hass, entry, central_system, async_add_entities) -> None:
    """Add the meter's grid and solar sensors to the Ocular IQ meter."""
    from .sensor import ChargePointMetric, OcppSensorDescription

    def _sensors(cpid):
        return [
            ChargePointMetric(
                hass,
                central_system,
                cpid,
                OcppSensorDescription(
                    key=metric.lower().replace(".", "_"),
                    name=metric.replace(".", " "),
                    metric=metric,
                ),
                connector_id=None,
            )
            for metric in METER_METRICS
        ]

    for cpid in configured_cpids(entry):
        async_add_when_ocular(
            hass,
            entry,
            cpid,
            lambda cpid=cpid: _sensors(cpid),
            async_add_entities,
            is_match=is_ocular_meter,
        )


@callback
def async_setup_switches(hass, entry, central_system, async_add_entities) -> None:
    """Add the solar switch to the Ocular IQ charger."""
    from .select import OcularSolarSwitch

    for cpid in configured_cpids(entry):
        async_add_when_ocular(
            hass,
            entry,
            cpid,
            lambda cpid=cpid: [OcularSolarSwitch(central_system, cpid)],
            async_add_entities,
        )
