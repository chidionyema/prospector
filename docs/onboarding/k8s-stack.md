# Onboarding — the tooling, and why each piece and not its rival

## What it is for

This is the answer to "what tooling are we using", written down once so nobody has to ask again and
so a buyer can check every line themselves without being walked through it.

Every row was chosen on evidence gathered on 2026-08-24 from two independent sources that can
disagree: the CNCF landscape file (`cncf/landscape/landscape.yml`, 1,133,298 bytes) for maturity,
and the CLOMonitor API for the health score. Licences came from the GitHub API, authenticated,
because an unauthenticated request from this sandbox returns every field as `?` and that would have
been an invented answer. The full row is in `~/dev/code/crew/science/RESEARCH-LEDGER.jsonl`.

## The stack

| Layer | What we use | Maturity | Licence | Why not the obvious rival |
|---|---|---|---|---|
| Kubernetes distribution | **k3s** (k3d locally) | CNCF Sandbox | Apache-2.0 | Talos is the better machine and we are not using it. Talos has no SSH and no shell by design, which is exactly right for a team with a platform engineer and exactly wrong for one operator with no prior Kubernetes experience on the night something breaks. Talos is the named upgrade once k3s has run a quarter. It is also **not a CNCF project at all**, and its licence is MPL-2.0 while its management plane Omni is NOASSERTION (BUSL), which LAW 40 test 3 fails on. |
| GitOps and self-healing | **Argo CD** | CNCF Graduated | Apache-2.0 | Flux is graduated too and is a fine tool. Argo wins on two specifics: `selfHeal: true` is the literal thing that was asked for in one line, and Argo ships a UI a stranger can open, which LAW 41 requires and Flux structurally does not provide. Flux is the named replacement if Argo stops being viable. |
| Standards enforcement | **Kyverno** | CNCF Graduated 2026-03-24, CLOMonitor 93.75 | Apache-2.0 | Gatekeeper (CLOMonitor 89.58) needs Rego, a second language nobody here writes. Kyverno policies are ordinary Kubernetes YAML. Gatekeeper wins only where the same Rego is reused against Terraform and APIs, which is not our case. Note the estate already runs Rego elsewhere — `policy/risk_register.rego` with conftest — so this is a per-surface call, not a religion. |
| TLS certificates | **cert-manager** | CNCF Graduated, CLOMonitor 95.65 | Apache-2.0 | Nothing else is close. Caddy does this today inside the edge container and would keep working; cert-manager moves it to where the rest of the cluster's config lives. |
| Backup and restore | **Velero** | CNCF **Sandbox**, CLOMonitor 83.6 | Apache-2.0 | Stated as Sandbox everywhere it is mentioned, deliberately. A design that called Velero "CNCF-backed" without the tier would be the exact overclaim this estate keeps producing. For the SQLite money rail the real mechanism is Litestream, below; Velero covers cluster objects and volumes. |
| SQLite replication | **Litestream** | not a CNCF project | Apache-2.0 | Streams the store to object storage continuously. This is what makes a single-writer database survivable rather than a single point of loss. |
| Secrets | **External Secrets Operator** | CNCF **Sandbox**, CLOMonitor 96.9 | Apache-2.0 | The highest CLOMonitor score in the whole stack and still Sandbox, which is a good illustration of why one number is never the answer. |
| Node reboots | **Kured** | not CNCF | Apache-2.0 | Small, boring, does one thing. |
| Cloud resources | **Crossplane** | CNCF Graduated, CLOMonitor 88.54 | Apache-2.0 | Not adopted yet. Named here because it and Cluster API are complementary rather than competitors, and the estate has previously assumed they compete. |

Star counts on 2026-08-24, for weight rather than for quality: argo-cd 23,978; k3s 33,792;
cert-manager 14,045; litestream 14,290; crossplane 11,971; talos 11,005; velero 10,252; flux2 8,367;
kyverno 8,061; external-secrets 6,807; gatekeeper 4,267; kured 2,566; omni 1,354.

## What it costs

The tooling is £0. Every component above is Apache-2.0 or equivalent, self-hosted, with no account
and no card.

The node is the cost. Hetzner with k3s comes to roughly €14 a month from one published source and
€10 from a second. **Neither figure has been measured by this estate** and both are stated as
somebody else's number until a box is actually rented.

## What it watches or changes

**This section changed on 2026-08-24, and the change is the interesting part.** It used to describe
seven Kyverno policies written by hand in this repo. Six of them restated something the Kyverno
project already publishes and maintains, so those six are gone and the upstream library is pulled in
instead, pinned to a commit. `deploy/k8s/policies/RETIRED.md` is the row-by-row account of which
policy was replaced by what, measured with `gh api` rather than remembered.

What a cluster is handed now, measured the same day:

```
$ kubectl kustomize deploy/k8s/overlays/production | grep -c '^kind: ClusterPolicy'
26
$ kubectl kustomize deploy/k8s/overlays/production | grep -o 'validationFailureAction: [A-Za-z]*' | sort | uniq -c
  26 validationFailureAction: Enforce
```

24 of those 26 are maintained by the Kyverno project. Adopting the library gained three rules the
estate had never thought to write: `require-drop-all`, `require-ro-rootfs` and
`disallow-default-namespace`. It also cost nothing to maintain, which is the whole argument.

Two policies stayed hand-written, in `deploy/k8s/policies/estate.yaml`, because each encodes
something true about this business that no upstream library could know:

1. **money-rail-single-writer** — refuses two replicas or a RollingUpdate on anything labelled
   `prospector.estate/single-writer`. SQLite has exactly one writer. Two engines is two spend ledgers,
   each honouring the daily cap separately, so a $100 cap silently becomes $200.
2. **no-optional-secret-references** — refuses `optional: true` on a secretRef. This is the
   2026-08-24 incident written as a rule: compose's `required: false` let a box start carrying none
   of its 24 settings while the deploy script reported success. Searched upstream and found no
   equivalent; if one appears, this one retires too.

Both exclude `kube-system`, `kube-public`, `kube-node-lease`, `kyverno` and `cert-manager`, so the
fence cannot take the cluster's own components down.

Underneath all of that, `deploy/k8s/base/namespace.yaml` sets
`pod-security.kubernetes.io/enforce: restricted`. Pod Security Admission is built into Kubernetes and
needs no controller, so it keeps refusing privileged pods on a cluster where Kyverno is down or not
yet installed. The overlap with Kyverno is deliberate: a fence with no moving parts, and a witness
that says which field of which container broke the rule.

## Where it lives

- `deploy/k8s/README.md` — the shape, the two commands, and what has NOT been proved.
- `deploy/k8s/policies/` — the upstream library pinned to a SHA, the Enforce patch, the two estate
  policies, and `RETIRED.md`.
- `deploy/k8s/overlays/{staging,production}/` — the two environments. They differ on image tags and
  hostnames, never on a policy.
- `deploy/k8s/argocd/applicationset.yaml` — one object owning both clusters. Nothing has run it.
- `.github/workflows/k8s-manifests.yml` — the five gates that make the above enforced rather than
  merely written down. Four grade the built manifests; the fifth watches the policies decide.
- `deploy/k8s/policy-tests/` — eleven manifests each with exactly one thing wrong, one manifest that
  is compliant, and Kyverno's own test format asserting which rule of which policy catches which. It
  runs offline, so knowing whether a standard works no longer waits on a cluster existing.
- `docs/K8S_STANDARDS_AND_WAYS_OF_WORKING.md` — the research, the CNCF measurements, and the
  processes.
- `deploy/rehearse_cluster.sh` — the drill that proves them.
- `deploy/targets/k8s.sh` — the adapter that deploys the engine, written 2026-08-20 and never once
  executed against a cluster until this drill ran it.
- `~/dev/code/crew/science/RESEARCH-LEDGER.jsonl` row 14 — the sources and the decision.

## How to turn it off

```
deploy/rehearse_cluster.sh down
```

Nothing is scheduled and nothing listens afterwards. Nothing on the estate depends on the cluster
existing. Nothing here has touched Fly, DNS, or the live shop.

To stop a single standard enforcing without deleting it, set its `validationFailureAction` to
`Audit`. It then records violations and refuses nothing.

## How to turn it back on

```
deploy/rehearse_cluster.sh            # cluster, standards, adapter, self-healing, in one command
deploy/rehearse_cluster.sh policy     # just the standards, both ways
deploy/rehearse_cluster.sh heal       # just the recovery timing
deploy/rehearse_cluster.sh status     # what is true right now
```

## What goes wrong

**"the local docker daemon is not running".** k3d runs k3s inside Docker. Start Docker.

**`kyverno test` says everything passed when it did not.** Measured 2026-08-24 on v1.16.1: with one
assertion deliberately violated it printed `Test Summary: 13 tests passed and 0 tests failed` and
exited **0**, while its own `REASON` column on that row read `Want fail, got pass`. Read `REASON`,
via `-o json`, and never the summary or the exit code. The CI gate does this; a person running the
command by hand will be told the wrong thing.

**A policy refuses something correct.** That is an outage, not a false positive, and it is graded as
one. The drill proves every standard both ways in the same run for this reason: eight refusals it
must make and five admissions it must not block. A standard that fails either half fails the drill.

**kubectl version skew.** The kubectl on this laptop is v1.27.2 from Docker Desktop and k3d brings
up k3s v1.35. Eight minors against a supported window of one, and the failure mode is dishonest:
an old client silently drops fields it does not know about, so a manifest applies without the
setting that mattered. The drill downloads a matching kubectl into its own cache and puts it first
on PATH. It does not replace the one on PATH, because that is machine-global state other things
depend on.

**The image import is slow.** `prospector-engine:local` is 2.62GB and goes into the cluster's own
store rather than through a registry, which is what keeps a registry account out of the migration
path.

**A green drill is not a green migration.** What it cannot prove: multi-node scheduling, a real
cloud's storage class, network latency, a Let's Encrypt issuance, and live Stripe. Those need money
and a real node. Everything before them is proved here.
