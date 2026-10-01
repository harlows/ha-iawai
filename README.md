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
- 🔄 **Incremental updates** — only fetches new data each run; full history
  injected once on first install
- 🕐 **Overlap window** — re-fetches the last 2 days on every run to catch
  late-arriving hourly data from IAWAI's multi-tranche publish schedule
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

The config flow will ask for the following fields. All values can be found
in your IAWAI portal account settings or in the URL when viewing your meter:

| Field | Description |
|---|---|
| **Username** | Your IAWAI portal email address |
| **Password** | Your IAWAI portal password |
| **Account ID** | Numeric account identifier |
| **Site ID** | Identifier for your property/site |
| **Meter Group ID** | Identifier for your meter group |
| **Meter ID** | Identifier for your specific meter |

> **Tip:** Log in to [iawai.oplex.nz](https://iawai.oplex.nz), navigate to
> your meter, and inspect the URL or network requests in your browser's
> developer tools to find these identifiers.

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
IAWAI publishes consumption data with approximately a **24-hour lag**.
Today's usage will not appear until tomorrow. Data is published in
multiple tranches throughout the day:

| Tranche | Approximate time (NZDT) | Coverage |
|---|---|---|
| 1 | ~00:00 | Partial — early hours |
| 2 | ~10:00 | More hours added |
| 3 | ~14:00 | Remainder of previous day |

The integration uses a **2-day overlap window** to catch all tranches
correctly. Each run re-fetches the last 2 days and upserts any newly
published hours.

> **Note:** The publish schedule above is based on limited observation
> (as at October 2026). Your meter may differ. See
> [issue #4](https://github.com/harlows/ha-iawai/issues) for ongoing
> observations.

### History start date is hardcoded
`HISTORY_START` in `const.py` must be set manually before installation.
A future version will make this configurable in the config flow. See
[issue #2](https://github.com/harlows/ha-iawai/issues).

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
coordinator run (up to 1 hour) behind newly injected data. This is
expected behaviour and self-corrects on the next hourly run.

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
