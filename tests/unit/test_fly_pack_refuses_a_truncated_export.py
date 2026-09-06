"""`fly ssh sftp get` truncates and exits 0, so the export has to prove its own bytes.

Measured 2026-08-23 on the weekly escape hatch drill: 112,474,776 bytes were packed on the Fly
VM and 12,779,520 bytes arrived (11.4%). flyctl printed "12779520 bytes written" and returned
success. `tar` then said "Unexpected EOF in archive", exit 2. Two 100 MB control transfers taken
the same day came back byte-exact, so the truncation is intermittent rather than a size ceiling.

That is the worse shape. A ceiling fails every time and gets noticed. An intermittent silent
truncation lets the drill go green on a partial store, and the drill is the only thing that says
whether we can leave the platform (LAW 19). The old check in the workflow was
`[ "$bytes" -gt 1000000 ]`, which an 11% payload passes comfortably.

Rung 4, incident test. It pins the rule, not the implementation: an export either arrives
byte-exact or it does not arrive at all. Retrying the whole file would satisfy the first case
and quietly fail the second, which is why both cases are here.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import tarfile
from pathlib import Path

ADAPTER = Path(__file__).resolve().parents[2] / "deploy" / "targets" / "fly.sh"

PART_BYTES = 65536       # the production value is 16 MiB; small here so the test stays cheap
ARCHIVE_MIN = 4          # parts, so there is a middle part to corrupt


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 16), b""):
            h.update(block)
    return h.hexdigest()


def _vm(tmp_path: Path) -> Path:
    """A stand-in for the Fly volume, holding a packed archive of several parts.

    The payload is urandom because the archive must not compress: the split has to produce more
    than one part for the per-part retry to be under test at all.
    """
    vm = tmp_path / "vm"
    (vm / "store").mkdir(parents=True)
    (vm / "store" / "prospector.jsonl").write_bytes(os.urandom(PART_BYTES * ARCHIVE_MIN))
    with tarfile.open(vm / "handover.tar.gz", "w:gz") as tar:
        tar.add(vm / "store", arcname=".")
    return vm


def _bin(tmp_path: Path, vm: Path, *, truncate_attempts: int) -> Path:
    """A PATH carrying a `fly` that truncates one part, and a portable `sha256sum`.

    `truncate_attempts` is how many times `handover.part.001` comes back short before the stub
    starts serving it honestly. A number above the retry count is the never-recovers case.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    # macOS has shasum and no sha256sum; the runner has sha256sum. Both sides of the comparison
    # must hash the same way or the test measures the shim rather than the transfer.
    (bin_dir / "sha256sum").write_text(
        "#!/bin/sh\n"
        'exec python3 -c "'
        "import hashlib,sys\n"
        "h=hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest()\n"
        "print(h+'  '+sys.argv[1])"
        '" "$1"\n'
    )
    (bin_dir / "fly").write_text(f"""#!/bin/sh
# fly ssh sftp get -a APP SRC DEST
[ "$1" = "ssh" ] || exit 0
src=$6
dest=$7
name=$(basename "$src")
if [ "$name" = "handover.part.001" ]; then
  n=$(cat "{tmp_path}/attempts" 2>/dev/null || echo 0)
  n=$((n + 1))
  echo "$n" > "{tmp_path}/attempts"
  if [ "$n" -le {truncate_attempts} ]; then
    # The measured failure: a short file, written successfully, exit 0.
    head -c 1000 "{vm}/$name" > "$dest"
    exit 0
  fi
fi
cp "{vm}/$name" "$dest"
exit 0
""")
    for stub in ("sha256sum", "fly"):
        (bin_dir / stub).chmod(0o755)
    return bin_dir


def _pack(tmp_path: Path, vm: Path, bin_dir: Path, out: Path) -> subprocess.CompletedProcess:
    """Source the adapter, replace t_exec with a local shell, and run t_pack.

    t_exec is overridden AFTER sourcing so the adapter's own definition is the one being
    replaced. The override runs the VM-side command locally against the fake volume, and turns
    the pack into a no-op because the archive is already there.
    """
    override = (
        "t_exec() { "
        f'  case "$1" in *store_migrate.py*) return 0 ;; esac; '
        f'  sh -c "$(printf %s "$1" | sed "s#/data/#{vm}/#g")"; '
        "}"
    )
    return subprocess.run(
        ["bash", "-c", f'source "{ADAPTER}" >/dev/null 2>&1; {override}; t_pack "{out}"'],
        env={
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "HOME": str(tmp_path),
            "APP": "test-app",
            "PROSPECTOR_PACK_PART_BYTES": str(PART_BYTES),
        },
        capture_output=True, text=True, timeout=300, check=False,
    )


def test_incident_20260823_a_truncated_part_is_refetched_until_the_export_is_byte_exact(tmp_path):
    vm = _vm(tmp_path)
    bin_dir = _bin(tmp_path, vm, truncate_attempts=2)
    out = tmp_path / "handover.tar.gz"

    # Read the source hash first. t_pack removes the packed file from the VM on every exit
    # path, which is correct - the Fly volume must not keep filling up - and means the oracle
    # has to be taken before the run rather than after it.
    want = _sha256(vm / "handover.tar.gz")

    run = _pack(tmp_path, vm, bin_dir, out)

    assert run.returncode == 0, f"stdout:\n{run.stdout}\nstderr:\n{run.stderr}"
    assert out.exists(), "a successful export must leave the archive"
    assert _sha256(out) == want, "the export is not byte-exact against the VM"
    assert "sha mismatch" in run.stderr, (
        "the truncation never happened, so this run proved nothing"
    )


def test_incident_20260823_an_export_that_cannot_be_completed_leaves_no_file(tmp_path):
    vm = _vm(tmp_path)
    bin_dir = _bin(tmp_path, vm, truncate_attempts=99)   # never recovers
    out = tmp_path / "handover.tar.gz"

    run = _pack(tmp_path, vm, bin_dir, out)

    assert run.returncode != 0, f"a partial export reported success:\n{run.stdout}"
    assert not out.exists(), (
        "an aborted export left a file behind; the next reader takes it for the store"
    )
    assert "EXPORT ABORTED" in run.stderr, run.stderr
