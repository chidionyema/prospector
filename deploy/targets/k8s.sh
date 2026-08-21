#!/usr/bin/env bash
# Kubernetes, and the lighter versions of it: k3s, k0s, MicroK8s, kind, EKS, GKE. Anything
# `kubectl` can reach is the same target.
#
# Founder question, 2026-08-20: "given our platforn requorenents how could jubernetes helo",
# then "even if we dont go for k8 right away, or if not full k8 then a lighter suitable erion".
# This is the answer as a FOURTH ADAPTER rather than a new substrate. docs/STACK_AUDIT.md §5
# already ruled: keep the eleven-line verb contract, do not adopt Kamal or Nomad. Kubernetes
# joins that contract the same way sshdocker did, and nothing else in this repository learns the
# word "kubectl". Choosing k8s later then costs one env var, not a migration.
#
#   PROSPECTOR_K8S_IMAGE=ghcr.io/you/prospector-engine:2026-08-20 \
#     deploy/cutover.sh --from fly --to k8s
#
# On a cluster with no registry (kind, k3s, a laptop), set the side-load command instead:
#
#   PROSPECTOR_K8S_LOAD_CMD='kind load docker-image' deploy/cutover.sh --from fly --to k8s
#
# The contract is written out in deploy/PORTABILITY.md.

set -euo pipefail

NS="${PROSPECTOR_K8S_NAMESPACE:-prospector}"
NAME="${PROSPECTOR_K8S_NAME:-prospector-engine}"
IMAGE="${PROSPECTOR_K8S_IMAGE:-prospector-engine:latest}"
PVC="${PROSPECTOR_K8S_PVC:-prospector-data}"
PVC_SIZE="${PROSPECTOR_K8S_PVC_SIZE:-20Gi}"
STORAGE_CLASS="${PROSPECTOR_K8S_STORAGE_CLASS:-}"
SECRET="${PROSPECTOR_K8S_SECRET:-prospector-engine-env}"
CTX="${PROSPECTOR_K8S_CONTEXT:-}"
LOAD_CMD="${PROSPECTOR_K8S_LOAD_CMD:-}"
ENGINE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../engine" && pwd)"
REPO_DIR="$(cd "$ENGINE_DIR/../.." && pwd)"

# The context is pinned on every single call, never with `kubectl config use-context`. Switching
# the current context is machine-global state: it outlives this script, and it silently retargets
# any other kubectl the operator runs in another terminal during the cutover window.
_kubectl() {
  if [ -n "$CTX" ]; then kubectl --context "$CTX" -n "$NS" "$@"; else kubectl -n "$NS" "$@"; fi
}

# Exactly one pod, or refuse to name one.
#
# This is the money fence read at query time. deploy/PORTABILITY.md item 1 is "run one container,
# and only one", because two engines keep two spend ledgers and can each spend the full $100 daily
# cap. Returning the first of two pods would let t_exec, t_put and t_pack quietly operate on one
# engine while a second one wrote to the same volume. Two is as much a failure as zero.
_pod() {
  local pods n
  pods="$(_kubectl get pods -l "app=$NAME" --field-selector=status.phase=Running \
            -o jsonpath='{.items[*].metadata.name}' 2>/dev/null || true)"
  n="$(printf '%s' "$pods" | wc -w | tr -d ' ')"
  [ "$n" = "1" ] || { echo "k8s:$NS expected exactly 1 running $NAME pod, found $n" >&2; return 1; }
  printf '%s' "$pods"
}

t_name() { echo "k8s:${CTX:-current}/${NS}"; }

# Everything after phase 4 of the cutover runs with the engine stopped and customers waiting, so
# the LOCAL side is checked here too, before that window opens.
t_preflight() {
  command -v kubectl >/dev/null || { echo "kubectl not installed locally" >&2; return 1; }
  command -v docker >/dev/null || { echo "docker not installed locally (needed to build)" >&2; return 1; }
  [ -f "$REPO_DIR/scripts/store_migrate.py" ] \
    || { echo "no $REPO_DIR/scripts/store_migrate.py — the pack/verify tool is missing" >&2; return 1; }
  # An empty PROSPECTOR_K8S_CONTEXT means "whatever `kubectl config current-context` says", which
  # is machine-global state this adapter does not own and cannot see the history of. Measured on
  # the founder's laptop 2026-08-21: current-context is `docker-desktop`, and `colima start
  # --kubernetes` would set it to `colima` because --activate defaults to true. Either way a
  # cutover drill would run entirely against a laptop and print a green migration proof. Name the
  # context or do not start.
  [ -n "$CTX" ] || {
    echo "PROSPECTOR_K8S_CONTEXT is unset, so every kubectl below would go to the current context" >&2
    echo "  ($(kubectl config current-context 2>/dev/null || echo '<none>')), which is whatever the" >&2
    echo "  last tool to touch ~/.kube/config chose. Set PROSPECTOR_K8S_CONTEXT explicitly." >&2
    return 1; }
  kubectl config get-contexts "$CTX" >/dev/null 2>&1 \
    || { echo "no kubectl context named $CTX" >&2; return 1; }
  _kubectl cluster-info --request-timeout=10s >/dev/null \
    || { echo "cluster unreachable for context ${CTX:-current}" >&2; return 1; }
  # An image tag with no registry host cannot be pulled by any node but the one that built it.
  # On kind or k3s that is expected and the side-load command covers it; without either, the
  # rollout fails with ImagePullBackOff several minutes into the downtime window.
  case "$IMAGE" in
    */*.*/*|*.*/*|*:*/*) ;;
    *) [ -n "$LOAD_CMD" ] || {
         echo "PROSPECTOR_K8S_IMAGE=$IMAGE has no registry host and PROSPECTOR_K8S_LOAD_CMD is unset:" >&2
         echo "  the cluster would have nothing to pull. Set one or the other." >&2
         return 1; } ;;
  esac
}

t_provision() {
  _kubectl create namespace "$NS" --dry-run=client -o yaml | _kubectl apply -f - >/dev/null
  # ReadWriteOnce on purpose: one writer is the contract, and asking for RWX on a default
  # StorageClass gets a PVC that stays Pending forever with no obvious reason why.
  _kubectl apply -f - <<YAML
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: $PVC
spec:
  accessModes: ["ReadWriteOnce"]
  resources:
    requests:
      storage: $PVC_SIZE
$([ -n "$STORAGE_CLASS" ] && echo "  storageClassName: $STORAGE_CLASS")
YAML
}

# $1 = KEY=VALUE file.
#
# --from-env-file takes a PATH, so no secret value is ever an argument: nothing lands in `ps`
# output or in a shell history file. Same rule as deploy/runners.sh.
t_secrets() {
  _kubectl create secret generic "$SECRET" --from-env-file="$1" \
    --dry-run=client -o yaml | _kubectl apply -f - >/dev/null
}

t_release() {
  # The build CONTEXT is the repository root, not deploy/engine. Every COPY in the Dockerfile is
  # written repo-root-relative because that is the only way one Dockerfile pulls in both the
  # engine and the Next.js console. See the same note in deploy/targets/fly.sh.
  docker build -f "$ENGINE_DIR/Dockerfile" -t "$IMAGE" "$REPO_DIR"
  if [ -n "$LOAD_CMD" ]; then
    # shellcheck disable=SC2086
    $LOAD_CMD "$IMAGE"
  else
    docker push "$IMAGE"
  fi
}

# THE SINGLE-INSTANCE MONEY FENCE, and the one place Kubernetes fights this contract.
#
# A Deployment's DEFAULT strategy is RollingUpdate, which starts the replacement pod BEFORE the
# old one terminates. So the default setting of the default workload type breaks
# deploy/PORTABILITY.md item 1 on every release: two engines, two spend ledgers, twice the $100
# daily cap, for as long as the handover takes. `Recreate` is what holds the rule — old pod gone,
# then new pod.
#
# It is also the only strategy that works against a ReadWriteOnce volume. Under RollingUpdate the
# new pod sits Pending on "Multi-Attach error for volume" until the rollout times out, which reads
# like a broken image rather than a wrong strategy. One setting, two failures.
#
# The Service is ClusterIP, so 8601 and 8611 are reachable from inside the cluster and nowhere
# else. The operator reaches them with `kubectl port-forward`, which is this platform's `fly proxy`.
t_start() {
  _kubectl apply -f - <<YAML
apiVersion: apps/v1
kind: Deployment
metadata:
  name: $NAME
  labels: { app: $NAME }
spec:
  replicas: 1
  strategy:
    type: Recreate
  selector:
    matchLabels: { app: $NAME }
  template:
    metadata:
      labels: { app: $NAME }
    spec:
      containers:
        - name: engine
          image: $IMAGE
          imagePullPolicy: IfNotPresent
          envFrom:
            - secretRef: { name: $SECRET }
          ports:
            - { containerPort: 8601 }
            - { containerPort: 8611 }
          volumeMounts:
            - { name: data, mountPath: /data }
      volumes:
        - name: data
          persistentVolumeClaim:
            claimName: $PVC
---
apiVersion: v1
kind: Service
metadata:
  name: $NAME
spec:
  type: ClusterIP
  selector: { app: $NAME }
  ports:
    - { name: console, port: 8601, targetPort: 8601 }
    - { name: ops, port: 8611, targetPort: 8611 }
YAML
  _kubectl scale deploy "$NAME" --replicas=1 >/dev/null
  # `apply` returns as soon as the API server has the object, not when anything is running. The
  # next thing the cutover does is exec into the pod. Started means started.
  _kubectl rollout status "deploy/$NAME" --timeout=300s
}

t_stop() {
  _kubectl get deploy "$NAME" >/dev/null 2>&1 || return 0
  _kubectl scale deploy "$NAME" --replicas=0 >/dev/null
  # `scale` returns when the SPEC is updated, not when the pod is gone. The cutover packs the
  # store in the phase straight after this one, and a pod still flushing writes produces a
  # tarball that verifies clean and is missing its last rows.
  local i=0
  while [ "$(_kubectl get pods -l "app=$NAME" -o name 2>/dev/null | wc -l | tr -d ' ')" != "0" ]; do
    i=$((i + 1))
    [ "$i" -le 90 ] || { echo "k8s:$NS pods for $NAME still present 180s after scale to 0" >&2; return 1; }
    sleep 2
  done
}

t_exec() { _kubectl exec "$(_pod)" -- /bin/sh -lc "$*"; }

# $1 = local file, $2 = absolute path inside the container.
#
# `kubectl cp` streams a tar and exits 0 on a short read — a truncated copy prints a warning to
# stderr and reports success, which is the same trap `fly ssh sftp` set on cutover attempt 6.
# So: clear the destination first, then prove the byte count from inside the pod.
t_put() {
  local pod want got
  pod="$(_pod)"
  want="$(wc -c < "$1" | tr -d ' ')"
  _kubectl exec "$pod" -- /bin/sh -lc "rm -f $(printf '%q' "$2")"
  _kubectl cp "$1" "$pod:$2"
  got="$(_kubectl exec "$pod" -- /bin/sh -lc "wc -c < $(printf '%q' "$2")" | tr -d ' \r')"
  [ "$got" = "$want" ] \
    || { echo "k8s:$NS put $2 landed $got bytes, sent $want" >&2; return 1; }
}

# $1 = local .tar.gz to write. Used when Kubernetes is the SOURCE, i.e. when we leave it.
# `kubectl cp` truncates silently in this direction too, so the byte count is proved again.
t_pack() {
  local pod want got
  pod="$(_pod)"
  _kubectl exec "$pod" -- /bin/sh -lc \
    "python /app/scripts/store_migrate.py pack /data/handover.tar.gz --store /data/store"
  want="$(_kubectl exec "$pod" -- /bin/sh -lc "wc -c < /data/handover.tar.gz" | tr -d ' \r')"
  _kubectl cp "$pod:/data/handover.tar.gz" "$1"
  got="$(wc -c < "$1" | tr -d ' ')"
  [ "$got" = "$want" ] \
    || { echo "k8s:$NS pack pulled $got bytes of a $want byte tarball" >&2; return 1; }
  _kubectl exec "$pod" -- /bin/sh -lc "rm -f /data/handover.tar.gz"
}

t_logs() { _kubectl logs -f "deploy/$NAME"; }

# Is this cluster actually carrying the load right now? deploy/decommission.sh asks before it
# turns the other platform off for good. A ready pod is not enough on its own: a pod that came up
# against a fresh empty PVC is Ready and serving nothing, so the ledger is checked too.
#
# `readyReplicas` must equal 1 exactly. Two is a failure here for the same reason it is in _pod:
# it means two engines are spending against one cap.
t_health() {
  local ready
  ready="$(_kubectl get deploy "$NAME" -o jsonpath='{.status.readyReplicas}' 2>/dev/null || true)"
  ready="${ready:-0}"
  [ "$ready" = "1" ] \
    || { echo "k8s:$NS deployment $NAME has $ready ready replicas, want exactly 1" >&2; return 1; }
  _kubectl exec "$(_pod)" -- /bin/sh -lc "test -f /data/store/prospector.jsonl" \
    || { echo "k8s:$NS is up but has no ledger at /data/store/prospector.jsonl" >&2; return 1; }
  echo "k8s:${CTX:-current}/$NS running one replica, ledger present"
}

# Run a verb directly: `bash deploy/targets/<name>.sh t_release`.
#
# Without this, running the file instead of sourcing it defines every function, reaches the end
# and exits 0 - a silent success that deploys nothing. Measured 2026-08-18: three consecutive
# `bash fly.sh t_release` calls each exited 0 with no output while `fly releases` never moved off
# v3. The guard means `source`ing it, which deploy/cutover.sh does, still runs nothing.
if [ "${BASH_SOURCE[0]}" = "${0}" ]; then
  verb="${1:?usage: $(basename "${BASH_SOURCE[0]}") <verb> [args...]}"
  case "$verb" in
    t_*) ;;
    *) echo "unknown verb: $verb (verbs start with t_)" >&2; exit 2 ;;
  esac
  declare -F "$verb" >/dev/null || { echo "no such verb: $verb" >&2; exit 2; }
  shift
  "$verb" "$@"
fi
