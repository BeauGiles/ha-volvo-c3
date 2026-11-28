# Changelog

All notable changes to Volvo C3 (domain `volvo_au`). This integration and [Polestar C3](https://github.com/BeauGiles/ha-polestar-c3) talk to the same Volvo C3 backend and were brought in line with each other on 18 and 19 November 2026, so most entries here have a matching entry in the Polestar changelog.

Dates are 2026.

## Unreleased

## 0.5.1 (28 November)

### Added

- **Diagnostics ask for the car's official images.** The Volvo app shows pictures of the actual car, as built, from an image service the integration doesn't use yet. Downloading diagnostics now lists the image links and the paint colour, to see whether they'd make a good device picture. The links expire after a while.

## 0.5.0 (28 November)

### Added

- **Has the car got the change yet?**
  - The Charging schedule switch has a `sync_status` attribute: `synced` once the car has the change, or `syncing`, `retrying`, `retrying_car_offline` or `error` while it hasn't. It also shows `updated_at`, `changed_by` (`mapp` for the app, or `car`) and, when the backend sends one, `sync_message`. Until now a pending change looked the same as an applied one.
  - Target SoC and Charge current show `updated_at` and `changed_by`. These settings have no sync status.
  - Climate timers aren't included, because neither car sends a sync status for them.

  Matches Polestar C3.
- **Air purification last cycle has attributes:**
  - `started_at`: when the cycle started.
  - `measured_at`: when the cabin air was last measured.
  - `air_quality_index`: the car's own index.
  - `pm2_5`.
  - `last_cycle_valid`.
  - `air_filter_health`, when the car reports it.

  An XC40 sends 0 for both readings, so those two stay hidden until it measures something. Matches Polestar C3.
- **Climate time remaining shows the longest climate run** as `max_runtime_minutes`, from the car record (30 on an XC40). Matches Polestar C3.
- **Charge now.** A binary sensor shows whether charge now is overriding the charge timer, from the same state the app reads (`GetEnabledOverrideChargeTimerAction`). Its attributes say the exact state, including pending, and which charge-now button the app offers (`charge_now`, `resume_schedule` or `not_applicable`). It's shown when the car record says `supportsChargeNowTimerOverride`, as an XC40's does. Matches Polestar C3.
- **Last charging error.** A diagnostic timestamp sensor listens to the backend's error stream, which stays silent until the car can't apply a change to charging or the climate timers. It then shows when that happened, with `setting`, `error` and `action` attributes, for example charge now, `car`, `start_override_charge_timer`. Its state changes, so automations can trigger on it. It runs with the live updates option. Matches Polestar C3.
- **The software update shows when the current software was installed.** An `installed_at` attribute comes from a field in the gRPC car record that neither app names (92); the REST car record doesn't have it. On an XC40 it's 4 Oct 2026, about 47 s after the 5.2.16 install finished. It's read every 6 hours and right after an install completes.
- **Vehicle info shows the data sharing consent:** `data_sharing_enabled`, `data_sharing_car_in_sync` and `data_sharing_read_only`. Remote commands can fail while it's off. Read every hour.
- **The VIN sensor shows the vehicle type code** from the car record: 536 for an XC40 / EX40, 534 for a Polestar 2.
- **Diagnostics include a few read-only calls the integration doesn't poll,** made once when diagnostics are downloaded: car preview, the gRPC car record (with fields the REST record leaves out, such as 43, 44, 45 and 92), Plug & Charge on/off, connected car contract and the error stream. Their fields are shown by number. The battery pack serial, PCID, visual ID and registration are removed from every value, not only from known keys.
- **The software update shows its full release notes.** Volvo sends the app's release notes with the update details; the update entity now offers them under "Release notes", converted from Volvo's markup to plain text. The short summary is unchanged.
- **The car tracker says when its parked position is out of date.** A `location_stale` attribute carries Volvo's own flag. It's true while the car is being driven, when the tracker still shows where it last parked, and clears once it parks again (seen on an XC40).

### Changed

- **The Cabin air quality index sensor is now called Cabin PM2.5.** It has always shown PM2.5 in µg/m³, not the car's air quality index, which is now the `air_quality_index` attribute on Air purification last cycle. Only the display name changes: the entity ID, history and automations are the same. Matches Polestar C3.

### Fixed

- **The OTA schedule's `relative_time` in diagnostics is now -2 when nothing is scheduled.** It used to show as 18446744073709551614, because the negative number was read as unsigned. Matches Polestar C3.
- **The alarm sensor now reads the car's alarm.** It looked for `alarmStatus`, which the car never sends. The car sends `alarm`, for example `ALARM_STATUS_IDLE` on a parked XC40, so Alarm triggered could never turn on. The old key is still read as a fallback. Matches Polestar C3.
- **The quick polling after a trip starts when the car is parked.** At the end of a trip the integration polls every 5 seconds for 5 minutes, so the lock state catches up when the car is locked, and checks the trip journal for the new trip more often. It used to wait for the car to report Abandoned, which an XC40 only does 7–10 minutes after parking, by when the driver has usually locked it and left. It now starts as soon as the car stops reporting Driving (or Engine on). A missing or unknown usage mode no longer counts as the end of a trip.
- **The tailgate lock reads the car's own tailgate lock signal.** It used to guess from the central lock and remember a tailgate unlock sent from Home Assistant, because no separate signal was known. The exterior reply carries `tailgateLock` (seen on an XC40), so it's used when present. After an unlock from Home Assistant, the lock shows unlocked until the car sends a newer reading. Cars without the signal keep the old behaviour.
- **The charge current slider follows the car's own range.** The car record says which currents the car accepts: 6–32 A on an Australian XC40, up to 48 A in North America. The slider was fixed at 6–32 A.
- **The Target SoC slider starts at the car's own minimum.** The car record says the lowest target charge level the car accepts (50 % on an XC40). The slider used to start at 20 %, so values the car would refuse could be picked. When the car record doesn't say, it still starts at 20 %.
- **Start charging, Stop charging, Charge current and Charge limit report it when the car's service says no.** These charging commands only checked that Volvo's server took the request, so a refusal looked like a success. Their reply is now read too: a charge-now reply with a validation, internal or not-found error, or a SetAmpLimit or SetTargetSoc reply that says the car is offline or reported an error, raises an error in Home Assistant. A reply without a status is let through as before. Volvo's replies to these commands are now logged at INFO, like the other commands, so we can confirm the format on a real car. Matches Polestar C3 ([#52](https://github.com/BeauGiles/ha-polestar-c3/pull/52)), from ericyew ([67952fd](https://github.com/ericyew/unofficial-polestar-api/commit/67952fdf5d5bf453d52fc3a7a992b613c288598b)).

## 0.4.1 (27 November)

### Added

- **Charging type** (none, AC, DC, wireless) and **Charger power status** sensors, matching Polestar C3 (battery fields 17 and 26). Read as `chargingType` and `chargerPowerStatus`, which an XC40 sends (Volvo's `NO_POWER_AVAILABLE` shows as No power); a car whose battery reply never has them gets them hidden on the first poll, like other features it lacks.
- **Cold battery status**, **Average speed (auto)**, **Unavailable reason**, **Any door open** and **Climate active**, matching Polestar C3. Cold battery status is hidden on a car whose first battery reply says `UNSPECIFIED` (an XC40 does, like the Polestar 2), and Average speed (auto) on one that never sends it. Climate active follows parking climatization, so it is hidden with the other climate sensors on a car without it.
- Diagnostics downloads now also redact the battery pack serial number and Plug & Charge ID.

### Fixed

- **Time to full charge**, **Time to target charge** and **Time to minimum SoC** read 0 min when not charging, instead of unknown. Volvo's JSON reply leaves out fields that are 0; Polestar C3 already showed 0.

## 0.4.0 (27 November)

### Added

- **Software update** entity, matching Polestar C3: the update Volvo offers for the car, with its state, schedule and release title. **Install** starts it now, and the `volvo_au.schedule_ota` (delay in minutes) and `volvo_au.cancel_ota` services schedule or cancel it, using the Volvo app's own OTA scheduler (`ota_mobcache.SchedulerService`). The installed version comes from the car record and is kept across restarts. Install is offered only when the car says it allows remote install scheduling (an XC40 does). Reads correctly on an XC40 (5.2.16, up to date); install, schedule and cancel are untested, as no update was waiting.
- **Battery thermal event** binary sensor (safety): a high-voltage battery thermal event reported by the car (`batteryThermalEventTriggered`, health field 48, as named in the Volvo app, which has a help screen for it). The car leaves the field out when there is no event, so it reads off. Listed under Diagnostic. Matches Polestar C3.
- **Time to target charge** and **Time to minimum SoC** (diagnostic): the car's own charging time estimates (battery fields 9 and 19, as in the Volvo app). Matches Polestar C3.
- **Climate running status** (Active, Start attempt, Not running), **Climate request type** (diagnostic: now from car, now from remote, timer, keep climate) and **Climate time remaining**, from the parking climatization record the Climate switch already reads. The state keys match Polestar C3's, so automations read the same on both. Not yet seen from a real car.

### Fixed

- **Streamed values survive a failed poll.** When a poll could not read a section (an error or an empty reply) that a live stream had delivered, such as the odometer or battery, the poll wiped it until the next stream message. The streamed value is now kept. Same fix as ericyew's for Polestar ([0da9bc1](https://github.com/ericyew/unofficial-polestar-api/commit/0da9bc1b692d86bf5f115464cd1ed80f2829f6eb)).

### Changed

- **Charge port hidden on electric XC40 and C40.** On these cars (CMA platform, like the Polestar 2) the charge port status stays closed even with a cable in, so the sensor is disabled. It is decided from the car's model and engine type, as no capability flag covers it; you can still enable it. Matches Polestar C3 on the Polestar 2.
- **Honk and flash is now Lights and horn, and Honk is now Horn**, as the Polestar app calls them (Flash lights already matched). The entity IDs are unchanged.
- **Boot and bonnet, not tailgate and hood.** Hood is now **Bonnet** (Australian and UK wording). The Tailgate binary sensor is now **Boot**, and the Tailgate control and Close tailgate buttons are **Open boot** and **Close boot**, matching Boot lock and the Australian wording. Their icons were blank (`mdi:truck-tailgate` is not a Material Design icon) and are now `mdi:arrow-up-box` and `mdi:arrow-down-box`. Only names and icons change; existing entity IDs stay. Matches Polestar C3.
- **Connection reads "In use" while the car is being used**, matching the Volvo app, instead of "Offline: car in use" ("In use from the app" for Volvo's remote-use reason). Volvo reports the car unavailable for remote commands while it is driven, so it never really was offline. Other reasons still read "Offline: …". The In use binary sensor is unchanged. Matches Polestar C3.
- **Entity sections tidied**, matching Polestar C3: **12V battery**, **Brake fluid**, **Light status**, **Engine coolant low**, **Oil level low** and **Software version** move to Diagnostic (health warnings that normally read OK, and versions).
- **README:** an unofficial and unsupported warning at the top and a fuller Disclaimer, pointing to Volvo's official Home Assistant integration for the regions its API supports.
- Documentation uses GitHub alert boxes (note, tip, important, warning) for the points that matter.
- **FAQ: new Volvo sign-in page.** Since late November Volvo ID forwards sign-in to a new page on `auth.volvocars.com`. The integration works with it unchanged (tested 27 November with Reconfigure); the FAQ explains what to expect.

## 0.3.1 (21 November)

### Changed

- The `User-Agent` sent to Volvo is now `vca-ios/7.6.0` (was `vca-ios/6.9.0`), matching the current Volvo Cars app version.

## 0.3.0 (18 to 21 November)

### Read this before updating

- **Sensor states are now lowercase keys.** Charging status, Charger connection and Usage mode are enum sensors that report `charging`, `idle`, `scheduled`, `done`, `connected`, `disconnected`, `driving`, `engine_on` and so on, and the frontend shows translated text. Automations and dashboards that compare to `Charging`, `Idle` or `Connected` must use the lowercase keys. Charging status: `charging, idle, scheduled, discharging, error, smart_charging, done, smart_charging_paused`. Charger connection: `connected, disconnected, fault`. Usage mode: `abandoned, inactive, convenience, active, driving, engine_on, engine_off`. A value outside these lists shows as unknown and is logged once.
- **The Connection sensor state is short:** `Online`, `Offline: <short reason>` or `Unknown`. The longer explanation and `offline_since` are attributes.
- **Entities were removed or merged** (see Removed). Registry entries for them are deleted at setup.
- **Display names changed**, entity IDs did not. Cards that show the entity's own name will look different; cards with hand-typed names will not.
- **Why it is called "Volvo C3":** the integration uses Volvo's C3 services, the same ones the Volvo Cars app uses, not Volvo's official public API (which is not available in some countries, including Australia). Nothing in it is specific to one market, so it is named after the platform, not a country, in the same way as Polestar C3.
- The domain is still `volvo_au`. Changing it would orphan existing entries and entity IDs, so it is left for a later migration.

### Harmonised with Polestar C3

- Renamed to **Volvo C3** (display name, config flow titles, HACS name, README, class names). The integration works for more than Australian cars.
- Shared entity names in sentence case: Service required, 12V battery, Brake fluid, Washer fluid, Front left door and window (no hyphens), Charge port, Online, State of charge, Outside temperature, Time to full charge, Trip meter (auto) and (manual), Cabin air quality index, Flash lights, Honk and flash, Lock with reduced alarm, Charging amp limit, Target SoC, Climate target temperature, Front left seat heating (and the other seats and steering wheel), Climate, Air purification, Charging schedule with Charging schedule start and end, Boot lock. Tyre pressure sensors are "Front left tyre pressure" and so on.
- Icons copied from Polestar, including state-dependent icons on doors and problem sensors. Volvo no longer sets its own icon on the location tracker, Boot lock and Usage mode.
- Enum sensors with translated states, whole-number display by default for distance, range, battery, speed and times, entity categories (configuration and diagnostic), and the same attribute names for warnings.
- Same behaviour: Start charging is refused with a clear message when the car is not plugged in; Alarm triggered shows OK instead of Unknown when no alarm is reported; In use also follows "unavailable because the car is in use"; reconfigure flow; entity names come from translations; hidden entities for features the car says it lacks; diagnostics download.

### Added

- **Tyre warning:** one binary sensor. Attributes give each wheel's grade (`ok`, `very_low`, `low`, `high`) and pressure in kPa, only on cars that report individual pressures. Separate pressure sensors appear only on those cars.
- **Live Activities guide:** [docs/live-activities.md](docs/live-activities.md) has example automations for charging and climate Live Activities on iOS and Android.
- **Service required** attributes `service_urgency` (`almost_due`, `due`, `overdue`) and `service_reason` (`regular`, `engine_hours`, `distance`).
- **Command refusal reasons:** the car's reply to a command is now read. A refusal says why (privacy mode on, car being driven, another command in progress, timeouts) instead of looking like success. Not yet tested against a real refusal. A "car offline" status is not treated as a refusal because it was seen on commands that worked.
- **Driving journal (opt in):** Last trip sensor, Trips this month and Distance this month, and the services `get_trips` and `get_trips_summary`. Off by default because trips include places.
- **Live update streams** (experimental; each service falls back to polling).
- **Climate controls** for cars that support them (experimental, untested on a real car): target temperature and seat and steering wheel heating, applied the next time climate starts. Hidden on cars whose record says they are not supported (the XC40).
- **Diagnostics download** and a disabled-by-default Vehicle info sensor with the car record, VIN sensor, optional registration plate, stable device name.
- **Options:** idle and active poll intervals. Plugged in but not charging stays on the idle poll.
- **Per-tyre pressure sensors**, climate action attribute, Light status attributes, Charging switch, Honk button, Sunroof sensor only on cars that report a sunroof.
- When an account has several cars, only cars not set up yet are offered.

### Changed

- **Cabin air quality index** now reports PM2.5 in µg/m³ (PM2.5 device class), like Polestar's.
- **Target SoC, Charging amp limit and Charging schedule** are re-read every 2 minutes instead of every 15, so changes made in the Volvo app show up within about a poll (5 minutes idle, 1 minute while charging). The app does not push these.
- Slow-changing data (software, weather) is polled less often.
- Charging schedule and Boot lock names match Polestar.
- First-poll check: entities with no data from the car are hidden.

### Removed

- **Last seen sensor.** It changed every few seconds and filled the activity log. The Online sensor keeps `last_seen` as an attribute; Connection keeps `offline_since`.
- **Target SoC sensor.** The Target SoC number replaces it.
- The four per-wheel tyre warning binary sensors (replaced by Tyre warning with attributes).

### Fixed

- Alarm triggered no longer shows Unknown on cars that send no alarm state.
- A timed-out command is reported as such instead of an unexpected error.
