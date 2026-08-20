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

## Part 5 — Open actions

| # | Action | Owner | Blocking |
|---|---|---|---|
| S1 | Escrow the age identity in the password manager AND print it | **founder** — it is a secret value and a physical act | R1, R8, and every recovery drill |
| S2 | Rotate `PROSPECTOR_ENTITLEMENTS_API_KEY` and `STORE_INTERNAL_API_KEY`, exposed 2026-08-18 | **founder** | — |
| S3 | Bring the 5 CI credentials under a declared source of truth | agent, after Part 3 lands | consolidation |
| S4 | Make `secrets.sh check` detect a value that DIFFERS between sinks, not only one that is absent | agent, after Part 3 lands | the detect half of 2.6 |
| S5 | Fix `encrypt_stdin` (`deploy/secrets.sh:62-68`) to encrypt to a recipients FILE, not to one key derived from the local identity | agent | must land BEFORE S1, or the next `set` silently strips every recovery recipient |
| S6 | ~~Escrow the signing key outside a code tree~~ DONE 2026-08-20, `~/.prospector/escrow/`. What remains: get a copy OFF this machine | **founder** — it means a secret value leaving the laptop | every recovery drill; the estate is one delete from an unrecoverable gate |
| S7 | Package `popdd` so a fresh clone can run the commit gate (R-K3) | agent, needs an owner | the portability contract and every migration target |
| S8 | Name ONE owner for the stale-`CLAUDE.md`-from-no-ref guard (R-K5) | **founder** — founder ruled 2026-08-20 that one person builds it | three sessions hit it the same day |

---

## Part 6 — SECURITY AND BUSINESS RISK REGISTER (opened 2026-08-20)

This part exists because of a specific failure of this programme, not as a formality. Parts 1-5
graded the secrets we knew we had: the age file, the CI credentials, the provider keys. The
estate's single worst secret was not in any of them, and neither was it in the daily stack audit.
It was found by a peer session on its way to doing something else, roughly one command away from
being destroyed permanently.

Risk is rated on what it costs the BUSINESS if it fires, and on whether it can be undone.

| # | Risk | Fires when | Business cost | Undo | Status |
|---|---|---|---|---|---|
| R-K1 | **One signing key, gitignored, and until 2026-08-20 every copy of it was inside a code tree.** Measured by `scripts/process_audit.py`, search completed, no unfinished roots: **78 `agent.pem` files, 23 distinct keys, and exactly ONE of the 23 verifies the tracked seed receipts** (file sha `c0de7d01f49c`, verifier id `f12fbf94ba535a51`). That one has **42 copies** — 38 under `~/Documents/code`, 37 in the iCloud clone, 2 in `.claude/worktrees`, 1 in `~/.lux`. | a sweep that reaches **both clones**, or the laptop is lost. Not a single `rm -rf`, and not one clone: 42 copies across two clones defeat either | no worktree in the estate can pass its own commit gate again; every session is blocked from committing at once | escrow now exists, see R-K2. `.gitignore:92` still keeps it out of git and the signer is HMAC, so it cannot be re-derived | PARTLY CLOSED — one copy is outside every code tree; off-machine escrow is still open |
| R-K2 | **Escrow: on-machine done, off-machine not.** A copy now sits at `~/.prospector/escrow/agent.pem`, mode 400, outside every code tree, with a README beside it giving the restore command. Verified by command that `~/.claude/scripts/estate_cleanup.py` enumerates trees only via `git worktree list` and never builds a path under `~/.prospector`, so a sweep cannot reach it. | the laptop is lost, stolen or wiped — the escrow is on the same disk as everything it protects | no recovery on new hardware; the estate cannot sign again | copy it back: `cp ~/.prospector/escrow/agent.pem <tree>/.lux/keys/agent.pem` | HALF OPEN — the sweep case is closed, the hardware case is S6 and needs the founder, because it means the key leaving this machine |
| R-K3 | **The gate's library is outside the repo.** `popdd.agent` resolves to `/Users/chidionyema/Documents/code/popdd-py/`. | a fresh clone is made anywhere — a new machine, a hosted runner, a migration target | the commit gate cannot run at all, so the migration target cannot prove its own work | reversible, but it is a packaging job | OPEN — S7. Breaks the one surviving clause of the old "no hosted service" rule: *a fresh clone plus an env file must still be able to run the whole engine* |
| R-K4 | **Auto-created keys hide the failure.** `HmacSigner.load_or_create_key` (`/Users/chidionyema/Documents/code/popdd-py/popdd/agent.py:68` — an absolute path because the module is not in this repo at all; that is R-K3) silently mints a key when a worktree has none. 22 of the 23 distinct keys are these. | any worktree made without `setup_worktree.sh` | the tree's gate is dead from birth and reports `Chain valid: False` while every lane passes, so the agent debugs their own diff instead | reversible per tree | OPEN — devops owner by founder ruling; do not start it |
| R-K5 | **A worktree can lose its git registration and keep serving rules.** `wt-storeroot` returns `fatal: not a git repository` for every command while its `CLAUDE.md` is still injected as project instructions from no ref — measured 361 lines adrift, carrying a rule that is false on main. | `git worktree prune` runs in a clone that cannot resolve a tree | agents work from rules nothing owns and cannot commit; time lost debugging phantom failures | files survive; registration does not | OPEN — one owner to be named; see the note under S8 |

### 6.1 What the audit missed, and why that is the real finding

`scripts/process_audit.py` runs daily and grades production, CI runners, deploys, launchd jobs,
workflows, enforcement, specialist probes and worktree drift. On the morning of 2026-08-20 it
graded all of them and reported nothing about any risk in the table above.

Every collector in it asked the same shape of question: **is this thing running.** Not one asked
**if this were deleted right now, could we get it back.** A key that is present and working scores
identically to a key that is present, working, and irreplaceable — right up to the moment it is
gone, at which point the audit has nothing to say either.

The class: **an audit of liveness reads as an audit of safety.** Both produce a clean report on a
healthy day, and they diverge only on the day that matters.

Closed mechanically, not with this document: `grade_recoverability()` in `scripts/process_audit.py`
is a new collector that asks only the recovery question, and `tests/unit/test_the_stack_audit_grades_recoverability.py`
fails if it stops asking. Measured on this estate the day it was written: 4 BAD rows, 62 seconds.

**The counts are a floor, and the doc is not the source of truth.** They come from a pruned `find` over three roots, so any tree it could not finish is missing from them. Re-measure with `scripts/process_audit.py`, whose `recoverability` section runs the same search and grades it; if this table and the probe disagree, the probe is right and this table is stale.

**Restoring from escrow is a human action, not an agent one.** A peer session ran the documented `cp` line to repair its own worktree and its classifier refused it — correctly, since copying a private key is exactly the class of thing an agent should not do unasked. So the escrow is recoverable BY THE FOUNDER OR THE DEVOPS ENGINEER, and a session that finds itself with a dead gate cannot self-heal. Do not write runbooks that assume it can.

### 6.2 Two traps inside the probe itself, both already paid for

**An unfinished search is not an empty one.** The first version used a plain `find` over both code
roots. Both hit a 25-second timeout and returned zero keys — and zero keys is the loudest alarm the
collector has, so it would have reported "this Mac cannot sign at all" every day, on an estate
holding 78 key files. Pruning `node_modules`, `.venv`, `.next`, `dist` and `.git` brings the same
search to 26s and 35s, and a root that still cannot finish is now reported as a separate WARN that
says every count below it is a floor.

**Two identifiers for one key, one of them fictional.** `9372897386a5` was broadcast between two
sessions as the working key's hash and passed on as measured. It reproduces as nothing — not the
file bytes, not the stripped text, not the decoded secret — and its author retracted it. The
correct pair is the file digest `c0de7d01f49c` and the derived `verifier_id` `f12fbf94ba535a51`
(`/Users/chidionyema/Documents/code/popdd-py/popdd/receipt.py:123-125`). The probe uses the file digest deliberately: the other one requires
decoding a private key, and a daily audit has no business doing that.
