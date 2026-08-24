# SECRETS PROGRAM — one source of truth, portable, recoverable

> This is the tracked spec for all secrets work, in the pattern of `COST_PROGRAM.md` and
> `SITE_SPEC_PROGRAM.md`. The rule from `CLAUDE.md` applies: read and append here, never in
> `CLAUDE.md`.
>
> **Every number in this file was measured, and the date is on it.** Nothing here is quoted
> from another document. Re-measure before acting; the commands are given so you can.

Founder, 2026-08-20, verbatim: *"lets reserach oss secret nanagent ools ad solutiions, can b e
la about security and portability as in line with nnigratioa nd contralisation and
consildation"*, and *"seanlessness"*, and *"we need to docunent all research fidings"*.

So this is not a tool choice. It is five properties at once, and a candidate that fails one is
out.

## Part 1 — The five properties (this is the acceptance test)

1. **Security.** A value is never in argv, never in a log, never in a git object in plaintext.
2. **Portability.** The estate moves between Fly, a laptop, a plain VM and Kubernetes. A
   secrets system that works on one of those re-introduces the lock-in that the portability
   contract exists to kill. **Cloud KMS was rejected by name for this reason and the ruling
   stands.**
3. **Migration.** `deploy/cutover.sh` must carry the secrets to the new target inside its own
   phases. The shape is already right: `t_secrets` is one of the eleven verbs.
4. **Centralisation and consolidation.** One source of truth, several sinks. Today the same
   value is authored by hand in more than one place, and every hand-authored copy is a chance
   to drift.
5. **Seamlessness.** Adding, rotating or reading a secret is ONE command or ONE button, on
   every target, with no step in a vendor console.

**The question that decides the shortlist:** *what must be RUNNING for a secret to be
readable?* `age` needs nothing running. A daemon can be down, and a cluster can be down, during
a migration — which is the exact moment secrets are needed. A replacement has to beat that, not
merely out-feature it.

## Part 2 — What we have, MEASURED 2026-08-20

### 2.1 Four sinks hold the same values. Two are updated by hand.

| Sink | Who writes it | Automated |
|---|---|---|
| `deploy/secrets.env.age` — committed ciphertext | `deploy/secrets.sh set` | yes |
| the deploy target (Fly / ssh+docker / k8s) | `deploy/secrets.sh push <target>` | yes |
| GitHub Actions secrets | a human, in the GitHub web UI | **no** |
| `./.env` on the laptop — gitignored, real values | a human | **no** |

### 2.2 The two declared lists have ZERO overlap

`deploy/secrets.required`, 11 names:
`CONTROL_CENTER_PASSWORD`, `EXA_API_KEY`, `MINIMAX_API_KEY`,
`PROSPECTOR_ENTITLEMENTS_API_KEY`, `R2_ACCESS_KEY_ID`, `R2_ACCOUNT_ID`, `R2_BUCKET`,
`R2_SECRET_ACCESS_KEY`, `STORE_API_URL`, `STORE_INTERNAL_API_KEY`, `STRIPE_LIVE_API_KEY`.

`.github/workflows/*.yml`, 5 names:
`FLY_API_TOKEN`, `FLY_API_TOKEN_API`, `FLY_API_TOKEN_ENGINE`, `GITHUB_TOKEN`,
`RUNNER_ADMIN_PAT`.

**Names in both lists: none.** So no declared source of truth covers CI at all. The five CI
credentials — including three Fly deploy tokens, which can deploy anything to anything — exist
only inside GitHub, are backed up nowhere, and are named in no file.

### 2.3 Distribution is already correct, and must stay that way

No target puts a secret value into argv.

| Target | `t_secrets` mechanism |
|---|---|
| `deploy/targets/fly.sh` | `fly secrets import -a "$APP" --stage < "$1"` — stdin |
| `deploy/targets/sshdocker.sh` | `cat "$1" \| _ssh "cat > $DATA/engine.env"` — mode 600, read by `docker --env-file` |
| `deploy/targets/k8s.sh` | `kubectl create secret generic --from-env-file="$1" --dry-run=client -o yaml \| kubectl apply -f -` |
| `deploy/targets/laptop.sh` | a deliberate no-op — `.env` on that box IS the store |

`deploy/secrets.sh push` writes one temp file, mode 600 in `$TMPDIR`, removed by an EXIT trap.

### 2.4 Bootstrap is one line, and it has no second chance

`deploy/secrets.sh:40`

```sh
KEY="${PROSPECTOR_AGE_KEY:-$HOME/.config/prospector/age-key.txt}"
```

A missing key dies at `:47`. There is **no second recipient and no fallback path**. Lose that
one file and the committed ciphertext is scrap. Independently corroborated as gap **G11** at
`docs/personas/security.md:709`.

### 2.5 Rotation: NONE. Read audit: NONE.

`prospector/audit.py` logs decisions, not credential access. Nothing expires or invalidates a
secret. Every rotation is a human act, and two keys are known to need one:
`PROSPECTOR_ENTITLEMENTS_API_KEY` and `STORE_INTERNAL_API_KEY`, exposed 2026-08-18.

### 2.6 The declare / apply / detect test

The same coherence test used for DNS in `WORKLOAD.md` R5.

| | State | Evidence |
|---|---|---|
| **declare** | YES | `deploy/secrets.required` plus the age file |
| **apply** | PARTLY | `secrets.sh push` applies to a deploy target. Nothing applies to GitHub Actions secrets. |
| **detect** | PARTLY | `secrets.sh check` exists. It has not been proven to catch a value that DIFFERS between two sinks — only one that is absent. |

## Part 3 — OSS research findings (COMPLETE, 2026-08-20)

Twenty-four tools scored. Every licence, version and release date below was read from
`api.github.com` on 2026-08-20. Anything not sourced is marked `unverifiable`.

### 3.0 Two corrections to Part 2 that this research forced

Both were found by re-measuring while writing this section, and both make the position worse
than Part 2 described.

1. **We do not use SOPS. We use plain `age`.** `sops` is not installed on this machine and there
   is no `.sops.yaml` in the repo. `deploy/secrets.sh:11` says so in its own header: *"WHY age
   AND NOT sops. age is already installed and already used in this estate."* Every `sops`
   command in the research below therefore needs translating to plain `age` before use, and the
   plain-`age` recipe in 3.6 is the one to follow.

2. **`deploy/secrets.env.age` is not on any branch anyone deploys from.** It is tracked in
   exactly one commit, `56f9cf4f`, whose subject is *"snapshot of uncommitted work in
   wt-fly-migration"*, reachable only from
   `origin/snapshot/2026-08-19-rescue/wt-fly-migration-shared`. It is not on `main`, not on
   `integrate/2026-08-20-final`, and not on disk in either clone. So a fresh clone plus an env
   file — the thing the repo-stays-the-complete-system rule requires — cannot read a single
   secret, because the ciphertext is not there to read.

   That snapshot object is 2860 bytes and carries **exactly one `-> X25519` recipient stanza**,
   which confirms the single-recipient finding at the file-format level rather than by reading
   the script.

3. **`age` on this machine is v1.3.1.** That matters below: post-quantum recipients landed in
   age v1.3.0, so we already have the binary that can do it.

### 3.1 The column that decides it: what must be RUNNING to read a secret

This is the portability question, and it is the same question as the twelve-function contract.
Everything with a daemon in this column becomes a special case on at least one of our four
targets.

| Nothing must be running | A daemon must be running | A cluster must be running | A vendor account must answer |
|---|---|---|---|
| `age`, SOPS+age, SOPS+PGP, git-crypt, dotenvx, SecretSpec, sops-nix/agenix | OpenBao, Vault, Infisical, Vaultwarden, Passbolt, Conjur | Sealed Secrets, External Secrets Operator, SPIRE | Doppler, 1Password, Bitwarden SM, chamber (AWS) |

### 3.2 Scoring table — licence and portability

| Tool | Licence, genuinely OSS in 2026? | Self-host with no vendor account | Works on all four targets | Offline |
|---|---|---|---|---|
| **age** (what we use) | BSD-3-Clause. Yes. v1.3.1, 2025-12-28 | Yes | Yes, identically | Yes |
| **SOPS + age** | MPL-2.0. Yes. CNCF Sandbox. v3.13.3, 2026-07-23 | Yes | Yes, identically | Yes |
| **SOPS + cloud KMS** | Tool yes; the recipient is not | **No** | Only with network | **No** |
| **age-plugin-yubikey** | Apache-2.0. Yes. v0.5.1, 2026-04-08 | Yes | No — needs USB, so not CI | Yes |
| **OpenBao** | MPL-2.0. Yes. v2.6.2, 2026-08-18 | Yes | VM/k8s well; laptop awkward | Yes |
| **HashiCorp Vault** | **BUSL-1.1 — not OSI-approved, not open source.** Now an IBM product | Yes | Same as OpenBao | Yes |
| **Infisical** | Core MIT, `ee/` proprietary — mixed | Core yes | VM/k8s; needs Postgres + Redis | Yes once deployed |
| **Doppler** | Proprietary | **No** | CLI anywhere, values in vendor cloud | Fallback cache only |
| **Bitwarden Secrets Manager** | **SM code is proprietary** under `bitwarden_license/` | **No** — self-host still needs a paid licence | VM/k8s | No |
| **1Password** | Proprietary | **No** | Connect on VM/k8s | Service accounts no |
| **chamber** | MIT. Yes. But it is an AWS SSM front-end | **No** | Needs AWS | **No** |
| **teller** | Apache-2.0 — but **last release 2024-05-20**. Stalled | Yes | CLI anywhere | Backend-dependent |
| **git-crypt** | GPL-3.0. Yes. 0.8.0, 2025-09-24 | Yes | Yes | Yes |
| **blackbox** | **ARCHIVED repo.** Dead | — | — | — |
| **Keywhiz** | **ARCHIVED. Last release 2019.** Dead | — | — | — |
| **Sealed Secrets** | Apache-2.0. Yes. v0.39.1, 2026-08-20 | Yes | **k8s only** | Yes |
| **External Secrets Operator** | Apache-2.0. CNCF **Sandbox**, not incubating | Yes | **k8s only** | Backend-dependent |
| **SPIFFE/SPIRE** | Apache-2.0. CNCF graduated. v1.15.2 | Yes | k8s/VM. **Stores no secrets — it issues identity** | Yes |
| **Vaultwarden** | AGPL-3.0. Yes. 1.37.1 | Yes | All four, light | Yes |
| **Passbolt CE** | AGPL-3.0. Yes. v5.14.3 | Yes | VM/k8s, needs MySQL | Yes |
| **Conjur OSS** | Licence field NOASSERTION — `unverifiable`. CyberArk is now inside Palo Alto Networks, so the OSS edition's future is a real risk | Yes | VM/k8s | Yes |
| **SecretSpec** *(not on the original list)* | Apache-2.0. Yes. v0.19.1, 2026-08-12 | Yes | All four, incl. a `fly://` provider | Yes |
| **dotenvx** *(not on the original list)* | BSD-3-Clause. Yes | Yes | All four | Yes |
| **sops-nix / agenix** *(not on the original list)* | MIT / CC0. Yes | Yes | **NixOS only** | Yes |

### 3.3 Scoring table — recovery, rotation, audit, CI, cost, migration

| Tool | Recovery after total hardware loss | Rotation | Read audit | GitHub Actions | Cost/month | Hours from here |
|---|---|---|---|---|---|---|
| **age / SOPS+age** | **Whatever you arranged in advance. Today: nothing.** With a second recipient: the other key | Manual | **None** | Any action + the key as a secret | £0 | 0 |
| **age + YubiKey** | **A second enrolled key, or you are locked out** | Manual re-enrol | None | **Unusable in CI** | ~£50 one-off ×2 | 2–3 |
| **OpenBao** | Restore Raft storage **and** the unseal material. Lose either and it is gone | **Automatic, short-lived dynamic credentials** | **Yes — audit devices** | Vault-compatible actions | £0 licence + £5–15 VM | **20–40** |
| **Vault** | Same | Same | Yes | `hashicorp/vault-action` | £0 + VM. **HCP Vault Secrets is EOL 2026-07-01** | 20–40 |
| **Infisical** | Postgres + the root `ENCRYPTION_KEY` | Pro tier only | 30 days, Pro | GitHub is a sync destination | Self-host £5–15; Pro **$20/identity/mo** | 8–16 |
| **Doppler** | Vendor holds it | Team tier | 3 days free | Native | Team ~$21/user/mo | 6–12 |
| **1Password** | Secret Key + password + recovery codes | Manual | **Yes — Events API** | `1Password/load-secrets-action` | $7.99/user/mo | 8–16 |
| **Bitwarden SM** | Vendor account | Manual | Retention `unverifiable` | `bitwarden/sm-action` | Teams ~$6/user/mo | 8–16 |
| **git-crypt** | The symmetric key | **Very poor — no rekey story** | None | Manual | £0 | A downgrade |
| **Sealed Secrets** | Back up the controller sealing key | Manual re-seal | No | N/A | £0 + cluster | k8s only |
| **ESO** | Backend-dependent | Backend-dependent | Backend-dependent | **GitHub provider is write-only** | £0 + cluster | k8s only |
| **Passbolt CE** | DB + org GPG key | Manual | **Paid tier only** | Community action | £0 + VPS; Cloud has a **10-seat floor ≈$54/mo** | 10–20 |
| **SecretSpec** | Inherits ours | Inherits | **Yes — a local `secretspec audit` log** | `cachix/secretspec-action` | £0 | 3–6 |

### 3.4 The four design questions, answered

**Q1 — "one laptop holds the only key", without a cloud KMS.** The mechanism is already in the
file format. Per the age v1 spec, each recipient stanza wraps the same file key independently,
so any one identity opens the file, and a recipient costs about 100 bytes of header. Ranked for
our situation:

- **A second software key on another machine — do this first.** Zero cost, zero new tooling, and
  the only one of the four that also fixes the CI path, because it needs no hardware present.
- **An offline printed key — do this second.** An age identity is one bech32 line. Generate,
  print, seal, delete the file. This is the actual answer to *total hardware loss*.
- **A YubiKey** (`age-plugin-yubikey`, Apache-2.0). Good as a second human factor, useless as
  break-glass: decryption needs the token physically present and CI has no USB port. Enrol two
  or you have moved the single point of failure rather than removed it.
- **Passphrase-derived identities — do NOT use.** The spec forbids mixing: *"An scrypt stanza,
  if present, MUST be the only stanza in the header."* A passphrase recipient is all-or-nothing,
  so it cannot be one of several.

**Shamir is the wrong shape for us and we would not need a third-party tool anyway.** SOPS has
had it built in since 3.0.0 (`sops groups`, `--shamir-secret-sharing-threshold`). But Shamir
RAISES the threshold to decrypt; our problem is the opposite — one holder needing more ways in.
Shamir with one founder means one person holds every share, which is one laptop with extra
steps. Revisit when there is a second human.

**Q2 — multiple recipients, any one of which decrypts: yes.** Confirmed twice: at the format
level by the spec sentence above, and at the tool level by `sops rotate --add-age` /
`--rm-age`. In plain `age` it is simply repeated `-r`, or `-R recipients.txt`.

**Q3 — one declare/apply/detect interface across our four sinks: none exists.** Measured:

| Candidate | Fly | GH Actions | k8s | `.env` | Drift detection |
|---|---|---|---|---|---|
| teller | No | No | No | Yes | No; stalled since 2024 |
| ESO PushSecret | No | **write-only** | Yes | No | **No** |
| Infisical Secret Syncs | Not found | Yes | Not found | No | **No** — syncs overwrite |
| Doppler | **Yes, native** | Yes | Yes | Yes | Closed-source SaaS — fails our portability rule |
| SecretSpec | **Yes, `fly://`** | Read at runtime only | No | Yes | No, but has `check` and `audit` |

ESO's confirmed PushSecret targets are Akeyless, AWS SM, AWS Parameter Store, Azure Key Vault,
GCP SM, Vault, Kubernetes, Oracle Vault, OVHcloud, Scaleway and SecretServer. **No Fly. No age.**

**And full drift detection is architecturally impossible on two of our four sinks.** GitHub
Actions secrets are write-only — `GET /repos/{owner}/{repo}/actions/secrets` returns names and
`updated_at`, never values. Fly secrets are write-only too — `fly secrets list` shows a name, a
digest and deployment status, and "the actual value of the secret is only available to the
application". Whether that digest is reproducible locally is **unverifiable**; Fly does not
document the algorithm.

So the honest design is a ~150–200 line script, in three tiers rather than one:

1. **Name-set reconciliation on all four sinks.** This alone catches our real defect today: 11
   declared names against 5 in GitHub with zero overlap.
2. **Digest comparison where a digest exists** — Fly, and Kubernetes (whose Secrets are
   readable, so hash the value).
3. **Timestamp staleness where nothing else is possible** — a GitHub `updated_at` older than the
   age file's last commit means that sink is behind.

That is smaller than adopting any tool in the table, and it is the only approach that does not
fail outright on the write-only sinks.

**Q4 — writing GitHub Actions secrets from a script: fully supported.** `GET .../secrets/public-key`,
then a libsodium sealed box against that key, base64, then `PUT .../secrets/{name}` with
`{"encrypted_value", "key_id"}`. **But do not write it:** `gh secret set NAME` does the whole
dance, and `gh secret set -f .env` does a whole file in one call.

### 3.5 Security of what we already do

**Committing age ciphertext to git is accepted practice, not a finding.** It is the design
intent — the SOPS security page lists what it does not protect against (compromised cloud
credentials, mishandled PGP keys, weak RSA keys, a theoretical AES break) and "ciphertext in a
repo" is not among them; it defends the pattern precisely so diffs stay meaningful.

The conditions attached to it are where we fail:

1. The private key must be strong and well-held. age is fine; **one copy on one laptop with no
   restore path is the finding** — not the commit.
2. **Rotation must be real, and git history is immutable.** Rotating a Stripe key does not
   remove its old ciphertext from history. If the age key ever leaks, every historical value in
   the repo is exposed at once, retroactively. That is the true cost of this pattern and the
   strongest reason to hold the key better.
3. If the repo ever becomes public the ciphertext is permanently harvested — and GitHub secret
   scanning and Stripe's key-leak detection will **not** fire, because there is no plaintext to
   match. A leak here gets none of the automatic protection a plaintext commit would.
4. There is no read audit and no revocation. Nothing in age's design offers either.

**Post-quantum: solved, not pending, and cheap enough to just take.** age uses X25519, which
falls to Shor's algorithm — and harvest-now-decrypt-later is a real category for anything in an
immutable, permanently-readable place, which is exactly what git history is. **age v1.3.0
(2025-12-27) shipped native hybrid post-quantum recipients** (HPKE with an ML-KEM-768 KEM,
`age-keygen -pq`, recipients `age1pq1…`). We are on **v1.3.1**, so we already have it. It is
hybrid, so it is no weaker than X25519 even if ML-KEM is later broken.

Blunt verdict: for 11 secrets rotated every 6–12 months the practical risk is near zero — a
harvested 2026 Stripe key is worthless by 2032. But it costs one flag on a re-encrypt we must do
anyway. Take it. **One caveat:** a PQ stanza is only readable by age ≥1.3.0 (and sops ≥3.12.1),
so keep a classic X25519 recipient alongside it until every consumer is upgraded — and every
deploy target counts as a consumer.

### 3.6 RECOMMENDATION — stay on `age`, harden the key, and fix what strips recipients

**Shortlist of three, strongest argument for each:**

1. **Stay on plain `age`, hardened to four recipients.** It is the only candidate whose answer to
   3.1 is *"nothing must be running"* — and that property IS the eleven-line portability
   contract. Every other option makes at least one of laptop, Fly, ssh+docker and k8s a special
   case: Sealed Secrets and ESO do not exist off a cluster, OpenBao means a second stateful
   service on all four, and Doppler/1Password/Bitwarden put a vendor account on the critical
   path of a cold boot. Nothing else in the table is true on all four counts.
2. **OpenBao, if and only if a read audit becomes a requirement.** It is the only genuinely
   open-source (MPL-2.0) option giving audit devices for reads and automatic short-lived
   dynamic credentials, under Linux Foundation governance rather than a vendor licence — which
   is the whole reason to prefer it to Vault, BUSL-1.1 since 2023 and now an IBM product.
3. **SecretSpec as a thin layer over age — not a replacement.** The only tool measured with both
   an age provider and a `fly://` provider, plus `check` and a local `audit` log, and no daemon.
   It could retire the hand-maintained `.env` sink while age stays the source of truth.

**The strongest argument AGAINST my own pick, stated as strongly as I can put it:** age gives no
read audit and no revocation, and our ciphertext is immutable in git. If the key leaks, the
attacker gets every value at every point in history — including Stripe live keys rotated a year
ago — we cannot tell that it happened because nothing logs a decrypt, and we cannot contain it
because a cloned commit cannot be unpublished. The only response is to rotate all 11 at source
and accept the historical set is gone. OpenBao turns that into a bounded, logged, revocable
event. Adding recipients does not fix this; it makes the key MORE available, which is the right
trade for a one-founder shop but genuinely the wrong direction on this axis.

The counterweight, and why the pick stands: an OpenBao we run has its own unseal material with
its own single-point-of-failure problem, and we would still need an age file to bootstrap it on
a cold Fly machine. We would hold two systems instead of one.

### 3.7 A blocker nobody would have found without reading the script

`deploy/secrets.sh:62-68` re-encrypts to **one** recipient, derived from our own private key:

```sh
encrypt_stdin() {
  pub="$(age-keygen -y "$KEY")"
  age -r "$pub" -o "$STORE.tmp"
}
```

So adding recipients by hand today would be **silently undone by the next `secrets.sh set`**.
The recovery fix is not durable until the recipient list lives in a file the script reads. That
is action S5 below, and it must land BEFORE S1, or S1 is decorative.

### 3.8 The commands, in order, in plain `age`

Not `sops` — see 3.0. Run on the laptop that holds the key.

1. Prove the current key still decrypts, before changing anything:
   `age -d -i ~/.config/prospector/age-key.txt deploy/secrets.env.age | head -1`
2. Back up the ciphertext and the key outside git, so a mistake is reversible.
3. Break-glass identity: `age-keygen -o /tmp/breakglass.txt`, record the public key, PRINT the
   file, verify the printout is legible, then `rm -P /tmp/breakglass.txt`.
4. Second machine identity: `age-keygen -o ~/.config/prospector/age-key-2.txt`, move it to the
   second machine, `chmod 600` there, delete the local copy.
5. Post-quantum identity: `age-keygen -pq -o ~/.config/prospector/age-key-pq.txt`.
6. Write all four public keys to `deploy/secrets.recipients`, one per line, each with a comment
   naming the machine or safe that holds it. An unlabelled `age1…` in six months is a key nobody
   dares remove.
7. Re-wrap: `age -d -i <current key> old.age | age -R deploy/secrets.recipients -o new.age`
8. Verify EACH identity independently, including typing the printed break-glass key back in
   once. **A break-glass key you have never tested is not a break-glass key.**
9. Only then delete the backups from step 2.

## Part 4 — Traps found on the way

- **`deploy/targets/k8s.sh` exists only on `integrate/2026-08-20-final`**, not on `main`. An
  audit run from the wrong branch reports "no Kubernetes target" as a fact about the estate. It
  is a fact about the branch. Check the branch before believing an absence.

- **`secrets.sh set KEY VALUE` put the value in argv, and that is a leak that outlives the
  terminal.** Surfaced 2026-08-20 by the founder running the script's own usage line. `ps` shows
  argv to every process on the box, and an interactive shell appends argv to its history file, so
  a live Stripe key typed once sits in `~/.zsh_history` afterwards. FIXED the same day: the value
  is now read from stdin when only a KEY is given (`deploy/secrets.sh` `cmd_set`), and
  `tests/unit/test_secrets_set_reads_stdin.py` fails if the usage line stops offering the stdin
  form. The positional form still works — breaking it would send people back to editing the
  plaintext by hand, which is worse.

- **`secrets.sh check` compares NAMES, not values.** It proves every required key is PRESENT in
  a sink. It cannot see a sink holding a stale or different value for a name that is present in
  both, which is the failure that actually happens after a rotation. This is the detect half of
  2.6 and it is missing. Tracked as S4.

- **Two shell traps in reading a value from stdin, both measured rather than reasoned.** `read`
  returns non-zero at EOF even when it filled the variable — which is exactly what
  `printf %s` with no trailing newline produces — so the emptiness test must read the VALUE, not
  the exit status. And under `set -e` that same non-zero return kills the script before any check
  can run, printing nothing at all. `v=""; IFS= read -r v || true` then testing `[ -n "$v" ]` is
  the form that handles all four cases. Three iterations were spent finding this.

## Part 4b — A FIFTH SINK, added 2026-08-24: a mounted directory of files

Kubernetes forced a shape the other three sinks never did, and it is a better one.

`deploy/k8s/policies` includes the upstream `secrets-not-from-env-vars`, which refuses
`envFrom.secretRef` and `env[].valueFrom.secretKeyRef` outright. Measured 2026-08-24, it was one of
ten policies that refused the Deployment `deploy/targets/k8s.sh` writes inline (`pass: 19, fail:
10`). So on Kubernetes a secret cannot reach the engine as an environment variable declared in the
pod spec, where it would sit in etcd and in `kubectl describe pod`. It arrives as a directory of
files, one file per name, mounted read-only.

**The writer side already existed and needed no change.** `deploy/targets/k8s.sh:115` builds the
Secret with `kubectl create secret generic prospector-engine-env --from-env-file`, which is one key
per variable, which mounts as one file per variable. `--from-env-file` takes a path, so no value is
ever an argument — the same rule as `deploy/runners.sh`, and it is why nothing had to be rewritten.

**The reader side was missing and is now `prospector/file_secrets.py`.** It copies every file in
`$PROSPECTOR_SECRETS_DIR` into `os.environ`, called from `prospector/__init__.py` so it runs before
any module in the package. Measured 2026-08-24: 30 files read a credential from `os.environ`
directly — `prospector/retrieval.py`, `prospector/operator.py`, `prospector/bridge.py`,
`prospector/api.py`, `prospector/scheduler/telegram_sender.py` and 25 more — and several read it at
module scope. A resolver only `config.py` called would have fixed none of them.

Three decisions in it worth keeping:

- **The file wins over an environment variable of the same name.** Both can be set on a laptop that
  has a `.env` and a mount. The file is what the cluster deployed and what a rotation updates;
  preferring the environment would mean a rotated secret silently does not take effect, which is
  2.5's missing rotation story failing in the least visible way possible.
- **A partial set refuses to start.** Missing mount, empty mount, unreadable file, or a name no
  shell could read: all raise, at import. That is 2.4's "bootstrap has no second chance" applied
  where it can still be cheap — a container that will not start, rather than "All operators
  unavailable - check API keys" three hours later in another subsystem.
- **No value reaches an exception message**, and the `UnicodeDecodeError` is deliberately not
  chained, because its own message prints the offending bytes.

Proof: `tests/test_incident_secrets_mounted_as_files.py`, 12 cases including the Kubernetes
symlink-farm layout (`..data` plus per-key symlinks) and a subprocess that asks a real Python
process what it can read.

**This does not close S3 or S4.** It adds a sink; the read-audit and drift-detection gaps in 2.5
and 2.6 are unchanged.

## Part 5 — Open actions

| # | Action | Owner | Blocking |
|---|---|---|---|
| S1 | Escrow the age identity in the password manager AND print it | **founder** — it is a secret value and a physical act | R1, R8, and every recovery drill |
| S2 | Rotate `PROSPECTOR_ENTITLEMENTS_API_KEY` and `STORE_INTERNAL_API_KEY`, exposed 2026-08-18 | **founder** | — |
| S3 | Bring the 5 CI credentials under a declared source of truth | agent, after Part 3 lands | consolidation |
| S4 | Make `secrets.sh check` detect a value that DIFFERS between sinks, not only one that is absent | agent, after Part 3 lands | the detect half of 2.6 |
| S5 | Recipient list in `deploy/secrets.recipients`, read by `encrypt_stdin`, so a recipient survives re-encryption (3.7 named this action but this table never held its row) | agent — landed 2026-08-24 | S1 — without it, S1's escrow recipient is stripped by the next `set` |
