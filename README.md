# Sleep Timer for Unfolded Circle Remote Two/3

Custom integration that turns off selected devices or runs configured Remote macros:

- after 15, 30, 45, 60, 90, or 120 minutes;
- after the media item that was playing when the timer was armed;
- immediately for testing.

The integration exposes a **Sleep Timer remote entity** with its own touch UI and simple commands, plus status and
remaining-time sensors. Its commands can also be placed on buttons in existing activities and macros.

The complete timer button layout is embedded in the remote entity. Version 0.1.2 and later also synchronizes this page
once for entities that were already configured with an older version, because Remote Core normally imports a driver's
default UI only during the initial entity configuration.

Version 0.1.3 adds up to six independent off targets. Supported targets are power-capable media players, remotes,
activities, lights and switches, plus existing Remote macros. All selected actions are attempted in their configured
order; one failing target does not prevent the remaining targets from being processed.

Version 0.1.8 detects the active activity through Remote Core's dedicated activity and activity-group endpoints and sends
`activity.off` before the configured device targets run. It then verifies that Core actually reached `OFF`, so a command
accepted by the API is no longer reported as successful while the Remote still shows the old activity. The behavior is
enabled by default and can be disabled in setup.

## Supported current-item sources

| Source | Detection | Reliability |
|---|---|---|
| Emby | Direct Emby Sessions API, using item id, position, and duration | Recommended |
| Emby media entity | Remote Core media-player attributes | Depends on the selected entity |
| Netflix on Nvidia Shield | Remote Android TV entity title/id or position/duration | Depends on metadata supplied by Netflix/Android TV |
| Prime Video on Nvidia Shield | Remote Android TV entity title/id or position/duration | Depends on metadata supplied by Prime/Android TV |

Netflix and Prime sometimes expose only the foreground app name. That is not enough to distinguish one episode from
the next. In that case the integration deliberately refuses to arm **After current item** instead of switching everything
off at an unsafe moment. Fixed timers continue to work normally.

## Before installation

1. Add every device that the timer should switch off to Remote Core. Alternatively, create a Remote macro such as
   **Everything off** if a more complex command sequence or delays are required.
2. Create a Remote Core API key. The Core API requires a bearer token for entity reads and command execution.
3. For reliable Emby monitoring, create an Emby API key in **Dashboard → Advanced → API Keys**.

The Core API connection defaults to `http://127.0.0.1:8080`, the local Remote Core endpoint. If that does not work on
your firmware, enter the Remote's normal web-configurator URL, for example `http://192.168.0.50`.

## Installation and setup

1. Download the latest `uc-intg-sleep-timer-...-aarch64.tar.gz` archive from Releases.
2. Install it with Integration Manager as a custom integration.
3. Enter the Remote Core URL and API key.
4. Keep **Turn off active Remote activity** set to **Yes** so the previous activity is closed in Remote Core.
5. Choose up to six **Off targets**. Each dropdown can contain devices with a power-off command and Remote macros.
6. Select the Nvidia Shield media-player entity if Netflix or Prime Video should be monitored.
7. Optionally enter the Emby Server URL, API key, and a device-name filter such as `Shield` or `LG`.
8. Add the **Sleep Timer** entity. The two sensor entities are optional.

When updating from version 0.1.2, the previous single macro remains selected as target 1. Run setup again to replace it
or add direct device targets.

Every published version has its own GitHub release and standalone installation archive. Existing version packages are
never replaced.

Available simple commands:

`TIMER_15`, `TIMER_30`, `TIMER_45`, `TIMER_60`, `TIMER_90`, `TIMER_120`, `AFTER_CURRENT`, `ADD_15`,
`SUBTRACT_15`, `CANCEL`, and `RUN_NOW`.

## Development

Requires Python 3.11.

```bash
python -m pip install -r requirements.txt -r test-requirements.txt
PYTHONPATH=intg-sleep-timer python -m unittest discover tests
ruff check intg-sleep-timer tests
ruff format --check intg-sleep-timer tests
```

## Security

API keys are stored only in the integration's private configuration directory and are never written to logs. Use a
dedicated Remote Core key and revoke it when the integration is removed.

## License

Mozilla Public License 2.0. See [LICENSE](LICENSE).
