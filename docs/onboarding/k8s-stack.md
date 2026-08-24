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

`deploy/k8s/policies/estate-standards.yaml` is seven Kyverno policies, all set to `Enforce`, and
each one is an incident this estate has actually had rather than a best practice copied from a blog:

1. **money-rail-single-writer** — refuses two replicas or a RollingUpdate on anything labelled
   `prospector.estate/single-writer`. SQLite has exactly one writer. Two engines is two spend ledgers.
2. **no-optional-secret-references** — refuses `optional: true` on a secret. This is the 2026-08-24
   incident written as a rule: a `required: false` let the API start half-configured.
3. **no-literal-credentials-in-pod-spec** — refuses a value under a name matching `*SECRET*`,
   `*PASSWORD*`, `*_TOKEN` and four more. LAW 21, enforced by the API server rather than by memory.
4. **images-must-be-traceable** — no `:latest`. You cannot roll back to a tag that moves.
5. **workloads-declare-what-they-need** — a memory request and limit are required. A CPU limit is
   deliberately **not** required, because a CPU limit throttles rather than protects.
6. **secure-by-default** — no privileged containers, with a labelled escape hatch that is countable.
7. **serving-workloads-must-be-probed** — anything serving traffic needs both probes. Without a
   readiness probe, self-healing has nothing to act on, which is how the rehearsal box reported
   HTTP 000 while every container claimed to be started.

Six of the seven exclude `kube-system`, `kube-public`, `kube-node-lease`, `kyverno` and
`cert-manager`, so the fence cannot take the cluster's own components down.

## Where it lives

- `deploy/k8s/policies/estate-standards.yaml` — the standards.
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
