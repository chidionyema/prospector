# Demo — the vendor ratchet

The ratchet counts how many times the repository depends on a vendor we are leaving, and fails a
change that makes the number bigger. It exists because Fly.io cannot be deleted in one commit:
production takes money through Fly today, and the deploy path for the live shop is inside the set
of files that would have to go.

Run on 2026-08-24, on this repository.

## What the estate actually looks like

```
$ .venv/bin/python scripts/vendor_ratchet.py --update
fly: 586 occurrences in 130 files  [NEW BASELINE]
baseline written: ops/config/vendor_ratchet.json
```

586 references across 130 executable files, documentation excluded. That is the number the
eradication has to walk down to zero.

## It allows the estate as it stands

```
$ .venv/bin/python scripts/vendor_ratchet.py --check
fly: 586 occurrences in 130 files  [unchanged]
exit=0
```

This half matters as much as the other one. A gate that only ever says no would have to be
bypassed by every honest change, and a bypassed gate measures nothing.

## It refuses a new one, and names it

Adding one file containing `fly deploy -a something-new`:

```
$ .venv/bin/python scripts/vendor_ratchet.py --check
fly: 587 occurrences in 131 files  [GREW +1]
    +1    deploy/newdep.sh   (new file)
    A new fly reference is a new dependency on a vendor this estate is
    leaving. Use the portable path, or if this really is unavoidable, say why
    in the commit and run: scripts/vendor_ratchet.py --update --vendor fly
exit=1
```

## And goes back to allowing once the file is gone

```
$ .venv/bin/python scripts/vendor_ratchet.py --check
fly: 586 occurrences in 130 files  [unchanged]
exit=0
```

Four runs, in order: baseline, allow, refuse, allow again. A gate tested only on the case it is
meant to stop has not been shown to be safe to install.
