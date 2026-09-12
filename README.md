# Sleep Timer for Unfolded Circle Remote Two/3

Custom integration that runs a configured Remote macro:

- after 15, 30, 45, 60, 90, or 120 minutes;
- after the media item that was playing when the timer was armed;
- immediately for testing.

The integration exposes a **Sleep Timer remote entity** with its own touch UI and simple commands, plus status and
remaining-time sensors. Its commands can also be placed on buttons in existing activities and macros.

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

1. In the Remote web configurator, create a macro such as **Everything off**. Add the desired commands in their safe
   order, for example light off, TV off, and Denon off.
2. Create a Remote Core API key. The Core API requires a bearer token for entity reads and command execution.
3. For reliable Emby monitoring, create an Emby API key in **Dashboard → Advanced → API Keys**.

The Core API connection defaults to `http://127.0.0.1:8080`, the local Remote Core endpoint. If that does not work on
your firmware, enter the Remote's normal web-configurator URL, for example `http://192.168.0.50`.

## Installation and setup

1. Download the latest `uc-intg-sleep-timer-...-aarch64.tar.gz` archive from Releases.
2. Install it with Integration Manager as a custom integration.
3. Enter the Remote Core URL and API key.
4. Select the Nvidia Shield media-player entity and the macro to execute.
5. Optionally enter the Emby Server URL, API key, and a device-name filter such as `Shield` or `LG`.
6. Add the **Sleep Timer** entity. The two sensor entities are optional.

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
