# ha-iawai

A [Home Assistant](https://www.home-assistant.io/) custom integration for
[IAWAI – Flowing Waters](https://www.iawai.co.nz/), the regional water
services provider for Hamilton City and Waikato District, Aotearoa New
Zealand.

Fetches your household water consumption data from the IAWAI/Oplex customer
portal and makes it available in Home Assistant, including full integration
with the **Energy → Water dashboard**.

---

## Features

- 📊 **Water dashboard integration** — hourly bars back to your chosen
  history start date, powered by HA's external statistics API
- 💧 **Yesterday's consumption sensor** — glanceable daily total in litres
- 📈 **Cumulative total sensor** — rising lifetime total for automations
- 🔄 **Incremental updates** — only fetches new data each run; full
  history injected once on first install
- 🕐 **Twice-daily polling** — syncs at 10:30 and 22:30 NZDT to align
  with IAWAI's two daily publish batches, keeping sensors current
  within 30 minutes of each update
- 🔍 **Auto-discovery** — owner, project, site group and site IDs are
  discovered automatically from your account; no manual lookup required
- 🔑 **Token refresh** — handles bearer token expiry transparently

---

## Requirements

- Home Assistant **2024.1** or later (uses `entry.runtime_data` and
  `async_add_external_statistics`)
- An **IAWAI customer account** with online portal access
  ([iawai.oplex.nz](https://iawai.oplex.nz))
- A **water meter** registered to your account (Hamilton City or Waikato
  District)

> **Note:** IAWAI water metering is currently available to residential
> customers in Hamilton City and parts of Waikato District. If you do not
> have a smart meter you will not have consumption data in the portal.

---

## Installation

### Manual (recommended until HACS support is added)

1. Copy the `custom_components/iawai/` folder into your Home Assistant
   `config/custom_components/` directory:

   ```
   config/
   └── custom_components/
       └── iawai/
           ├── __init__.py
           ├── api.py
           ├── config_flow.py
           ├── const.py
           ├── coordinator.py
           ├── manifest.json
           ├── sensor.py
           └── translations/
               └── en.json
   ```

2. **Before installing**, open `const.py` and set `HISTORY_START` to the
   date your meter data begins. Check your IAWAI portal for the earliest
   available reading:

   ```python
   HISTORY_START = date(2026, 3, 26)  # ← change to your earliest reading date
   ```

3. Restart Home Assistant.

4. Go to **Settings → Devices & Services → Add Integration** and search
   for **IAWAI Water**.

---

## Configuration

The config flow asks for your IAWAI portal credentials only. Your meter
identifiers are discovered automatically from your account.

| Field | Description |
|---|---|
| **Username** | Your IAWAI portal email address |
| **Password** | Your IAWAI portal password |

> **Note:** Auto-discovery currently supports accounts with a single owner
> and single site. If your account has multiple sites, please open an issue.

---

## Sensors

### `sensor.iawai_water_total_water_consumption`
**Total water consumption** — continuously rising cumulative total in litres
from `HISTORY_START` to end of yesterday. Used as the source for the
**Energy → Water dashboard**.

- Device class: `water`
- State class: `total_increasing`
- Unit: `L`

### `sensor.iawai_water_yesterday_s_consumption`
**Yesterday's consumption** — total litres consumed yesterday. Resets at
midnight each day. Useful as a glanceable card on a Lovelace dashboard.

- Device class: `water`
- State class: `total`
- Unit: `L`

---

## Adding to the Water Dashboard

1. Go to **Settings → Energy → Water**
2. Select **Add water source**
3. Search for **IAWAI Water Consumption** (the external statistic, not the
   sensor)
4. Save

The dashboard will populate with historical daily bars back to
`HISTORY_START` after the first coordinator run.

---

## Known Limitations

### ~24-hour data lag

IAWAI publishes consumption data with approximately a **24-hour lag** —
today's usage will not appear until tomorrow. Data arrives in two daily
batches:

| Batch | Approximate time (NZDT) | Coverage |
|-------|------------------------|----------|
| 1 | ~10:15 | Previous day 07:00 – 19:00 |
| 2 | ~22:15 | Previous day 19:00 – current day 07:00 |

Together the two batches provide a complete 24-hour picture from the
previous day. The integration polls at **10:30 and 22:30 NZDT** to
align with these batches, so sensors are updated within 15 minutes of
each publish.

> **Note:** The publish schedule above is based on limited observation
> (as at October 2026). Your meter may differ. See
> https://github.com/harlows/ha-iawai/issues/4 for ongoing observations.

### History start date is hardcoded
`HISTORY_START` in `const.py` must be set manually before installation.
A future version will make this configurable in the config flow. See
[issue #2](https://github.com/harlows/ha-iawai/issues/2).

### Single site only
Auto-discovery currently supports accounts with one owner and one site.
Multi-site support is tracked in
[issue #5](https://github.com/harlows/ha-iawai/issues/5).

---

## Troubleshooting

### No data appearing in the Water dashboard
- Confirm the **IAWAI Water Consumption** statistic (not the sensor) is
  added as the water source in **Settings → Energy → Water**
- Check logs for `custom_components.iawai` — enable debug logging:

  ```yaml
  logger:
    default: warning
    logs:
      custom_components.iawai: debug
  ```

- Force a coordinator refresh via **Developer Tools → Actions →
  `homeassistant.update_entity`** targeting
  `sensor.iawai_water_total_water_consumption`

### Yesterday sensor showing 0 or stale value
The yesterday sensor reads from the recorder database. It may lag one
coordinator run behind newly injected data. This is expected behaviour
and self-corrects on the next poll.

---

## Contributing

Bug reports and pull requests are welcome at
[github.com/harlows/ha-iawai](https://github.com/harlows/ha-iawai/issues).

Please include:
- Your HA version
- Integration version (from `manifest.json`)
- Relevant debug logs

---

## Acknowledgements

Inspired by [ha-meridian-energy](https://github.com/danfickling/ha-meridian-energy)
by Dan Fickling, particularly the `async_add_external_statistics` pattern
for injecting backdated hourly data into the HA recorder.

---

## Licence

[MIT Licence](https://github.com/harlows/ha-iawai/blob/main/LICENSE)
