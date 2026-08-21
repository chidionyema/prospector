# Classes a project may declare, with no adapter here yet

`kit/projects/<name>.yaml` says which substrates each class of resource may move to. Saying so
does not move it -- a class moves when there is a `kit/classes/<class>.sh` beside this file.
Until then the plan compiles, the run starts, and the step fails by name at whatever minute the
plan reaches it.

This list exists so that gap is visible from the tree rather than from a failed migration.
`tests/e2e/test_migration_end_to_end.py` fails when it drifts from what is actually on disk, in
either direction: writing an adapter and forgetting this file is as much a defect as the reverse,
because the next person reads this file to decide what is left.

Delete a line when its adapter lands.

- `ci_runner`
- `datastore`
- `dns`
- `log_sink`
- `object_storage`
- `payment_integration`
- `scheduled_job`
- `secret`
- `tls_certificate`
