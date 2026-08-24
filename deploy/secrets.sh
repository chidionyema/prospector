#!/usr/bin/env bash
# One encrypted file holds every secret the stack needs, and every target reads that same file.
#
# WHY. Moving the stack to another provider currently means finding the secrets again. They live
# in a `.env` on the laptop, in `fly secrets` on Fly, and nowhere at all on a box we have not
# rented yet. Three copies with no single source is how a migration ends with a machine that runs
# and cannot authenticate — which is exactly what happened on 2026-08-17, when the production
# checkout moved and every MiniMax tier died with "All operators unavailable - check API keys",
# because the key file was simply not there.
#
# WHY age AND NOT sops. `age` is already installed and already used in this estate
# (~/.hermes/secrets.age, ~/.hermes/scripts/secrets_manager.py). sops is not installed. A new
# dependency needs a reason the existing one cannot serve, and there isn't one here: we encrypt a
# whole file, not selected YAML fields.
#
# WHAT IS AND IS NOT IN HERE. Secrets only. Domain names are NOT secret and belong in
# deploy/compose/stack.env, where the compose file and the image builds can read them without a
# key. Putting a hostname in here would mean needing the private key to find out what the site is
# called.
#
# THE KEY NEVER ENTERS THE REPO. It lives at ~/.config/prospector/age-key.txt, mode 600.
#
# AND NEITHER DOES THE ENCRYPTED FILE. This header said the opposite until 2026-08-23 - that
# deploy/secrets.env.age "IS committed, that is the point, it is useless without the key". That
# is correct reasoning about a PRIVATE repository and wrong about this one. `gh repo view`
# reports chidionyema/prospector as PUBLIC. Committing the store would publish the Stripe live
# keys, the R2 keys, the Fly token and every model provider key to the open internet, where
# clones and caches keep them after any deletion, leaving one X25519 key on one laptop as the
# only thing between a stranger and the money. age is strong today and the ciphertext would be
# public forever, which is the half that cannot be undone. .gitignore now refuses it.
#
# So the second copy goes somewhere private instead: the `secret-store` source in
# ops/config/offsite_backup.yaml puts it in the R2 backup bucket on every offsite run.
#
# Losing the key means re-minting every credential, so back it up somewhere that is not this
# laptop, which is the same reason this whole programme exists. Back up the R2 read credentials
# in the SAME place while you are there: they live inside this store, so a laptop loss with only
# the key recovered leaves you holding a key and no way to reach the file it opens.
#
#   bash deploy/secrets.sh init                 # make the keypair, once per machine
#   printf %s "$VALUE" | bash deploy/secrets.sh set KEY   # add or change one secret
#   bash deploy/secrets.sh set KEY value                 # same, but the value lands in argv
#   bash deploy/secrets.sh list                 # key NAMES only, never values
#   bash deploy/secrets.sh import path/to/.env  # take a whole existing .env in one go
#   bash deploy/secrets.sh push fly             # decrypt and hand to that target's t_secrets
#   bash deploy/secrets.sh check                # every key in secrets.required is present
#
# `push` writes the plaintext to a file mode 600 under $TMPDIR, hands it to the adapter, and
# deletes it on any exit path including a failure - the trap is set before the file is written.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STORE="${PROSPECTOR_SECRETS_FILE:-$HERE/secrets.env.age}"
KEY="${PROSPECTOR_AGE_KEY:-$HOME/.config/prospector/age-key.txt}"
REQUIRED="$HERE/secrets.required"
RECIPIENTS="${PROSPECTOR_AGE_RECIPIENTS:-$HERE/secrets.recipients}"

die() { echo "$*" >&2; exit 1; }

need_age() {
  command -v age >/dev/null || die "age is not installed: brew install age"
}

need_key() {
  [ -f "$KEY" ] || die "no key at $KEY - run: bash deploy/secrets.sh init"
}

# Decrypt to stdout. Every reader goes through this, so there is one place that knows the format.
plaintext() {
  need_age; need_key
  [ -f "$STORE" ] || die "no encrypted secrets at $STORE - run: bash deploy/secrets.sh import <file>"
  age -d -i "$KEY" "$STORE"
}

# Encrypt stdin to the store. When deploy/secrets.recipients exists, every public key listed
# there can decrypt, and the list survives re-encryption — before this, every `set` re-encrypted
# to our own key alone, so a recovery recipient added by hand was silently stripped by the next
# write (SECRETS_PROGRAM.md 3.7). A recipients file that omits our own public key is refused:
# honouring it would make this the last `set` this machine can ever read back.
encrypt_stdin() {
  need_age; need_key
  local pub
  pub="$(age-keygen -y "$KEY")"
  if [ -f "$RECIPIENTS" ]; then
    # Strip CR and trailing whitespace before the membership test: age's own parser accepts a
    # CRLF recipients file, and an exact-line grep would refuse it with a wrong diagnosis
    # ("add the line" when the line is already there).
    sed 's/[[:space:]]*$//' "$RECIPIENTS" | grep -qxF "$pub" \
      || die "our own public key is not in $RECIPIENTS - encrypting would lock this machine out of its own store; add the line: $pub"
    age -R "$RECIPIENTS" -o "$STORE.tmp"
  else
    age -r "$pub" -o "$STORE.tmp"
  fi
  mv "$STORE.tmp" "$STORE"
}

cmd_init() {
  need_age
  if [ -f "$KEY" ]; then
    echo "key already exists at $KEY (public: $(age-keygen -y "$KEY"))"
    return 0
  fi
  mkdir -p "$(dirname "$KEY")"
  age-keygen -o "$KEY" 2>/dev/null
  chmod 600 "$KEY"
  echo "made $KEY (public: $(age-keygen -y "$KEY"))"
  echo "back this file up somewhere that is not this machine. Without it the store cannot be read."
}

cmd_set() {
  local k="${1:?usage: set KEY [VALUE]  -- omit VALUE and it is read from stdin}" v
  if [ "$#" -ge 2 ]; then
    v="$2"
  else
    # Read the value from stdin so it never reaches argv. Two reasons, both measured rather
    # than theoretical: `ps` shows argv to every process on the box, and an interactive shell
    # appends argv to its history file. A live Stripe key sitting in ~/.zsh_history is a leak
    # that outlives the terminal it was typed in. The positional form still works, because
    # breaking it would send people back to editing the plaintext by hand, which is worse.
    # Two traps in one line. `read` returns non-zero at EOF even when it filled the
    # variable, which is exactly what `printf %s` with no trailing newline produces -- so
    # test the VALUE, not the exit status. And this script runs under `set -e`, which kills
    # it on that same non-zero return before any check can run, printing nothing at all.
    # `|| true` is what keeps the EOF case alive long enough to be judged.
    v=""
    IFS= read -r v || true
    [ -n "$v" ] || die "no value on stdin for $k -- pipe one in, or pass it as an argument"
  fi
  local current=""
  [ -f "$STORE" ] && current="$(plaintext)"
  # Drop any existing line for this key, then append the new one. grep -v with an anchored
  # pattern, so KEY=... never matches OTHER_KEY=... .
  { printf '%s\n' "$current" | grep -v "^${k}=" || true; printf '%s=%s\n' "$k" "$v"; } \
    | grep -v '^$' | sort | encrypt_stdin
  echo "set $k"
}

cmd_list() {
  plaintext | grep -o '^[A-Za-z_][A-Za-z0-9_]*=' | tr -d '=' | sort
}

cmd_import() {
  local f="${1:?usage: import <file>}"
  [ -f "$f" ] || die "no such file: $f"
  # Keep only real KEY=VALUE lines. Comments and blanks are dropped rather than encrypted, so
  # `list` never shows something that is not a key.
  grep -E '^[A-Za-z_][A-Za-z0-9_]*=' "$f" | sort | encrypt_stdin
  echo "imported $(cmd_list | wc -l | tr -d ' ') keys from $f"
}

cmd_push() {
  local target="${1:?usage: push <target>}"
  local adapter="$HERE/targets/${target}.sh"
  [ -f "$adapter" ] || die "no adapter at $adapter"
  local tmp
  tmp="$(mktemp "${TMPDIR:-/tmp}/prospector-secrets.XXXXXX")"
  # Set BEFORE anything is written, so an interrupt between mktemp and the write still cleans up.
  trap 'rm -f "$tmp"' EXIT INT TERM
  chmod 600 "$tmp"
  plaintext > "$tmp"
  # shellcheck disable=SC1090
  source "$adapter"
  t_secrets "$tmp"
  echo "pushed $(grep -c '=' "$tmp") secrets to $(t_name)"
}

cmd_check() {
  [ -f "$REQUIRED" ] || die "no $REQUIRED to check against"
  local have missing=0
  have="$(cmd_list)"
  while read -r k; do
    case "$k" in ''|'#'*) continue ;; esac
    printf '%s\n' "$have" | grep -qx "$k" || { echo "MISSING $k"; missing=1; }
  done < "$REQUIRED"
  [ "$missing" = 0 ] && echo "every required secret is present" || die "the store is incomplete"
}

case "${1:-}" in
  init)   shift; cmd_init "$@" ;;
  set)    shift; cmd_set "$@" ;;
  list)   shift; cmd_list ;;
  import) shift; cmd_import "$@" ;;
  push)   shift; cmd_push "$@" ;;
  check)  shift; cmd_check ;;
  *) die "usage: $(basename "$0") {init|set KEY [VALUE]|list|import <file>|push <target>|check}
  set reads VALUE from stdin when you omit it, which keeps it out of argv and shell history" ;;
esac
