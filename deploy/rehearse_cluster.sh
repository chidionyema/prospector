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
POLICY_DIR="$REPO/deploy/k8s/policies"

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
  local clog="$CACHE/k3d-create.log"
  set +e
  k3d cluster create "$CLUSTER" --wait --timeout "${K3D_TIMEOUT:-900s}" \
    --no-rollback \
    --agents 0 \
    --image "$k3s_image" \
    --k3s-arg '--disable=metrics-server@server:0' >"$clog" 2>&1
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
  ok "kyverno admission controller ready"

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
  k apply --server-side -k "$REPO/deploy/k8s/overlays/staging" >/dev/null \
    || fail "the staging overlay did not apply"
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
        - { name: STORE_API_URL, value: "https://api.mumchimp.com" }
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
