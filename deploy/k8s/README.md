# `deploy/k8s` — what a cluster is handed, and how it gets there

The standards, the reasoning and the measurements behind every choice here are in
`docs/K8S_STANDARDS_AND_WAYS_OF_WORKING.md`. This file is the operating detail.

## The shape

```
base/          the namespace, its security level, and four of the five workloads. True everywhere.
policies/      admission control: the upstream Kyverno library, pinned, plus two estate policies.
overlays/      staging and production. Image tags, hostnames, secret references. Never a policy.
argocd/        one ApplicationSet owning both clusters.
```

## The two commands

Everything here is built by `kubectl kustomize`, which is part of kubectl. No tool to install.

```bash
kubectl kustomize deploy/k8s/overlays/staging
kubectl kustomize deploy/k8s/overlays/production
```

Both fetch the pinned upstream policy library over the network, so the first run is slow and needs
to be online.

## What that build actually contains, measured 2026-08-24

```
$ kubectl kustomize deploy/k8s/overlays/production | grep -c '^kind: ClusterPolicy'
26
$ kubectl kustomize deploy/k8s/overlays/production | grep -o 'validationFailureAction: [A-Za-z]*' | sort | uniq -c
  26 validationFailureAction: Enforce
$ kyverno apply deploy/k8s/policy-tests/policies.generated.yaml --resource /tmp/production-workloads.yaml
Applying 87 policy rule(s) to 15 resource(s)...
pass: 91, fail: 0, warn: 0, error: 0, skip: 0
```

The fifteen documents are the namespace and the four workloads `base/` now declares: a PVC, a
Deployment and a Service each for the engine and the store API; a Deployment, a Service and a
PodDisruptionBudget for the storefront; and a ClusterIssuer, a Gateway and three HTTPRoutes for the
edge. Staging grades identically: `87 rules, 91 passes, 0 fails`, measured the same way on
2026-08-24. That equality is the point of the two overlays being the same files.

**Read the two numbers together, because 15 documents and 91 passes is the same 91 the ten
documents scored.** The five edge documents contributed nothing. No policy in the set of 26 matches
a `Gateway`, an `HTTPRoute` or a `ClusterIssuer` — every one of them is about pods. So the edge is
in the count because a build that silently dropped `edge.yaml` must fail the gate, not because
anything graded it. Saying it the other way round would be the "grade a proxy" mistake.

26 policies. 24 of them are maintained by the Kyverno project; 2 are this estate's, and
`policies/RETIRED.md` is the row-by-row account of which six hand-written ones were deleted and what
replaced each. Every one is `Enforce` — upstream ships `Audit`, and `policies/enforce.yaml` flips
the whole build, because an audit-only rule is a log line nobody reads.

Adopting the library gained three rules the estate had never thought to write:
`require-drop-all`, `require-ro-rootfs`, `disallow-default-namespace`.

## Two layers of pod security, on purpose

`base/namespace.yaml` sets `pod-security.kubernetes.io/enforce: restricted`. Pod Security Admission
is built into Kubernetes and needs no controller, so it keeps working on a cluster where Kyverno is
down or not yet installed. Kyverno's `pod-security/restricted` bundle covers the same ground and
says WHICH field of WHICH container broke the rule. LAW 15 wants evidence from two angles: this is
a fence and a witness, not a duplicate.

## Why the upstream library is pinned to a SHA

`kyverno/policies` publishes no releases — measured 2026-08-24,
`GET /repos/kyverno/policies/releases/latest` returns 404. `?ref=main` would mean the cluster's
admission rules change on somebody else's merge, with no review here and no way to say when they
changed. The pin is `ef9843f08d25b3555fe69616f8612c9f915af5d4`, `main` at 2026-07-04T06:01:43Z.
Moving it is a reviewed commit like any other.

## Staging and production are the same files

The overlays change image tags, replica counts, hostnames and which Secret is referenced. They do
not change a policy, and a pull request that makes them differ on a policy should be refused. A
staging cluster with softer rules admits manifests production refuses, which turns a caught problem
into an outage — the one failure a staging cluster exists to prevent.

## What has not been proved

Honest state, so nobody reads this directory as a report of something running:

- **No cluster has ever applied any of this.** The build is green; the cluster is not there. Both
  environments are rented boxes, which is money leaving the account and the founder's decision under
  LAW 5.
- **No policy has been shown to refuse anything ON A CLUSTER.** That sentence used to have no
  qualifier. Since 2026-08-24 the policies are proved to DECIDE, offline, by the same admission
  engine the cluster runs — see "The policies decide" below. What is still unproved is everything
  that needs an API server: that the webhook is reachable, that the policies were installed at all,
  and that the cluster is not quietly running them in Audit. Register row F-47 stays `◐`; the
  offline half is F-55 and is `✅`.
- **`base/` declares the namespace, the engine, the store API, the storefront and the edge. The CI
  runner is the one service left.** Register row F-39. **A correction, because this file said
  otherwise until 2026-08-24**: the remaining services were never "generated inline by
  `deploy/targets/k8s.sh`". That script emits exactly three documents — a PersistentVolumeClaim, a
  Deployment and a Service, all for the engine — and mentions no storefront, no API, no edge and no
  runner. The runner has no Kubernetes representation of any kind, which is worse than a bad one.
- **The edge is NOT the Caddy container ported across, and that decision has receipts.**
  `deploy/compose/docker-compose.yml` runs `caddy:2.10-alpine` with a hand-written Caddyfile.
  Lifting it into a Deployment was the smallest diff and the wrong one, so the research ran first
  and is on the record in `~/dev/code/crew/science/RESEARCH-LEDGER.jsonl`. What it found:
  `gh api repos/kubernetes/ingress-nginx --jq .archived` returns **`true`**, last push
  2026-03-23 — the Ingress API's flagship controller is retired, its successor InGate never
  shipped, and the Kubernetes Steering and Security Response Committees name **Gateway API** as
  the migration path. So `base/edge.yaml` is a Gateway plus three HTTPRoutes plus a cert-manager
  ClusterIssuer. `gatewayClassName` is the only controller-specific string in the file; k3s ships
  Traefik, and Envoy Gateway is one word away. The Caddyfile's two site blocks, its
  `X-Forwarded-Proto` header, its 60s Stripe-webhook timeout and its `force_https` all have a
  named counterpart there. **Compose keeps Caddy unchanged** — on a plain Docker host with no
  cluster it is the right answer, and the two substrates are allowed to differ.
  **What is NOT true: no cluster has the Gateway API CRDs or cert-manager installed**, so this is
  admissible YAML that nothing reconciles, and per `apis/v1/shared_types.go:468-478` a controller
  may accept an HTTPRoute and mark it `PartiallyInvalid` with reason `UnsupportedValue` rather
  than refuse it — the `timeouts` block is `Support: Extended` and is exactly the field that can
  be dropped that way.
- **The storefront is the only workload here that may lose a pod without losing the service, and
  it is the only one with a PodDisruptionBudget.** It owns no database, so it runs two replicas,
  rolls rather than Recreates, and carries no `prospector.estate/single-writer` label. The engine
  and the API deliberately get no budget: `minAvailable: 1` on a `replicas: 1` workload blocks a
  drain forever instead of protecting anything, which LAW 38 grades as an outage. It also mounts
  no Secret, and that is a property of the image rather than an omission — every `NEXT_PUBLIC_*`
  value is a build argument baked in at `docker build`, which is what `NEXT_PUBLIC_` means. The
  consequence worth knowing: a storefront built for staging is a DIFFERENT IMAGE from the one built
  for production, so the two overlays cannot share a tag the way the engine's and the API's can.
  **What is NOT proved is the same sentence as the API's**: nothing has run
  `store_platform/src/Store.Web`'s image as `runAsUser 10001` with a read-only root, and its
  Dockerfile has no `USER` line.
- **The store API's manifest is admitted, and the application change it needed is written and
  tested.** `secrets-not-from-env-vars` refuses a credential in the pod environment, and the compose
  file supplies all seven of the API's secrets that way, so the API had to learn to read secrets as
  files. It reads them with `Microsoft.Extensions.Configuration.KeyPerFile`, which is in the
  `Microsoft.AspNetCore.App` shared framework — no package was added and no resolver was written.
  `Store.Api/Infrastructure/FileSecrets.cs` adds only the refusal on a missing or empty mount, and
  reads the same `PROSPECTOR_SECRETS_DIR` the engine reads. Eight tests in
  `Store.Tests/Infrastructure/FileSecretsTests.cs` prove the four refusals and the four things the
  manifest bets on: `Jwt__SigningKeyPem` becomes `Jwt:SigningKeyPem`, a Kubernetes projected-volume
  symlink farm yields the keys and none of the `..`-prefixed machinery, a trailing newline is not
  part of the value, and a mounted file beats an environment variable of the same name.
  **What is NOT proved: nothing has run the API image as `runAsUser 10001` with a read-only root**,
  the way the engine was drilled. Its Dockerfile has no `USER` line.
- **The engine manifest is admissible, and one of its two gaps is closed.** `prospector/file_secrets.py`
  reads the file-mounted secrets that `secrets-not-from-env-vars` forces and puts them in
  `os.environ` before any module runs, so the 30 files that read a credential from the environment
  needed no change.
- **The non-root drill has now run, and the image fails it as shipped.** 2026-08-24, the real
  image under `--user 10001:10001 --read-only`: supervisord refused with `Can't drop privilege as
  nonroot user` because `deploy/engine/supervisord.conf` sets `user=root`, `HOME` was `/` which
  uid 10001 cannot write, and `.next/cache` was root-owned and unwritable. The last two are fixed
  in `base/engine.yaml`. **The first is an image change and is not made yet**, because dropping
  `user=root` means the image runs as 10001 under `docker compose` too, where `./data` on the host
  is not owned by 10001. With all three worked around, supervisord and eight of nine programs
  reached RUNNING with no permission or read-only error anywhere in the log.
- **The ops console under those constraints IS now proved, and it was not this morning.** The
  earlier drill ran `next start` from a shell inside the container and saw an empty log, nothing
  listening and no process. Re-run 2026-08-24 with node as the container's PID 1 — `--user
  10001:10001 --read-only`, tmpfs at `/tmp` and `.next/cache`, `HOME=/tmp` — against a freshly
  built image: `Next.js 16.3.1`, `Ready in 2.7s`, `Running=true ExitCode=0`, and `GET /` on the
  published port returned **307**. A control arm of the same image and command with no `--user`
  and no `--read-only` returned **307** in 2.1s, so the status is the app's answer and not a
  symptom of the constraints. A Kubernetes `httpGet` probe passes on 200–399, and both probes in
  `base/engine.yaml` ask for exactly that path on exactly that port.
- **What is still unproved is the path the pod takes, and it is blocked on one line.** The pod
  runs the image's own entrypoint, so supervisord starts the console rather than Docker. Drilled
  under the same securityContext: `ExitCode=2`, `Error: Can't drop privilege as nonroot user`.
  That is the `user=root` blocker above, measured twice now, and it is the only thing between the
  proved process and a proved pod.
- **`argocd/applicationset.yaml` has a placeholder for the production API URL**, because there is no
  production cluster to name.

## The policies decide, and you can watch them do it without a cluster

```
kubectl kustomize deploy/k8s/policies > deploy/k8s/policy-tests/policies.generated.yaml
kyverno test deploy/k8s/policy-tests          # 13 assertions
kyverno apply deploy/k8s/policy-tests/policies.generated.yaml \
  --resource deploy/k8s/policy-tests/admitted.yaml   # must be 0 failures
```

The Kyverno CLI runs the same admission engine the cluster runs, so no API server is involved. Pin
it to the version in `KYVERNO_VERSION` in `deploy/rehearse_cluster.sh`, not to latest: a CLI on a
different engine version answers a different question than the one the cluster will be asked.

`base/engine.yaml` is graded by the same engine, in CI gate 6, in both overlay builds. What it
replaces was refused by ten of these policies — see that file's header.

`policy-tests/refused.yaml` holds eleven manifests, each a copy of `admitted.yaml` with exactly one
thing wrong. One violation per manifest is the point — a fixture that breaks five rules at once
proves only that *something* refused it, and would still pass on the day four of the five policies
silently stopped loading. `kyverno-test.yaml` asserts the pairing: this resource, refused by this
rule of this policy.

`admitted.yaml` is the other half, and it is also the reference shape. `base/engine.yaml` was
written from it on 2026-08-24; the shop, api, web and edge follow the same way.

**Three things measured on 2026-08-24 that anyone running these commands will hit:**

1. **`kyverno test` lies in its summary and in its exit code.** With one assertion deliberately
   violated it printed `Test Summary: 13 tests passed and 0 tests failed` and exited **0**, while
   its own `REASON` column on that row read `Want fail, got pass`. The verdict is in `REASON`. The
   CI gate parses `-o json` and grades that field; it never trusts the exit code.
2. **The CLI silently loads zero rules from a file containing a non-policy document.** Handed an
   overlay build, which also emits the Namespace, it reported `Applying 0 policy rule(s)` and then
   `pass: 0, fail: 0, error: 0` — which reads exactly like success. Build the `policies`
   kustomization, never an overlay, and assert the rule count.
3. **`secrets-not-from-env-vars` forbids `envFrom.secretRef` outright**, not only the optional form,
   and it forbids `env[].valueFrom.secretKeyRef` too. Secrets must be mounted as files. The first
   draft of `admitted.yaml` used `envFrom` — which is how the whole estate does it in compose today
   — and was refused. Adopting an upstream library means adopting rules nobody here thought of, and
   this is the first one that bit, and it cost something real rather than being weakened:
   `base/engine.yaml` mounts its secrets as files, and `prospector/file_secrets.py` was written to
   read them. The estate is better off — a credential is now a file with an owner and a mode
   rather than a string in a process listing — and it would not have been written if the fence had
   been softened the first time it refused work.
