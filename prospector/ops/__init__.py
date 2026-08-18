"""`prospector/ops` — the ops spine (OPS_CONSOLE_PROGRAM §4).

Two surfaces read the engine today: Telegram through `scheduler/status.py`, and the Next.js ops
console through `readers.py` in this package. Two readers of one truth is the defect memory
`one-reader-two-caller-shapes` records. Everything in here is written to be imported by BOTH,
so a number rendered on the phone and the same number at the desk cannot drift.

  * `readmodel.py` — reads only. No process may be started, no file written, from this module.
  * `pause.py`     — the one writer for the three pause scopes, with the fence in the WRITER.
"""
