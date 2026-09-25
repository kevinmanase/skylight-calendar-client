# Skylight Calendar Client (Unofficial)

A small Python client and CLI for studying how a personal calendar integration fits together: request mapping, authentication, lists, events, and the boundary between a one-time import and a real sync service.

**Independent, unofficial, and published for educational study.** This project is not affiliated with, endorsed by, sponsored by, or supported by Skylight or Glimpse LLC. Product names identify the system studied; no trademark rights are granted.

**Read before connecting:** Skylight's [Terms of Service](https://myskylight.com/tos/) restrict access through unsupported interfaces and reverse engineering (§5.4). An educational purpose or an open-source license does not override those terms or give permission to access a service. See [DISCLAIMER.md](DISCLAIMER.md). You can read the code and run the offline tests without credentials or a Skylight account.

## Why this exists

I like my Skylight. My favorite part is the lists. Checking things off is the point.

I also like holding the button on my phone, telling Siri to remind me about something, and moving on. Those reminders live in Apple Reminders. I wanted them on the calendar too.

The original experiment inspected the web app's request shapes, built this client, and copied 33 reminders into Skylight. Their contents, account identifiers, credentials, and import receipts are not included here.

## What is here

- A standard-library Python client and command-line interface.
- Methods for lists, calendar events, and a limited set of chore operations.
- One token-refresh attempt after an authentication failure.
- Offline tests using synthetic data and mocked network requests.
- [API notes](API.md) and [automation design notes](ARCHITECTURE.md): IFTTT, Apple Shortcuts, their limits, and a rough Mac-based sync proposal.

There is no automatic Reminders sync, Apple Reminders reader, hosted service, or web portal in this repository. The original personal importer contained private data and is not distributed.

## Status and compatibility

This is an educational prototype. Endpoint observations and successful live checks come from the original experiment on September 1, 2026; they are not a promise of current compatibility or coverage of every method.

This public-source revision removes personal examples, improves credential-file handling, avoids printing server error bodies, and identifies itself with its own User-Agent. **It has only been tested offline.** The service may reject its requests. Stop on access restrictions; do not use this project to bypass them.

## Start offline

Use Python 3.9 or later. No third-party Python dependencies are required.

```sh
python3 skylight.py --help
python3 -m unittest discover -s tests -v
```

The tests do not connect to Skylight or read your credentials. Examples use invented data.

## Configuration for authorized experiments

Only connect if you have the necessary rights and permissions under applicable terms and law. Owning an account alone is not a determination that this integration is permitted. This repository does not provide a login flow, credential-extraction tool, or instructions for bypassing service controls.

The client reads these settings from the environment or a local `.env` next to `skylight.py`:

| Setting | Meaning |
| --- | --- |
| `SKYLIGHT_FRAME_ID` | The device identifier for an authorized experiment. |
| `SKYLIGHT_ACCESS_TOKEN` | An access token obtained through an authorized process. |
| `SKYLIGHT_REFRESH_TOKEN` | Optional refresh token. |
| `SKYLIGHT_TIMEZONE` | Default timezone for timed CLI events; defaults to `UTC`. |

`.env.example` contains no credentials. Keep any local `.env` private. When credentials come from that file without account or credential overrides, refresh writes use an atomic replacement with owner-only permissions. Credentials supplied through environment overrides or a manually constructed client configuration stay in memory; their refreshed values do not survive process exit. A `.env` containing unrelated settings does not opt environment credentials into disk storage.

Commands such as `add-item`, `check`, `uncheck`, `add-event`, and `del-item` perform real writes when configured against a live service. There is no undo or dry-run mode. Read the method before using it; use disposable test data in an authorized environment.

For example, the library keeps endpoint details behind a small method:

```python
def add_item(self, list_id, label, category_id=None, section=None):
    body = {"label": label, "category_id": category_id, "section": section}
    return self._req("POST", self.f(f"lists/{list_id}/list_items"), body)
```

This is an excerpt, not a standalone program. `self.f()` adds the configured device path; `_req()` handles the request and refresh logic.

## Credentials and private data

Do not commit or attach tokens, `.env` files, browser storage, cookies, HAR captures, real reminders, calendar exports, or account/device identifiers. The client intentionally returns account data on successful reads, so treat its output as private too. See [SECURITY.md](SECURITY.md).

## Credits

- [Dax's post](https://x.com/thdxr/status/2078727284865827140), which credits James Long, illustrated deriving a client from browser network requests.
- [Matt Van Horn's Printing Press](https://github.com/mvanhorn/cli-printing-press) was a reference for the approach. Its source code is not bundled here.

## License

The original implementation in this repository is offered under the [MIT License](LICENSE), including its warranty and liability provisions. Educational study describes the purpose of sharing it; it is not an extra use restriction on that license. MIT permits reuse, including commercial reuse, of the code. It does not license Skylight's service, trademarks, software, or other third-party rights, or establish that any service access is permitted.

No compatibility, maintenance, legal protection, or production-readiness guarantee is provided.
