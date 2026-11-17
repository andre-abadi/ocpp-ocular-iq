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

The Ocular IQ's grid meter (its CT clamp) connects as its own charge point and sends its
readings as vendor `DataTransfer` messages (vendor `IoCharger`, message `meterValue`)
rather than as standard meter values. The fork reads those messages and shows them as
sensors on the meter device:

| Sensor | Meaning |
| --- | --- |
| Current Ocular Grid | Current at the grid connection (A) |
| Power Active Ocular Grid | Grid power (W): positive is export; negative is assumed to be import, not yet confirmed |
| Ocular EcoMode | The charging mode the charger is set to (`Fast`, `PV` or `PV_plus`) |
| Ocular SolarEnabled | Whether the charger's solar feature is on (`Enabled` / `Disabled`) |

### Solar controls on the charger

Two controls on the charger device change its solar behaviour through OCPP configuration
keys:

- **Ocular charging mode** (a select): *Fast*, *Solar Only* or *Solar Assist*, set through
  the `EcoMode` key.
- **Ocular solar enabled** (a switch): turns the solar feature on or off, set through the
  `enableSolar` key.

## Setup

### 1. Connect the charger

Point the charger at Home Assistant in its web interface, as for the upstream integration:
under **Basic / Server**, set the domain to your Home Assistant IP, port `9000`, path
`central`, an identity such as `Ocular-IQ-Charger`, and security profile `ws`. The charger
then appears in the OCPP integration.

### 2. Point the meter at the integration

The meter can't be redirected from the web interface. It has its own server settings,
hidden configuration keys on the charger whose names start with `b`, and by default they
point at Ocular's cloud (`ocpp.ocularcharging.com.au`).

**Before you change them, record their current values** so you can switch back.
Redirecting the meter away from Ocular's cloud will likely stop the Ocular app from
showing its readings. To see the current values, run this action in Home Assistant
(**Developer tools → Actions**), using your charger's charge point id as `devid`:

```yaml
action: ocpp.get_configuration
data:
  devid: charger
```

Then set each `b` key to match the charger's own server settings with `ocpp.configure`,
one call per key:

| Key | Set it to | Default (Ocular cloud) |
| --- | --- | --- |
| `bsDomain` | Your Home Assistant IP (the charger's `sDomain`) | `ocpp.ocularcharging.com.au` |
| `bsPort` | `9000` (the charger's `sPort`) | `9113` |
| `bsURL` | `/central` (the charger's `sURL`) | `/ocpp/energy` |
| `bsecurityProfile` | `0` (the charger's `securityProfile`) | `2` |
| `bId` | A new identity for the meter, such as `Ocular-IQ-Meter` | The charger's serial number |

For example:

```yaml
action: ocpp.configure
data:
  devid: charger
  ocpp_key: bsDomain
  value: "192.168.1.50"
```

The charger answers `reboot_required: true`. After the last key, reboot the charger, with
its **Reset** button in Home Assistant or from its web interface.

### 3. Add the meter

Once the charger restarts, the meter connects as a second charge point, and the OCPP
integration offers to add a new device. Add it with any charge point id (for example
`meter`) and the default settings.

When the meter has booted and reported its model, the four Ocular sensors appear on its
device. Its standard OCPP controls and sensors don't apply to it and stay unavailable or
unknown, so you can disable them. With debug logging on, its readings show up as
`Data transfer received from Ocular-IQ-Meter` lines.

## How the meter and charger work together

The charger holds the settings and acts on them. The meter is a passive observer: it
reads the charger's settings and reports them in its own `meterValue` messages, using
names instead of the charger's numbers:

| Charging mode | Charger `EcoMode` | Meter `Ocular.EcoMode` |
| --- | --- | --- |
| Fast | `0` | `Fast` |
| Solar Only | `1` | `PV` |
| Solar Assist | `2` | `PV_plus` |

| Solar feature | Charger `enableSolar` | Meter `Ocular.SolarEnabled` |
| --- | --- | --- |
| On | `1` | `Enabled` |
| Off | `0` | `Disabled` |

`EcoMode` and `enableSolar` are separate settings: changing the mode to *Fast* doesn't
change `enableSolar`. How the two combine on the charger is still being worked out.

The fork's controls follow this split:

- **They write to the charger.** Choosing a mode or flipping the switch sends
  `ChangeConfiguration` to the charger, the same as `ocpp.configure`.
- **They read from the meter.** Each control shows the state the meter last reported, and
  updates as soon as a new meter reading arrives.
- **A change takes effect only after a reboot.** The charger answers `reboot_required`, and
  Home Assistant shows a notification saying so. Until you reboot the charger (with its
  **Reset** button) and the meter reports the new setting, the control keeps showing the
  old value.
- **Both controls need both devices.** They are unavailable unless the charger and the
  meter are both connected.

## Status and limitations

This is a proof of concept, not a finished feature:

- The fork only acts on the Ocular IQ devices, recognised by the model they report when
  they boot: `IOCAH30-7SE-RW` (vendor `Ocular`) for the charger and `M_IOCAH30-7SE-RW`
  for the meter. Any other charger behaves exactly as with the upstream integration.
  Charge point ids don't matter.
- It works with OCPP 1.6 only.
- One meter per integration: if more than one charge point reports the meter model, the
  controls use the first one listed.

The fork's code is marked with `# Ocular POC` banners in `const.py`, `ocppv16.py`,
`sensor.py`, `switch.py` and `select.py` under `custom_components/ocpp/`, so it can be
kept apart from upstream changes.
