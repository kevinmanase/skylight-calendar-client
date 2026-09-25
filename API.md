# Observed API shapes

Historical notes from an experiment on the author's own account on September 1, 2026. These are observations, not an official specification or a statement that automated access is permitted. Review [DISCLAIMER.md](DISCLAIMER.md) before considering live use. The public revision has not been tested against the service.

## Request boundary

The client uses `https://app.ourskylight.com/api` with JSON request bodies and a bearer token supplied by the operator. Resource responses observed in the experiment used a `data` wrapper with record IDs and `attributes`.

`Skylight.f(path)` scopes an operation to `frames/{frame_id}/`. All identifiers below are symbolic placeholders, not account data.

| Client operation | Method | Relative API path |
| --- | --- | --- |
| List devices | GET | `frames` |
| List categories | GET | `frames/{frame}/categories` |
| List calendars' events | GET | `frames/{frame}/calendar_events?date_min=YYYY-MM-DD&date_max=YYYY-MM-DD` |
| Create an event | POST | `frames/{frame}/calendar_events` |
| Update/delete an event | PUT / DELETE | `frames/{frame}/calendar_events/{event}` |
| List lists | GET | `frames/{frame}/lists` |
| Read/add list items | GET / POST | `frames/{frame}/lists/{list}/list_items` |
| Set item status/delete item | PUT / DELETE | `frames/{frame}/lists/{list}/list_items/{item}` |
| Read chores | GET | `frames/{frame}/chores/all?after=YYYY-MM-DD&before=YYYY-MM-DD` |
| Create a chore | POST | `frames/{frame}/chores` |
| Complete a chore | PUT | `frames/{frame}/chores/{chore}/completions` |

Example list-item body, using synthetic data:

```json
{"label": "Example task", "category_id": null, "section": null}
```

The client can set a list item's status to `pending` or `completed`. An endpoint appearing in this table does not mean every operation, payload, or edge case was tested.

## Refresh behavior

After a `401`, the client makes at most one refresh attempt at `https://app.ourskylight.com/oauth/token`, then repeats the original request if refresh succeeded. Failure stops the operation. This handles an expired token; it is not permission to work around an access denial.

The refresh exchange is implemented in the code for study. The repository does not supply credentials or a process for extracting browser sessions.

## Historical checks and limits

The original experiment verified reads, a list-item create/complete/delete round trip, timed and all-day calendar create/delete round trips, and token refresh. A separate personal script then copied 33 reminders; that script and all personal data are excluded.

Recurring-event deletion used an `apply_to` query parameter (`this`, `all`, or `following`), rather than a JSON request body. Chore queries required both dates.

Recurring events, timezones, retry safety, write idempotency, rate limits, and every possible error response have not been comprehensively tested. The client does not automatically retry transport failures or ambiguous writes. The service may reject the client's identification or authentication; no evasion fallback is included.
