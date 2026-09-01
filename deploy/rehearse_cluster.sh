#!/usr/bin/env bash
# A real Kubernetes cluster on this laptop, in about two minutes, for free -- and the drill that
# proves the estate's k8s adapter and its standards actually work before anyone rents a node.
#
#   deploy/rehearse_cluster.sh            # cluster, policies, adapter, self-healing, all of it
#   deploy/rehearse_cluster.sh up         # just the cluster
#   deploy/rehearse_cluster.sh policy     # prove every standard refuses AND permits
#   deploy/rehearse_cluster.sh adapter    # run deploy/targets/k8s.sh against it for real
#   deploy/rehearse_cluster.sh heal       # kill things and TIME the recovery
#   deploy/rehearse_cluster.sh down       # destroy it
#
# WHY THIS EXISTS. deploy/targets/k8s.sh has been in this repository since 2026-08-20 and has never
# once been run against a cluster. It reads well -- it carries the money fence at line 48, Recreate
# at line 133, byte-count-verified copies at line 218 -- and none of that is evidence. An adapter
# nobody has executed is a design document with a shebang. This is the same gap deploy/rehearse_box.sh
# closed for the compose path, and it closed it by finding a real defect on its first run.
#
# It is k3d, which is k3s in a container, and that is deliberate rather than convenient. The decision
# recorded in the research ledger on 2026-08-24 is k3s on a rented Linux box, so the drill runs the
# distribution the estate would actually buy. kind would give vanilla upstream Kubernetes and prove
# something slightly different from what would be running.
#
# WHAT IT CANNOT PROVE, said plainly so a green run is not read for more than it carries: multi-node
# scheduling, a real cloud's storage class, network latency, a Let's Encrypt issuance, and live
# Stripe. Those need money and a real node. Everything before them is proved here.

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

CLUSTER="${REHEARSAL_CLUSTER_NAME:-prospector-rehearsal}"
CTX="k3d-$CLUSTER"
CACHE="${REHEARSAL_CACHE:-$HOME/.cache/prospector-k8s-rehearsal}"
NS="${PROSPECTOR_K8S_NAMESPACE:-prospector}"
KYVERNO_VERSION="${KYVERNO_VERSION:-v1.16.1}"

say()  { printf '\n== %s\n' "$*"; }
ok()   { printf '   ok  %s\n' "$*"; }
note() { printf '   -   %s\n' "$*"; }
# A failure that does not stop the run. `fail` exits; `bad` records and lets the caller return
# non-zero, so one broken control does not hide the eleven that were about to be tested.
bad()  { printf '   BAD %s\n' "$*"; }
fail() { printf '!! %s\n' "$*" >&2; exit 1; }

# CAN THE DAEMON ACTUALLY START A CONTAINER? `docker info` cannot answer that question.
#
# THE INCIDENT, 2026-08-24. cmd_up's only daemon check was `docker info >/dev/null || fail`. It
# passed. `docker ps`, `docker version` and `docker context ls` all passed too. Meanwhile a no-op
# container -- `docker run --rm alpine echo ok` -- did not return in 90 seconds, `docker stop`
# reported "tried to kill container, but did not receive an exit event", and `docker rm -f` removed
# nothing. The containerd shim in the colima VM was wedged while every status command answered
# normally.
#
# What that cost: this script ran anyway, got far enough to create the k3d containers and not far
# enough to write the serverlb's confd config, and left a half-built cluster whose load balancer
# crash-looped 19 times on `stat /etc/confd/values.yaml: no such file or directory`. The wreckage
# then sat on the machine holding CPU. The half-cluster looked like a k3d bug and was not one.
#
# THE CLASS, not the instance: a preflight that asks an instrument for a STATUS instead of asking
# the system to DO THE WORK. `docker info` reports a shape. Starting a container is the work. This
# is the same family docs/CI_DEBUG_RUNBOOK.md is written about, and the rule there is the rule here.
#
# DAEMON_PROBE exists so this check can be proved BOTH ways without needing a broken daemon to hand
# (LAW 38: a guard only ever seen refusing has never been shown to permit):
#   DAEMON_PROBE=/usr/bin/true  ./rehearse_cluster.sh up   # must get past this line
#   DAEMON_PROBE=/usr/bin/false ./rehearse_cluster.sh up   # must stop on this line
# Unset, it runs the real thing. alpine is 3MB and pulling it also proves the daemon can pull, which
# cluster creation needs a few lines later anyway.
DAEMON_PROBE="${DAEMON_PROBE:-docker run --rm alpine:latest true}"

daemon_can_start_a_container() {
  timeout "${DAEMON_PROBE_TIMEOUT:-60}" $DAEMON_PROBE >/dev/null 2>&1
}

# HAS THE MACHINE GOT THE CAPACITY TO FINISH WHAT THIS SCRIPT IS ABOUT TO START?
#
# THE SECOND INCIDENT, 2026-08-24, an hour after the first. The guard above was in place and it
# PASSED -- the daemon started a container in under a second, correctly. The boot then ran for 20
# minutes and got nowhere. Measured while it was stuck:
#
#   CPU utilisation      98% busy, 1% idle over a 5s sample of /proc/stat, on 4 vCPUs
#   CPU pressure         /proc/pressure/cpu some avg10=91.85
#   IO pressure          some avg10=0.71     memory pressure  some avg10=0.00
#   k3s server's share   28% of the whole machine
#   kine SQL             a single indexed SELECT taking 1.7-1.9s; it is milliseconds when idle
#   k3s uptime           1205s without ever writing its own /etc/rancher/k3s/k3s.yaml
#
# The apiserver could not answer its OWN client inside the client's timeout, so k3s never finished
# bootstrapping, k3d never got a kubeconfig, and the serverlb never got its confd config. The
# wreckage is byte-identical to the wreckage the wedged daemon produced, which is the trap: the
# same symptom, a completely different cause, and the guard above says the runtime is fine because
# the runtime IS fine.
#
# THE CLASS, which is one step out from the class above: a preflight that proves a dependency
# RESPONDS but not that the machine has the CAPACITY to complete the work it is about to begin.
# Responding is cheap. Bootstrapping a control plane is not. A one-second container start is not
# evidence about a twenty-minute job, and treating it as evidence is how this script burned twenty
# minutes and left a half-built cluster for the second time in one afternoon.
#
# THE FLOOR IS A JUDGEMENT, AND IT IS LABELLED AS ONE. It is anchored on exactly one measured
# failure -- 1% idle did not boot -- and there is no measured success yet to bound it from the
# other side, so 10% is chosen to refuse only the case that is already known to fail. When a boot
# does succeed, put its idle figure in this comment and re-derive the floor from two points instead
# of one. Do not raise it on a hunch: LAW 38, a guard that refuses correct work is an outage.
#
# CAPACITY_PROBE is the seam that lets this be proved both ways with no need to saturate a laptop:
#   CAPACITY_PROBE='echo 90' ./rehearse_cluster.sh up   # must get past this line
#   CAPACITY_PROBE='echo 1'  ./rehearse_cluster.sh up   # must stop on this line
#   CAPACITY_PROBE='echo x'  ./rehearse_cluster.sh up   # unreadable => BLIND, proceeds, says so
#
# It measures inside a container on purpose: /proc/stat is not namespaced, so the container reads
# the kernel that will actually run k3s -- the colima VM here, the LinuxKit VM under Docker Desktop,
# the host itself on native Linux. Reading the Mac's own load would answer about the wrong machine,
# which is the mistake made earlier today when a listener started on the Mac was unreachable from a
# container because the container's gateway is the bridge inside the VM.
CAPACITY_PROBE="${CAPACITY_PROBE:-}"

measure_idle_pct() {
  if [ -n "$CAPACITY_PROBE" ]; then $CAPACITY_PROBE; return; fi
  local out rc
  out="$(timeout "${CAPACITY_PROBE_TIMEOUT:-45}" docker run --rm alpine:latest sh -c '
    read_stat() { awk "/^cpu /{print \$2+\$3+\$4+\$6+\$7+\$8, \$5}" /proc/stat; }
    set -- $(read_stat); b=$1; i=$2
    sleep 4
    set -- $(read_stat); B=$1; I=$2
    db=$((B-b)); di=$((I-i)); t=$((db+di))
    if [ "$t" -gt 0 ]; then echo $((di * 100 / t)); else echo unreadable; fi
  ' 2>/dev/null)"; rc=$?

  # A PROBE THAT TIMED OUT IS NOT AN UNREADABLE PROBE. It is the loudest capacity reading available,
  # and conflating the two is how this guard would wave through the worst machine it will ever see.
  #
  # The work inside that container is `sleep 4` and two reads of /proc/stat. On a machine with
  # headroom it returns in a few seconds. Measured 2026-08-24, on this laptop with the compose stack
  # running: the sidecar did not return within the 45s budget at all, and `colima ssh -- head -1
  # /proc/loadavg` -- no container involved, just a shell in the VM -- also did not return in 90s.
  # Both came back EMPTY, which the numeric test below reads as "unreadable" and waves through BLIND.
  # That is exactly backwards: a box that cannot run `sleep 4` in 45 seconds cannot bootstrap a
  # control plane, and saying so needs no threshold.
  #
  # Both exit codes are accepted because both occur. GNU timeout returns 124; busybox timeout signals
  # SIGTERM and the shell reports 143. A check written for 124 alone silently misses the busybox case
  # -- three files in this estate key on 124 as the sentinel and are correct only because they run on
  # the Mac. 137 is the same event after a SIGKILL escalation.
  case "$rc" in
    124|137|143) echo "timeout"; return ;;
  esac
  printf '%s\n' "$out"
}

# What is eating the machine, so the refusal names the cause instead of only the symptom. A refusal
# that says "the machine is full" and nothing else sends the reader back to the same measuring this
# guard just did.
#
# It is `top -b -n 1`, not `ps -eo pcpu,comm --sort=-pcpu`, and that is not a style choice. alpine's
# ps is busybox, which has neither -eo nor --sort: the ps form printed "unrecognized option" to
# stderr, which 2>/dev/null then swallowed, and the refusal shipped with an EMPTY evidence section.
# Caught 2026-08-24 by reading the guard's own output instead of trusting that it had one, which is
# the whole of LAW 28. busybox top -b -n 1 needs no options and gives the CPU line, the load average
# and the consumers sorted, in one shot.
top_cpu_consumers() {
  # The fallback is chosen on the CONTENT, not on an exit status. Two reasons, both measured
  # 2026-08-24 on this line:
  #
  #   1. `docker run ... | head -10 || echo fallback` never runs the fallback. The `||` binds to the
  #      whole pipeline, and `head` exits 0 on empty input, so a sidecar that failed to start still
  #      reported success. Sampled three times in a row: the section came back EMPTY once and
  #      populated twice. An intermittently blank evidence block is worse than a stated failure,
  #      because it reads as "nothing is using the machine".
  #   2. The sidecar genuinely does fail sometimes here, and for the guard's own reason -- a machine
  #      with no CPU left is slow to start a container. So this must degrade to a sentence, never to
  #      whitespace (LAW 28: an instrument nobody can read is not an instrument).
  #
  # EVIDENCE_PROBE is a seam, for the same reason DAEMON_PROBE and CAPACITY_PROBE are. The failure
  # path here cannot be reached by stubbing a shell function called `docker`: `timeout` is an
  # external binary and execs the docker BINARY, so a function never gets a look in. Without this
  # seam the fallback branch is unprovable, and an unproven fallback is the branch that ships broken.
  local out
  if [ -n "${EVIDENCE_PROBE:-}" ]; then
    out="$($EVIDENCE_PROBE 2>/dev/null | head -10)"
  else
    out="$(timeout 30 docker run --rm --pid=host alpine:latest top -b -n 1 2>/dev/null | head -10)"
  fi
  if [ -n "$out" ]; then
    printf '%s\n' "$out"
  else
    echo "   (could not read the process table: the evidence sidecar did not start either, which is"
    echo "    itself consistent with the reading above)"
  fi
}

# The gate is its own function so it can be proved without building a cluster: source this file
# with a harmless argument, then call it. A guard that can only be exercised by running the
# twenty-minute job it protects will not be exercised.
capacity_gate() {
  local idle; idle="$(measure_idle_pct)"

  # The timeout branch refuses, and it is not covered by IDLE_FLOOR_PCT: there is no number to
  # compare, so a floor cannot express the override. IDLE_PROBE_TIMEOUT_IS_FATAL=0 is the deliberate
  # escape, separate because it is a different decision -- "I accept a machine measured below the
  # floor" and "I accept a machine too busy to be measured at all" are not the same acceptance.
  if [ "$idle" = "timeout" ]; then
    if [ "${IDLE_PROBE_TIMEOUT_IS_FATAL:-1}" = "0" ]; then
      note "CPU probe timed out; proceeding anyway because IDLE_PROBE_TIMEOUT_IS_FATAL=0 was set"
      return 0
    fi
    fail \
"the CPU probe did not finish in ${CAPACITY_PROBE_TIMEOUT:-45}s, so this machine cannot bootstrap a control plane.

The probe runs \`sleep 4\` and reads /proc/stat twice. A machine that cannot do that inside
${CAPACITY_PROBE_TIMEOUT:-45} seconds has no headroom to give a control plane, and this needs no
threshold to say so -- the failure to measure IS the measurement.

Measured 2026-08-24 on this laptop, for what this looks like when it is real: the sidecar did not
return inside its 45s budget, and \`colima ssh -- head -1 /proc/loadavg\` -- a plain shell in the VM,
no container -- did not return in 90s either.

What is using the machine:
$(top_cpu_consumers)

The remedy is to free CPU, not to retry. Same two options as a below-floor refusal, and both are
founder calls: stop the compose stack in deploy/compose for the rehearsal window (free, but it is
shared estate infrastructure other sessions depend on, LAW 11), or raise the VM's vCPU count, which
needs a colima restart that crew/STATE.md forbids outright, crew #85.

To override deliberately, with a reason:   IDLE_PROBE_TIMEOUT_IS_FATAL=0 deploy/rehearse_cluster.sh up"
  fi

  case "$idle" in
    ''|*[!0-9]*)
      # A guard that loses its evidence reports BLIND, never a verdict. Refusing on an unreadable
      # measurement would be a guard refusing correct work, which is LAW 38's outage.
      note "CPU headroom UNREADABLE (probe said '${idle:-nothing}'); proceeding BLIND, this run is not covered by the capacity guard"
      return 0
      ;;
  esac
  if [ "$idle" -lt "${IDLE_FLOOR_PCT:-10}" ]; then
    fail \
"this machine has ${idle}% idle CPU and cannot bootstrap a control plane.

Floor is ${IDLE_FLOOR_PCT:-10}%, measured over 4s inside the runtime's own kernel, not on the Mac.

This is NOT the daemon being broken -- the check above just started a container in under a second,
and it was right to pass. The runtime is healthy and the machine is full. Both failures leave the
same wreckage (no kubeconfig, no serverlb confd config, a half-built cluster), so read the number
above rather than the symptom.

What it looked like the last time this ran anyway, 2026-08-24: 20 minutes, k3s at 28% of the
machine, a single indexed kine SELECT taking 1.9s, and k3s never writing its own
/etc/rancher/k3s/k3s.yaml in 1205 seconds. The apiserver could not answer its own client.

What is using the machine:
$(top_cpu_consumers)

The remedy is to free CPU, not to retry. On this laptop the compose stack in deploy/compose shares
these vCPUs with the cluster, so stopping it for the rehearsal window is the free option -- but it
is shared estate infrastructure other sessions depend on, so that is a founder call under LAW 11,
not this script's and not yours. Raising the VM's vCPU count needs a colima restart, which
crew/STATE.md forbids outright: route it to the founder, crew #85.

To override deliberately, with a reason:   IDLE_FLOOR_PCT=0 deploy/rehearse_cluster.sh up"
  fi
  ok "CPU headroom ${idle}% idle over 4s, floor ${IDLE_FLOOR_PCT:-10}%"
}

# THE VERSION SKEW TRAP, HANDLED RATHER THAN NARRATED.
#
# Measured 2026-08-24 on this laptop: the kubectl on PATH is v1.27.2, shipped by Docker Desktop, and
# k3d 5.9.0 brings up k3s v1.35.5. That is eight minor versions of skew against a supported window of
# one, and the failures it produces are not honest ones -- fields the old client does not know about
# are dropped from what it sends, so a manifest applies "successfully" without the setting that
# mattered. A drill built on that would grade a proxy.
#
# So the drill fetches a matching kubectl into its own cache and puts that first on PATH. It does NOT
# touch the kubectl on PATH: that binary is machine-global state another session or Docker Desktop
# itself may depend on, and quietly replacing it is exactly the kind of shared-state change LAW 11
# says is never one agent's to make alone.
ensure_kubectl() {
  mkdir -p "$CACHE/bin"
  local want="${K3S_KUBECTL_VERSION:-v1.35.5}" bin="$CACHE/bin/kubectl"
  if [ ! -x "$bin" ] || [ "$("$bin" version --client -o json 2>/dev/null | sed -n 's/.*"gitVersion": *"\([^"]*\)".*/\1/p' | head -1)" != "$want" ]; then
    local arch; arch="$(uname -m)"; [ "$arch" = "x86_64" ] && arch=amd64; [ "$arch" = "aarch64" ] && arch=arm64
    curl -fsSL -o "$bin" "https://dl.k8s.io/release/${want}/bin/$(uname -s | tr '[:upper:]' '[:lower:]')/${arch}/kubectl" \
      || fail "could not download kubectl ${want}"
    chmod +x "$bin"
  fi
  PATH="$CACHE/bin:$PATH"; export PATH
}

k() { kubectl --context "$CTX" "$@"; }

cluster_running() { k3d cluster list "$CLUSTER" >/dev/null 2>&1 \
  && [ "$(k3d cluster list "$CLUSTER" --no-headers 2>/dev/null | awk '{print $2}')" != "0/1" ]; }

# THE ONLY HONEST TEST OF A CLUSTER IS THAT ITS API ANSWERS.
#
# `k3d cluster list` reports a SHAPE -- how many servers it believes are running -- and it said 1/1
# on 2026-08-24 while the API server was still starting and every kubectl returned a connection
# refused. A container being up is a fact about a process, in the same way that the rehearsal box's
# three `Started` containers were a fact about three processes while both HTTP probes returned 000.
# /readyz is the control plane answering for itself.
api_answers() { timeout 10 kubectl --context "$CTX" get --raw='/readyz' >/dev/null 2>&1; }

# Wait for the API, printing a dot per attempt so a slow machine looks slow rather than hung.
# Returns non-zero on timeout. The caller decides what that means; this function never exits.
wait_for_api() {
  local budget="${1:-300}" waited=0
  printf '       waiting for the API server '
  while [ "$waited" -lt "$budget" ]; do
    if api_answers; then printf ' up after %ss\n' "$waited"; return 0; fi
    printf '.'; sleep 5; waited=$(( waited + 5 ))
  done
  printf ' still silent after %ss\n' "$budget"
  return 1
}

# ---------------------------------------------------------------------------

cmd_up() {
  command -v docker >/dev/null || fail "docker is not installed on this laptop"
  docker info >/dev/null 2>&1 || fail "the local docker daemon is not running"
  # `docker info` answering is not the test; on 2026-08-24 it was the thing that lied. See the
  # comment on daemon_can_start_a_container.
  daemon_can_start_a_container || fail \
"the docker daemon answers status commands but cannot start a container within \
${DAEMON_PROBE_TIMEOUT:-60}s.

Runtime that failed: context '$(docker context show 2>/dev/null || echo unknown)'. Name it, because
the obvious repair is to restart the wrong thing: Docker Desktop is installed on this laptop and is
NOT the runtime, so restarting it clears nothing while appearing to succeed.

Do NOT let this script build into that. It gets far enough to create the k3d containers and not far
enough to configure them, and leaves a half-built cluster that then looks like a k3d bug.

Reproduce it in one line:   docker run --rm alpine:latest echo ok
Runtime on this machine:    docker context show    (colima, not Docker Desktop)
crew/STATE.md carries the standing instruction for this exact failure: do NOT restart colima,
route it to the founder -- an unco-ordinated restart is crew #85, load 255 on 12 cores."
  ok "docker context '$(docker context show 2>/dev/null || echo unknown)' started a container"

  # Starting a container proves the runtime works. It says nothing about whether this machine can
  # finish a control-plane bootstrap. See the comment on measure_idle_pct for what that cost.
  capacity_gate

  command -v k3d >/dev/null   || fail "k3d is not installed. brew install k3d"

  say "cluster"
  ensure_kubectl
  ok "kubectl $(kubectl version --client -o json | sed -n 's/.*"gitVersion": *"\([^"]*\)".*/\1/p' | head -1) from $CACHE/bin, PATH's own left alone"

  # A HEALTHY CLUSTER IS NEVER DESTROYED TO START A RUN.
  #
  # Founder, 2026-08-24: "we need the clsuter to be stable", "we cant have it going dowwn". The first
  # version of this line was an unconditional `k3d cluster delete`, which made every run a fresh
  # build and made the drill the single largest cause of the cluster not existing. Rebuilding from
  # nothing to prove something is a test of the builder, not of the thing built.
  #
  # So: if the API answers, keep it. If the containers exist but are stopped, start them rather than
  # rebuilding. Only a cluster that cannot be recovered is deleted, and REHEARSAL_FRESH=1 forces the
  # old behaviour for the F-45 repeatability drill, which genuinely does need to build from nothing.
  if [ "${REHEARSAL_FRESH:-0}" = "1" ]; then
    note "REHEARSAL_FRESH=1, deleting any existing cluster to prove a build from nothing"
    k3d cluster delete "$CLUSTER" >/dev/null 2>&1 || true
  elif k3d cluster list "$CLUSTER" >/dev/null 2>&1; then
    if api_answers; then
      ok "cluster $CLUSTER already up and its API answers, reusing it"
      ok "$(k get nodes --no-headers 2>/dev/null | wc -l | tr -d ' ') node(s) ready"
      return 0
    fi
    note "cluster $CLUSTER exists but its API is silent; starting it rather than rebuilding"
    k3d cluster start "$CLUSTER" >/dev/null 2>&1 || true
    if wait_for_api 240; then
      ok "cluster $CLUSTER recovered by starting it, no rebuild needed"
      return 0
    fi
    note "it did not recover; deleting and rebuilding is now the only road left"
    k3d cluster delete "$CLUSTER" >/dev/null 2>&1 || true
  fi

  # PRE-PULL, AND THE REASON IS A MEASURED FAILURE RATHER THAN CAUTION.
  #
  # First run, 2026-08-24: k3d spent its whole 180s creation budget pulling rancher/k3s and died with
  # `context deadline exceeded` against colima's docker.sock. The image is ~200MB and the clock that
  # ran out was the cluster's, not the download's, so a slower network turns a working drill into a
  # cluster-creation failure that names the wrong thing. Pulling first separates "the image is not
  # here yet" from "the cluster will not come up", which are different problems with different fixes.
  local k3s_image="rancher/k3s:${K3S_IMAGE_VERSION:-v1.35.5-k3s1}"
  if ! docker image inspect "$k3s_image" >/dev/null 2>&1; then
    note "pulling $k3s_image, first run only"
    docker pull "$k3s_image" >/dev/null 2>&1 || fail "could not pull $k3s_image"
  fi
  ok "$k3s_image present locally"

  # --wait means k3d returns when the API server answers, not when the container starts. Without it
  # the next kubectl races the control plane and fails with a connection refused that reads like a
  # broken cluster.
  #
  # stderr is NOT suppressed. The first version of this line sent it to /dev/null and printed the
  # command to re-run by hand, which is precisely the thing LAW 2 forbids: the data was on screen and
  # this script threw it away, so the founder was handed a shrug where an error message existed.
  # The output goes through a file rather than a pipe on purpose. `cmd | sed` reports SED's exit
  # status, so `if ! k3d ... | sed` would call a failed cluster creation a success every single time.
  # --no-rollback IS THE STABILITY FIX, AND IT COST A WORKING CLUSTER TO FIND.
  #
  # Measured 2026-08-24, k3d v5.9.0, from $CACHE/k3d-create.log: the server node started at t=620s
  # and k3d gave up at t=913s with `error waiting for log line "k3s is up and running" ... context
  # deadline exceeded`, then printed `Rolling Back` and DELETED the cluster along with its volume.
  # `docker ps` showed k3d-prospector-rehearsal-server-0 as `Up 5 minutes` while that rollback ran.
  #
  # The cluster was fine. k3d's clock ran out first, and its rollback destroyed a working cluster to
  # tidy up after a timeout that measured a starved 4-CPU Docker VM rather than a broken control
  # plane. On a machine six sessions share, that turns every slow moment into a demolition.
  #
  # --no-rollback keeps whatever came up. The timeout goes to 900s because the measured cold build
  # took 913s. Then this script waits for /readyz itself, so the verdict comes from the API server
  # answering rather than from k3d's patience.
  # WHAT IS STARVED IS I/O, NOT CPU, AND THAT CHANGES WHICH ADD-ONS ARE WORTH DISABLING.
  #
  # Measured 2026-08-24 inside the colima VM, immediately after a bootstrap failed at t=1250s with
  # `failed to bootstrap cluster data: context deadline exceeded`:
  #
  #   /proc/loadavg          499.75 473.70 416.25   551/3159 runnable
  #   nproc                  4
  #   df -h /var/lib/docker  59G total, 38G available      <- not a disk-space problem
  #   free -m                3445 MB available             <- not a memory problem
  #   host CPU               Intel i7-8850H, 6 cores       <- no emulation; colima arch matches
  #
  # A load average of 500 on 4 CPUs with memory and disk to spare is hundreds of processes parked
  # in uninterruptible sleep waiting on the disk. That matches the 17 `Slow SQL ... INSERT INTO
  # kine(...) duration=2.79s` lines k3s printed: every write of the bootstrap goes through kine to
  # SQLite on overlay2 inside a VM. The fix is to make the bootstrap write less, not to wait longer
  # -- a timeout increase measures patience, and the previous attempt already had 900s and lost.
  #
  # traefik and servicelb are two Helm chart installs on the critical path, and the estate wants
  # neither: deploy/k8s/base/edge.yaml is Gateway API served by its own controller, and a rehearsal
  # with --agents 0 has nothing for servicelb to balance. metrics-server was already off.
  #
  # local-storage STAYS ON, deliberately. deploy/k8s/base declares two PVCs (prospector-data and
  # prospector-store-api-data); without the local-path provisioner they never bind and every
  # workload sits Pending. Disabling it would make the cluster start faster and prove nothing.
  local clog="$CACHE/k3d-create.log"
  set +e
  k3d cluster create "$CLUSTER" --wait --timeout "${K3D_TIMEOUT:-900s}" \
    --no-rollback \
    --agents 0 \
    --image "$k3s_image" \
    --k3s-arg '--disable=metrics-server@server:0' \
    --k3s-arg '--disable=traefik@server:0' \
    --k3s-arg '--disable=servicelb@server:0' >"$clog" 2>&1
  local crc=$?
  set -e

  # A non-zero exit from k3d is a report about k3d's wait, not a verdict on the cluster. With
  # --no-rollback the parts survive, so the cluster gets asked directly before anything is declared
  # broken. This ordering is the difference between "it timed out" and "it does not work".
  if [ "$crc" -ne 0 ]; then
    note "k3d exited $crc; asking the cluster itself before believing it"
    k3d cluster start "$CLUSTER" >/dev/null 2>&1 || true
    if wait_for_api "${API_WAIT_S:-420}"; then
      ok "the cluster is serving despite k3d's timeout, and nothing was rolled back"
    else
      sed 's/^/       /' "$clog" | tail -12
      fail "k3d exited $crc and the API never answered -- the reason is in the lines above"
    fi
  else
    api_answers || wait_for_api "${API_WAIT_S:-420}" \
      || fail "k3d reported success and the API server does not answer"
  fi
  ok "k3d cluster $CLUSTER up, context $CTX"

  local server; server="$(k version -o json 2>/dev/null | sed -n 's/.*"gitVersion": *"\(v[^"]*\)".*/\1/p' | tail -1)"
  ok "k3s server $server, $(k get nodes --no-headers | wc -l | tr -d ' ') node"

  say "kyverno ${KYVERNO_VERSION}"
  # The install manifest, not a Helm chart, because helm is one more tool to install and this drill's
  # whole claim is that it always runs. CNCF Graduated 2026-03-24, Apache-2.0, CLOMonitor 93.75 --
  # measured 2026-08-24 from landscape.yml and the CLOMonitor API, two sources that can disagree.
  k apply --server-side -f \
    "https://github.com/kyverno/kyverno/releases/download/${KYVERNO_VERSION}/install.yaml" >/dev/null 2>&1 \
    || fail "could not install kyverno ${KYVERNO_VERSION}"
  k -n kyverno rollout status deploy/kyverno-admission-controller --timeout=180s >/dev/null \
    || fail "kyverno admission controller never became ready"

  # ROLLOUT STATUS IS A PROXY, AND IT COST THIS DRILL A RUN. Measured 2026-08-24 on this laptop:
  # the admission controller Deployment went Available=True at 21:11:20Z, this line returned, the
  # drill applied the overlay, and the API server answered
  #
  #     Error from server (InternalError): failed calling webhook "validate-policy.kyverno.svc":
  #     Post "https://kyverno-svc.kyverno.svc:443/policyvalidate?timeout=10s": context deadline exceeded
  #
  # at 21:13:18Z -- nearly two minutes AFTER the Deployment said Available. Probed by hand at
  # 21:15Z the same webhook answered a server-side dry run immediately, so nothing was broken; the
  # readiness reading was simply about something else. A Deployment being Available says its pods
  # pass their own probes. It says nothing about the ValidatingWebhookConfiguration being
  # registered, the CA bundle being injected, or the Service having a ready endpoint, and it is
  # those three the API server needs before an apply can survive.
  #
  # So ask the webhook. A server-side dry run of a trivial ClusterPolicy goes through
  # /policyvalidate exactly as the overlay's own policies will, and either it answers or it does
  # not. Nothing is created: --dry-run=server means the API server runs admission and discards the
  # object. This grades the thing, not a signal correlated with the thing.
  say "kyverno webhook"
  local wtmp; wtmp="$(mktemp -t kyverno-webhook-probe)"
  cat >"$wtmp" <<'PROBE'
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: webhook-liveness-probe
spec:
  rules:
    - name: noop
      match:
        any:
          - resources:
              kinds: [Pod]
      validate:
        message: this policy is never created; it exists to make the webhook answer
        pattern:
          metadata:
            name: "?*"
PROBE
  local wi=0 wbudget="${KYVERNO_WEBHOOK_WAIT_S:-300}" wstart werr
  werr="$(mktemp -t kyverno-webhook-err)"
  wstart="$(date +%s)"
  until k apply --dry-run=server -f "$wtmp" >/dev/null 2>"$werr"; do
    wi=$(( $(date +%s) - wstart ))
    if [ "$wi" -ge "$wbudget" ]; then
      note "last error from the API server:"
      sed 's/^/       /' "$werr" | tail -4
      rm -f "$wtmp" "$werr"
      fail \
"the kyverno webhook did not answer a server-side dry run within ${wbudget}s.

The Deployment IS Available -- the line above proved that -- so this is not a crashing pod. The
webhook is registered and the API server cannot reach it, or the CA bundle has not been injected.
Look at the error above, then at:  kubectl -n kyverno get svc,endpoints kyverno-svc

Raise the budget with KYVERNO_WEBHOOK_WAIT_S if this machine is simply slow, but read the error
first: a webhook that will never answer does not answer any faster with a longer wait."
    fi
    sleep 3
  done
  rm -f "$wtmp" "$werr"
  ok "kyverno webhook answered a server-side dry run after $(( $(date +%s) - wstart ))s (Deployment was Available before this)"

  # THE OVERLAY REFERENCES KINDS THIS CLUSTER DOES NOT HAVE. Measured in the same failed run: the
  # staging overlay carries the edge, and the edge is a Gateway, four HTTPRoutes and a ClusterIssuer.
  # A bare k3s cluster has none of those kinds, so kubectl refused five objects with
  # "no matches for kind ... ensure CRDs are installed first" and the whole apply exited non-zero.
  #
  # CRDs ONLY, AND THIS IS A DELIBERATE LIMIT ON WHAT THE DRILL CLAIMS. Installing the CRDs makes
  # the manifests apply, which is what this step is for: it proves the overlay a real cluster would
  # be handed is well-formed against the real schemas, and that the estate's policies admit or
  # refuse it. It does NOT prove a certificate is ever issued or that traffic routes -- there is no
  # cert-manager controller and no Gateway implementation running here, so a Gateway stays
  # Programmed=False and a Certificate stays pending forever. Those need a controller, an ACME
  # account and DNS that resolves, none of which belong in a throwaway cluster on a laptop. When
  # the drill grows to claim routing, it installs the controllers and says so on this line.
  #
  # Versions are pinned rather than "latest" so two runs a week apart rehearse the same thing.
  # gateway-api v1.6.1 is what deploy/k8s/base/edge.yaml already names; checked 2026-08-24 against
  # the GitHub releases API, it is also the current release (2026-07-16). cert-manager v1.21.1 is
  # the current release (2026-07-29) and ships a CRDs-only asset, which is why no chart is needed.
  say "the CRDs the overlay's own kinds need"
  local crd_gwapi="${GATEWAY_API_VERSION:-v1.6.1}"
  local crd_certmgr="${CERT_MANAGER_VERSION:-v1.21.1}"
  k apply --server-side -f \
    "https://github.com/kubernetes-sigs/gateway-api/releases/download/${crd_gwapi}/standard-install.yaml" \
    >/dev/null 2>&1 || fail "could not install the gateway-api ${crd_gwapi} CRDs"
  k apply --server-side -f \
    "https://github.com/cert-manager/cert-manager/releases/download/${crd_certmgr}/cert-manager.crds.yaml" \
    >/dev/null 2>&1 || fail "could not install the cert-manager ${crd_certmgr} CRDs"
  # Established, not merely created: the API server registers a CRD before it can serve the kind,
  # and an apply in that window fails with the same "no matches for kind" this step exists to stop.
  for crd in gateways.gateway.networking.k8s.io httproutes.gateway.networking.k8s.io \
             clusterissuers.cert-manager.io; do
    k wait --for=condition=Established "crd/$crd" --timeout=120s >/dev/null 2>&1 \
      || fail "CRD $crd never became Established"
  done
  ok "gateway-api ${crd_gwapi} and cert-manager ${crd_certmgr} CRDs established (schemas only; no controllers run here)"

  say "the estate's standards"
  # APPLY THE OVERLAY, NOT THE DIRECTORY. `apply -f "$POLICY_DIR/"` read the raw yaml files and so
  # rehearsed something no cluster will ever run: it missed the upstream Kyverno library entirely,
  # because that arrives through kustomize, and it applied the estate's two policies without the
  # Enforce patch. A drill against different objects than production gets is not a drill.
  #
  # `-k` is kubectl's built-in kustomize. Same command, same overlay, same 26 policies a real
  # cluster is handed. deploy/k8s/README.md holds the measurement.
  #
  # --server-side because the built policy CRDs are large enough to hit the size limit on the
  # last-applied-configuration annotation that client-side apply writes.
  # RETRY, BECAUSE THE WEBHOOK TIMES OUT UNDER ITS OWN LOAD AND NOT BECAUSE ANYTHING IS WRONG.
  # Measured 2026-08-24, on a run where the webhook probe above answered in 1 second: applying the
  # overlay still produced three
  #     failed calling webhook "validate-policy.kyverno.svc": ... policyvalidate?timeout=10s:
  #     context deadline exceeded
  # while the other twenty-three policies went in. One apply hands the API server 26 ClusterPolicies
  # at once, each of which Kyverno must validate inside a 10s webhook budget, on a laptop measured
  # at 19% idle. The webhook is not broken -- it is queued behind itself.
  #
  # `apply` is idempotent, so a retry re-sends the whole overlay and only the objects that did not
  # land have any work to do; each pass is cheaper than the last and the queue drains. This is a
  # bounded retry with a named budget, not a loop: if the overlay still will not apply after
  # OVERLAY_APPLY_TRIES passes, the last error is printed and the drill fails, because at that point
  # it is not congestion.
  local oi=1 otries="${OVERLAY_APPLY_TRIES:-4}" oerr
  oerr="$(mktemp -t overlay-apply-err)"
  # The manifests spell every hostname as <label>.${ESTATE_ZONE} and Flux substitutes the zone on the
  # cluster (postBuild.substituteFrom estate-config). There is no Flux here, so render, substitute
  # from the environment, then apply; an unset zone stops the drill instead of applying a literal.
  until { k kustomize "$REPO/deploy/k8s/overlays/staging" \
          | sed "s/\${ESTATE_ZONE}/${ESTATE_ZONE:?set ESTATE_ZONE, the estate zone from clusters/<cluster>/estate-config.yaml}/g" \
          | k apply --server-side -f -; } >/dev/null 2>"$oerr"; do
    if [ "$oi" -ge "$otries" ]; then
      note "last error from the API server, after $oi attempts:"
      sed 's/^/       /' "$oerr" | tail -6
      rm -f "$oerr"
      fail "the staging overlay did not apply in $oi attempts"
    fi
    note "overlay apply $oi/$otries did not complete; $(grep -c 'context deadline exceeded' "$oerr" || true) webhook timeout(s), retrying"
    oi=$((oi+1)); sleep 10
  done
  if [ "$oi" -gt 1 ]; then
    note "the overlay applied on attempt $oi; the earlier failures were webhook congestion, not rejection"
  fi
  rm -f "$oerr"
  # `apply` returns when the API server has the object, not when the webhook is enforcing it. A
  # policy test run in that window passes because nothing is refusing yet, which is the most
  # expensive kind of green there is.
  local i=0
  until [ "$(k get clusterpolicy -o jsonpath='{range .items[*]}{.status.ready}{"\n"}{end}' 2>/dev/null | grep -c true)" \
          = "$(k get clusterpolicy --no-headers 2>/dev/null | wc -l | tr -d ' ')" ]; do
    i=$((i+1)); [ "$i" -le 60 ] || fail "policies applied but never became ready"
    sleep 2
  done
  k get clusterpolicy --no-headers | awk '{printf "   ok  policy %s\n", $1}'
}

# ---------------------------------------------------------------------------
# LAW 38: "you tested that your fence says no. That was never in doubt. What was in doubt is whether
# it says yes to the work it was never meant to stop." Every standard is proved BOTH WAYS here, in
# one run, and a policy that fails either half fails the drill.

POLICY_PASS=0; POLICY_FAIL=0

# refuses <name> <policy that should catch it> <<< manifest
refuses() {
  local label="$1" want="$2" out
  if out="$(k apply --dry-run=server -f - 2>&1)"; then
    printf '   NO  %-42s WAS ADMITTED and should not have been\n' "$label"
    POLICY_FAIL=$((POLICY_FAIL+1)); return
  fi
  # Refused is not enough: refused BY THE RIGHT RULE is the claim. A manifest rejected because it is
  # malformed, or caught by a different policy, would otherwise read as this policy working.
  if printf '%s' "$out" | grep -q "$want"; then
    printf '   ok  %-42s refused by %s\n' "$label" "$want"
    POLICY_PASS=$((POLICY_PASS+1))
  else
    printf '   NO  %-42s refused, but not by %s:\n       %s\n' "$label" "$want" "$(printf '%s' "$out" | head -2 | tr '\n' ' ')"
    POLICY_FAIL=$((POLICY_FAIL+1))
  fi
}

# permits <name> <<< manifest
permits() {
  local label="$1" out
  if out="$(k apply --dry-run=server -f - 2>&1)"; then
    printf '   ok  %-42s admitted, as it should be\n' "$label"
    POLICY_PASS=$((POLICY_PASS+1))
  else
    printf '   NO  %-42s REFUSED CORRECT WORK -- this is an outage, not a false positive:\n       %s\n' \
      "$label" "$(printf '%s' "$out" | head -3 | tr '\n' ' ')"
    POLICY_FAIL=$((POLICY_FAIL+1))
  fi
}

# A pod that satisfies every standard. The paired controls below each break exactly one thing about
# it, so a refusal names one cause rather than several at once.
good_pod() {  # good_pod <name> [extra yaml under spec.containers[0]]
  cat <<YAML
apiVersion: v1
kind: Pod
metadata:
  name: $1
  namespace: $NS
  labels:
    prospector.estate/serving: "true"
spec:
  containers:
    - name: app
      image: nginx:1.29
      resources:
        requests: { memory: 32Mi }
        limits:   { memory: 64Mi }
      readinessProbe: { httpGet: { path: /, port: 80 } }
      livenessProbe:  { httpGet: { path: /, port: 80 } }
${2:-}
YAML
}

cmd_policy() {
  ensure_kubectl
  cluster_running || fail "no cluster. run: deploy/rehearse_cluster.sh up"
  k create namespace "$NS" --dry-run=client -o yaml | k apply -f - >/dev/null

  say "the standards, proved BOTH WAYS"

  printf '\n   -- what they must refuse\n'

  refuses "two replicas on a single-writer store" money-rail-single-writer <<YAML
apiVersion: apps/v1
kind: Deployment
metadata: { name: two-engines, namespace: $NS, labels: { prospector.estate/single-writer: "true" } }
spec:
  replicas: 2
  strategy: { type: Recreate }
  selector: { matchLabels: { app: two-engines } }
  template:
    metadata: { labels: { app: two-engines } }
    spec: { containers: [ { name: app, image: "nginx:1.29", resources: { requests: { memory: 32Mi }, limits: { memory: 64Mi } } } ] }
YAML

  refuses "RollingUpdate onto a ReadWriteOnce store" money-rail-single-writer <<YAML
apiVersion: apps/v1
kind: Deployment
metadata: { name: rolling-engine, namespace: $NS, labels: { prospector.estate/single-writer: "true" } }
spec:
  replicas: 1
  strategy: { type: RollingUpdate }
  selector: { matchLabels: { app: rolling-engine } }
  template:
    metadata: { labels: { app: rolling-engine } }
    spec: { containers: [ { name: app, image: "nginx:1.29", resources: { requests: { memory: 32Mi }, limits: { memory: 64Mi } } } ] }
YAML

  refuses "optional secret, the 2026-08-24 incident" no-optional-secret-references <<YAML
apiVersion: v1
kind: Pod
metadata: { name: half-configured, namespace: $NS }
spec:
  containers:
    - name: app
      image: nginx:1.29
      envFrom: [ { secretRef: { name: shop-secrets, optional: true } } ]
      resources: { requests: { memory: 32Mi }, limits: { memory: 64Mi } }
YAML

  refuses "a credential written into the pod spec" no-literal-credentials-in-pod-spec <<YAML
apiVersion: v1
kind: Pod
metadata: { name: leaky, namespace: $NS }
spec:
  containers:
    - name: app
      image: nginx:1.29
      env: [ { name: Stripe__WebhookSecret, value: "not-a-real-key-but-the-shape-is-the-point" } ]
      resources: { requests: { memory: 32Mi }, limits: { memory: 64Mi } }
YAML

  refuses "an image tagged :latest" images-must-be-traceable <<YAML
apiVersion: v1
kind: Pod
metadata: { name: untraceable, namespace: $NS }
spec:
  containers:
    - name: app
      image: nginx:latest
      resources: { requests: { memory: 32Mi }, limits: { memory: 64Mi } }
YAML

  refuses "a container with no memory limit" workloads-declare-what-they-need <<YAML
apiVersion: v1
kind: Pod
metadata: { name: unbounded, namespace: $NS }
spec:
  containers: [ { name: app, image: "nginx:1.29" } ]
YAML

  refuses "a privileged container" secure-by-default <<YAML
apiVersion: v1
kind: Pod
metadata: { name: rooted, namespace: $NS }
spec:
  containers:
    - name: app
      image: nginx:1.29
      securityContext: { privileged: true }
      resources: { requests: { memory: 32Mi }, limits: { memory: 64Mi } }
YAML

  refuses "a serving pod with no probes" serving-workloads-must-be-probed <<YAML
apiVersion: v1
kind: Pod
metadata: { name: unprobed, namespace: $NS, labels: { prospector.estate/serving: "true" } }
spec:
  containers:
    - name: app
      image: nginx:1.29
      resources: { requests: { memory: 32Mi }, limits: { memory: 64Mi } }
YAML

  printf '\n   -- what they must NOT refuse\n'

  good_pod compliant-shop-pod | permits "a pod that meets every standard"

  permits "a secret reference that is required" <<YAML
apiVersion: v1
kind: Pod
metadata: { name: properly-configured, namespace: $NS }
spec:
  containers:
    - name: app
      image: nginx:1.29
      envFrom: [ { secretRef: { name: shop-secrets } } ]
      env: [ { name: Jwt__SigningKeyPem, valueFrom: { secretKeyRef: { name: shop-secrets, key: jwt } } } ]
      resources: { requests: { memory: 32Mi }, limits: { memory: 64Mi } }
YAML

  # The false-positive check the credential policy most needs. Jwt__Issuer and Jwt__Audience are
  # claim names, not credentials -- docker-compose.yml says so explicitly -- and a policy that
  # refused them would stop the shop starting while looking like it was protecting it.
  permits "issuer and audience, which are not secrets" <<YAML
apiVersion: v1
kind: Pod
metadata: { name: claims-not-credentials, namespace: $NS }
spec:
  containers:
    - name: app
      image: nginx:1.29
      env:
        - { name: Jwt__Issuer,   value: store-api }
        - { name: Jwt__Audience, value: store-web }
        - { name: STORE_API_URL, value: "https://api.${ESTATE_ZONE}" }
      resources: { requests: { memory: 32Mi }, limits: { memory: 64Mi } }
YAML

  permits "one replica, Recreate, on the money rail" <<YAML
apiVersion: apps/v1
kind: Deployment
metadata: { name: one-engine, namespace: $NS, labels: { prospector.estate/single-writer: "true" } }
spec:
  replicas: 1
  strategy: { type: Recreate }
  selector: { matchLabels: { app: one-engine } }
  template:
    metadata: { labels: { app: one-engine } }
    spec: { containers: [ { name: app, image: "nginx:1.29", resources: { requests: { memory: 32Mi }, limits: { memory: 64Mi } } } ] }
YAML

  # The escape hatch has to work, or the fence is a wall. LAW 38 again: leave one, name it, count it.
  permits "privileged WITH the declared escape hatch" <<YAML
apiVersion: v1
kind: Pod
metadata:
  name: declared-exception
  namespace: $NS
  labels: { prospector.estate/needs-privileged: "true" }
spec:
  containers:
    - name: app
      image: nginx:1.29
      securityContext: { privileged: true }
      resources: { requests: { memory: 32Mi }, limits: { memory: 64Mi } }
YAML

  printf '\n   %s of %s paired controls passed\n' "$POLICY_PASS" "$((POLICY_PASS + POLICY_FAIL))"
  [ "$POLICY_FAIL" = 0 ]
}

# ---------------------------------------------------------------------------

cmd_adapter() {
  ensure_kubectl
  cluster_running || fail "no cluster. run: deploy/rehearse_cluster.sh up"

  say "deploy/targets/k8s.sh, against a real cluster, for the first time"
  docker image inspect prospector-engine:local >/dev/null 2>&1 \
    || fail "prospector-engine:local is not built. docker compose -f deploy/compose/docker-compose.yml build engine"

  # A tag that names this drill rather than :latest, because the estate's own images-must-be-traceable
  # policy refuses :latest and the adapter would otherwise be refused by the standards it ships beside.
  local tag="prospector-engine:rehearsal"
  docker tag prospector-engine:local "$tag"
  note "importing $tag into the cluster (2.6GB, this is the slow part)"
  k3d image import "$tag" -c "$CLUSTER" >/dev/null 2>&1 || fail "k3d could not import $tag"
  ok "image in the cluster's own store, nothing pulled from a registry"

  # A throwaway env file. The real one is never copied into a drill: t_secrets reads a PATH and never
  # puts a value in argv, so nothing lands in `ps` or a shell history either way.
  local envfile="$CACHE/rehearsal.env"
  mkdir -p "$CACHE"; umask 077
  printf 'PROSPECTOR_STORE_DIR=/data/store\nPROSPECTOR_REHEARSAL=1\n' > "$envfile"

  set +e
  (
    export PROSPECTOR_K8S_CONTEXT="$CTX" PROSPECTOR_K8S_NAMESPACE="$NS" \
           PROSPECTOR_K8S_IMAGE="$tag" PROSPECTOR_K8S_LOAD_CMD="true"
    for verb in t_preflight t_provision; do
      printf '   -   %s ... ' "$verb"
      if bash "$REPO/deploy/targets/k8s.sh" "$verb" >/dev/null 2>&1; then echo ok; else echo FAILED; exit 1; fi
    done
    printf '   -   t_secrets ... '
    if bash "$REPO/deploy/targets/k8s.sh" t_secrets "$envfile" >/dev/null 2>&1; then echo ok; else echo FAILED; exit 1; fi
    printf '   -   t_start ... '
    if out="$(bash "$REPO/deploy/targets/k8s.sh" t_start 2>&1)"; then
      echo ok
    else
      echo FAILED
      printf '       %s\n' "$(printf '%s' "$out" | tail -4 | sed 's/^/       /')"
      exit 1
    fi
  )
  local rc=$?
  set -e
  rm -f "$envfile"
  [ "$rc" = 0 ] || return 1

  printf '   -   t_health ... '
  if bash "$REPO/deploy/targets/k8s.sh" t_health 2>&1 | sed 's/^/       /'; then :; else echo "FAILED"; return 1; fi
}

# ---------------------------------------------------------------------------
# The founder asked for "total self healing prod ready". This measures the part that is real today
# rather than describing the part that would be. Layer 1 is the cluster replacing what it lost; layer
# 2 is a GitOps controller reverting what somebody changed, and this estate does not have one yet, so
# the drill says so out loud instead of leaving the reader to assume.

cmd_heal() {
  ensure_kubectl
  cluster_running || fail "no cluster. run: deploy/rehearse_cluster.sh up"
  local dep=prospector-engine
  k -n "$NS" get deploy "$dep" >/dev/null 2>&1 \
    || fail "nothing deployed. run: deploy/rehearse_cluster.sh adapter"

  say "self-healing, timed rather than asserted"

  printf '   layer 1  the pod is destroyed, and nothing intervenes\n'
  local pod start elapsed
  pod="$(k -n "$NS" get pods -l app="$dep" -o jsonpath='{.items[0].metadata.name}')"
  printf '            killing %s\n' "$pod"
  start="$(date +%s)"
  k -n "$NS" delete pod "$pod" --wait=false >/dev/null
  # Waiting on the DEPLOYMENT, not on a pod name. Waiting for the named pod to come back would wait
  # forever: the replacement has a different name, which is the whole mechanism.
  if k -n "$NS" wait --for=condition=Available "deploy/$dep" --timeout=300s >/dev/null 2>&1; then
    elapsed=$(( $(date +%s) - start ))
    printf '            back to Available in %ss, as %s\n' "$elapsed" \
      "$(k -n "$NS" get pods -l app="$dep" -o jsonpath='{.items[0].metadata.name}')"
  else
    printf '            NEVER RECOVERED within 300s\n'; return 1
  fi

  printf '\n   layer 1  the replica count is set to zero by hand\n'
  k -n "$NS" scale deploy "$dep" --replicas=0 >/dev/null
  sleep 5
  local n; n="$(k -n "$NS" get pods -l app="$dep" --no-headers 2>/dev/null | wc -l | tr -d ' ')"
  printf '            pods running: %s\n' "$n"
  if [ "$n" = 0 ]; then
    printf '            NOT HEALED, and this is the honest result. Kubernetes replaces what it\n'
    printf '            loses; it does not revert what an operator changed on purpose. Reverting a\n'
    printf '            hand edit is GitOps drift correction -- Argo CD selfHeal -- and this estate\n'
    printf '            has not installed one yet. Until it does, "total self-healing" covers\n'
    printf '            crashes and lost nodes, and does not cover a bad change.\n'
    k -n "$NS" scale deploy "$dep" --replicas=1 >/dev/null
    k -n "$NS" wait --for=condition=Available "deploy/$dep" --timeout=300s >/dev/null 2>&1 || true
    printf '            restored by hand, which is the point being made\n'
  fi

  printf '\n   layer 1  the money fence, under the cluster rather than in a comment\n'
  if k -n "$NS" scale deploy "$dep" --replicas=2 >/dev/null 2>&1; then
    sleep 3
    local r; r="$(k -n "$NS" get deploy "$dep" -o jsonpath='{.spec.replicas}')"
    if [ "$r" = 2 ]; then
      printf '            REFUSED NOTHING: replicas is %s. Two engines, two spend ledgers.\n' "$r"
      k -n "$NS" scale deploy "$dep" --replicas=1 >/dev/null
      return 1
    fi
  fi
  printf '            scaling to 2 was refused, the deployment is still at %s\n' \
    "$(k -n "$NS" get deploy "$dep" -o jsonpath='{.spec.replicas}')"
}

cmd_status() {
  ensure_kubectl
  if ! cluster_running; then echo "cluster: down"; return 1; fi
  say "the cluster"
  k get nodes -o wide --no-headers | sed 's/^/   /'
  # The API, not the container list. `k3d cluster list` said 1/1 on 2026-08-24 while every kubectl
  # returned a connection refused, so a shape is reported here alongside the thing itself answering.
  if api_answers; then ok "the API server answers /readyz"; else bad "the API server does NOT answer /readyz"; fi
  printf '   restart policy on each k3d container (this is what survives a Docker restart):\n'
  docker ps -a --filter "name=k3d-$CLUSTER" --format '{{.Names}}' 2>/dev/null | while read -r c; do
    printf '      %-46s %s\n' "$c" \
      "$(docker inspect -f '{{.HostConfig.RestartPolicy.Name}}' "$c" 2>/dev/null || echo unknown)"
  done
  printf '   policies:\n'; k get clusterpolicy --no-headers 2>/dev/null | sed 's/^/      /' || echo "      none"
  printf '   workloads in %s:\n' "$NS"
  k -n "$NS" get pods --no-headers 2>/dev/null | sed 's/^/      /' || echo "      none"
}

# F-46a AT THE CONTROL PLANE, NOT AT THE WORKLOAD.
#
# Founder, 2026-08-24: "we cant have it going dowwn, thats absured", then "resilience, self healing".
# cmd_heal proves a POD comes back. That is the failure Kubernetes was always going to handle. This
# proves the CLUSTER comes back when its own server dies, which is the failure that actually takes
# the estate off the air, and it is the one nothing here had ever tested.
#
# Nothing is repaired by this function on purpose. It kills the server container and then only
# watches. A drill that helps the patient recover has measured the drill.
cmd_resilience() {
  ensure_kubectl
  cluster_running || fail "no cluster to test; run: deploy/rehearse_cluster.sh up"
  api_answers     || fail "the API is already down, so nothing here would mean anything"

  say "resilience -- killing the control plane and touching nothing afterwards"
  local srv="k3d-$CLUSTER-server-0"
  docker inspect "$srv" >/dev/null 2>&1 || fail "cannot find the server container $srv"

  local policy; policy="$(docker inspect -f '{{.HostConfig.RestartPolicy.Name}}' "$srv")"
  printf '   restart policy on %s: %s\n' "$srv" "$policy"
  if [ "$policy" = "no" ] || [ -z "$policy" ]; then
    bad "restart policy is '$policy', so this cluster CANNOT come back by itself"
    printf '       That is the founder"s complaint as a measurement rather than a feeling.\n'
    return 1
  fi

  printf '   killing %s with SIGKILL, no graceful stop, no warning to the cluster\n' "$srv"
  docker kill "$srv" >/dev/null 2>&1 || fail "could not kill $srv"

  # Prove it actually went down. Without this the next line could pass on a cluster that never died,
  # which would grade the drill instead of the cluster.
  local down=0 i=0
  while [ "$i" -lt 12 ]; do
    api_answers || { down=1; break; }
    sleep 2; i=$(( i + 2 ))
  done
  if [ "$down" = 0 ]; then
    bad "the API still answered after the server was killed; this drill proved nothing"
    return 1
  fi
  ok "confirmed down: the API stopped answering after ${i}s"

  local t0 t1; t0="$(date +%s)"
  if wait_for_api "${RESILIENCE_WAIT_S:-420}"; then
    t1="$(date +%s)"
    ok "the cluster recovered BY ITSELF in $(( t1 - t0 ))s, with no command from this script"
    k get nodes --no-headers 2>/dev/null | sed 's/^/       /'
    return 0
  fi
  bad "the cluster did not come back within ${RESILIENCE_WAIT_S:-420}s"
  return 1
}

cmd_down() {
  k3d cluster delete "$CLUSTER" >/dev/null 2>&1 && echo "cluster destroyed: $CLUSTER" || echo "no cluster to destroy"
  rm -f "$CACHE/rehearsal.env"
}

case "${1:-all}" in
  up)      cmd_up ;;
  policy)  cmd_policy ;;
  adapter) cmd_adapter ;;
  heal)    cmd_heal ;;
  resilience) cmd_resilience ;;
  status)  cmd_status ;;
  down)    cmd_down ;;
  all)     cmd_up
           rc=0
           cmd_policy  || rc=1
           cmd_adapter || rc=1
           [ "$rc" = 0 ] && { cmd_heal || rc=1; }
           if [ "$rc" = 0 ]; then
             say "rehearsal complete"
             echo "   Every standard refused what it should and admitted what it should. The k8s"
             echo "   adapter ran against a real cluster for the first time. Recovery was timed."
             echo "   Destroy it with:"
             echo "       deploy/rehearse_cluster.sh down"
           else
             say "REHEARSAL FAILED"
             echo "   This is the drill doing its job. Nothing has been rented and nothing is live,"
             echo "   so the cost of this failure is the two minutes it took to find it."
             echo "       deploy/rehearse_cluster.sh status"
             exit 1
           fi ;;
  -h|--help) sed -n '2,27p' "${BASH_SOURCE[0]}" ;;
  *) fail "unknown command: $1  (up | policy | adapter | heal | status | down)" ;;
esac
