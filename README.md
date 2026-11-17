# OCPP – Ocular IQ fork

> **This is a fork, not the official integration.** It is based on the Home Assistant
> [OCPP integration](https://github.com/lbbrhzn/ocpp) by lbbrhzn, and is used to develop
> deeper support for the Ocular IQ solar-enabled EV charger. For the supported integration,
> its documentation and its releases, use the
> [upstream repository](https://github.com/lbbrhzn/ocpp).

## What this fork adds

The upstream integration already handles the Ocular IQ as a standard OCPP 1.6 charger.
This fork is a proof of concept that adds the charger's solar features, which it reports
and controls outside the standard OCPP messages.

### Grid and solar readings from the meter

The Ocular IQ's grid meter connects as its own charge point and sends its readings as
vendor `DataTransfer` messages (vendor `IoCharger`, message `meterValue`) rather than as
standard meter values. The fork reads those messages and shows them as sensors on the
meter device:

| Sensor | Meaning |
| --- | --- |
| Current Ocular Grid | Current at the grid connection (A) |
| Power Active Ocular Grid | Power exported to the grid (W) |
| Ocular EcoMode | The charging mode the charger reports |
| Ocular SolarEnabled | Whether the solar feature is on (`Enabled` / `Disabled`) |

### Solar controls on the charger

Two controls on the charger device change its solar behaviour through OCPP configuration
keys:

- **Ocular charging mode** (a select): *Fast*, *Solar Only* or *Solar Assist*, set through
  the `EcoMode` key.
- **Ocular solar enabled** (a switch): turns the solar feature on or off, set through the
  `enableSolar` key.

Both controls show the state the meter last reported, update as soon as a new reading
arrives, and are available only while the charger and the meter are both connected.

## Status and limitations

This is a proof of concept, not a finished feature:

- The charge point ids are fixed in the code: the charger must be `charger` and the meter
  `meter`, and the meter must connect as `Ocular-IQ-Meter`.
- It works with OCPP 1.6 only.
- After you change a setting, the control keeps showing the old value until the meter
  reports the new one.

The fork's code is marked with `# Ocular POC` banners in `const.py`, `ocppv16.py`,
`sensor.py`, `switch.py` and `select.py` under `custom_components/ocpp/`, so it can be
kept apart from upstream changes.
