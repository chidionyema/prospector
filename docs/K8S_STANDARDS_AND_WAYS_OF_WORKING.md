# Kubernetes — the standards we follow, and how we work

Founder, 2026-08-24, verbatim: *"sicne we are on k, we should underdtnd what is possobe , it is
nature platfron, never reinvent the wheel"*, then *"we eed to follow stadrds"*, then *"not write
custon scripts for production cluster"*, *"reserch what always works"*, *"we need proper standrads,
defined processes and ways of woking"*, and *"staging and prod cluster"*.

He is right, and this document exists because he caught something specific. Earlier the same night I
had written a bash function that killed a container to test resilience, and seven hand-written policy
files. Kubernetes and the CNCF already standardise most of both. What follows is what the platform
gives us, measured rather than remembered, and what we are allowed to write ourselves.

---

## 0. The rule

**Nothing custom runs against staging or production.** Every change to either cluster is a
declarative resource, in git, applied by a standard controller. The only command a person runs is
`git push`.

Custom scripts are allowed in exactly one place: a developer's own laptop, for a local rehearsal
cluster that no customer can reach. `deploy/rehearse_cluster.sh` lives under that exemption and must
never gain a production code path.

**Why this is a rule and not a preference.** A custom script is a second implementation of something
already tested by thousands of operators, and it is tested by nobody. When it fails at 2am it fails
in a way no search result covers, and the only person who can read it is whoever wrote it. On
2026-08-24 a custom bash wrapper around `k3d` deleted a working cluster because its timeout expired
while the control plane was still starting. The cluster was fine. The wrapper was the outage.

---

## 1. How these were chosen

Two sources that can disagree, both re-read on 2026-08-24:

- **`cncf/landscape` `landscape.yml`**, 1,133,298 bytes, for the maturity tier. This is the CNCF's
  own record.
- **The CLOMonitor API** for a health and best-practice score.
- Licence and star counts from an **authenticated** `gh api` call. An unauthenticated request from
  this sandbox returns every field as `?`, and reporting that would be an invented answer.

**A limit of the method, stated because it bit me.** The landscape lists a project once, under its
parent. A first parse looked for `project:` *below* each `repo_url:` and reported Argo CD as not a
CNCF project, which is false. `project:` sits *above*. Sub-projects such as Argo Rollouts, Gatekeeper,
Kustomize and Cluster API have no entry of their own; they inherit their parent's tier. Where the
table below says "via parent" that is what it means.

| Tool | Serves | Maturity | CLOMonitor | Stars | Licence |
|---|---|---|---|---|---|
| **Argo CD** | GitOps delivery, drift self-heal | **Graduated** | 89.47 (Argo) | 23,978 | Apache-2.0 |
| Flux | the rival | **Graduated** | no entry | 8,367 | Apache-2.0 |
| **Argo Rollouts** | canary, automatic rollback | Graduated via Argo | — | 3,560 | Apache-2.0 |
| **Kyverno** | policy as Kubernetes YAML | **Graduated** | 93.75 | 8,061 | Apache-2.0 |
| **kyverno/policies** | the official policy library | part of Kyverno | — | 500 | Apache-2.0 |
| Gatekeeper | policy as Rego | Graduated via OPA | — | 4,267 | Apache-2.0 |
| **Litmus** | chaos engineering | **Incubating** | no entry | 5,600 | Apache-2.0 |
| **Chaos Mesh** | chaos engineering | **Incubating** | 40.0 | 7,853 | Apache-2.0 |
| **Sonobuoy** | CNCF conformance suite | via VMware | — | 3,051 | Apache-2.0 |
| **kube-bench** | CIS Kubernetes Benchmark | via Aqua | — | 8,148 | Apache-2.0 |
| Trivy | image and manifest scanning | via Aqua | — | 37,579 | Apache-2.0 |
| Falco | runtime security detection | **Graduated** | 78.12 | 9,294 | Apache-2.0 |
| **Velero** | backup and restore | CNCF | 73.96 | 10,252 | Apache-2.0 |
| **Gateway API** | edge routing, the Ingress API's successor | SIG-Network, v1.6.1 | — | 2,976 | Apache-2.0 |
| **Traefik** | the Gateway API controller k3s already ships | not CNCF | — | 64,556 | MIT |
| Envoy Gateway | the named replacement controller | CNCF via Envoy | — | 2,975 | Apache-2.0 |
| ingress-nginx | the retired rival | **ARCHIVED 2026-03** | — | 19,480 | Apache-2.0 |
| **cert-manager** | TLS issuance and renewal | **Graduated** | ~100 | 14,045 | Apache-2.0 |
| External Secrets | secrets from a real store | **Sandbox** | 96.88 | 6,807 | Apache-2.0 |
| **Kustomize** | per-environment overlays | Graduated via Kubernetes | — | 12,143 | Apache-2.0 |
| Prometheus | metrics and alerting | **Graduated** | — | — | Apache-2.0 |

---

## 2. What I was about to reinvent

This table is the point of the document. Left column is what a custom script would have done. Right
column is what the platform already does, better, and with somebody else maintaining it.

| The need | What I hand-wrote | The standard that replaces it |
|---|---|---|
| Pod security baseline | 3 Kyverno policies of my own: no privileged containers, no literal credentials, declare resources | **Pod Security Admission**, built into Kubernetes since 1.25. One label on a namespace: `pod-security.kubernetes.io/enforce=restricted`. No controller, no CRD, no install |
| Common best-practice policy | the rest of `estate-standards.yaml` | **`kyverno/policies`**, the official library. `pod-security/baseline` and `pod-security/restricted` each carry a `kustomization.yaml` and install as one line. `best-practices/` does **not** — measured, it holds twenty policy directories and no kustomization — so those are referenced one file at a time, which is better anyway: four of the twenty mutate workloads rather than refuse them |
| Chaos testing | `cmd_resilience`, which SIGKILLs a container from bash | **Litmus** or **Chaos Mesh**, both CNCF Incubating. Experiments are custom resources in git, scheduled, with a blast radius and a steady-state hypothesis |
| Waiting for readiness | a `wait_for_api` polling loop | **`kubectl wait --for=condition=...`**, and for workloads the readiness probe the platform already runs |
| Is this cluster correct | nothing | **Sonobuoy**, which runs the official CNCF conformance suite non-destructively |
| Is this cluster hardened | nothing | **kube-bench**, the CIS Kubernetes Benchmark |
| Staging against production | nothing | **Kustomize overlays** plus an **Argo CD ApplicationSet** |
| Bad deploy rolled back | nothing | **Argo Rollouts**, with an analysis step that aborts on its own metrics |
| TLS and hostname routing | `deploy/compose/Caddyfile`, 3,286 bytes of one vendor's config language, plus an ACME_EMAIL default that exists only because `email` with no argument is a Caddy parse error | **Gateway API**, with **cert-manager** issuing the certificates. The routing stops being the proxy's config and becomes Kubernetes objects; `gatewayClassName` is the only controller-specific string left. Compose keeps Caddy, because on a Docker host with no cluster there is no controller to talk to |

**What stays ours, and the test for it.** A policy is allowed to be hand-written only when it encodes
something true about this business that no upstream library could know. Exactly one of the seven
passes that test today:

- **`money-rail-single-writer`** refuses two replicas or a `RollingUpdate` on anything labelled
  `prospector.estate/single-writer`. SQLite has one writer. Two engines is two spend ledgers. No
  upstream library knows that, and none should.

The other six are being replaced by the upstream equivalents rather than maintained here.

---

## 3. Staging and production

Founder, 2026-08-24: *"and we need staging also"*, *"staging and prod cluster"*.

**Two clusters, never two branches of one.** A namespace is not an environment: it shares an API
server, a scheduler, the node pool and every cluster-scoped policy with the thing it is supposed to
be rehearsing against. A staging namespace cannot rehearse a control-plane upgrade, a node loss, or a
policy change, and those are the changes that hurt.

| | Staging | Production |
|---|---|---|
| Purpose | every change lands here first, automatically | serves customers |
| Receives a change | on merge to `main`, no human step | by a commit that moves an image tag |
| Data | restored from the most recent Velero backup, never live data | live |
| Money | Stripe test keys | live keys |
| Policy | **identical to production**, and this is the whole point | the same files |
| Chaos | runs continuously | runs on a schedule, in business hours, with a person watching |

**Policy must be identical in both, or staging proves nothing.** A cluster with softer rules will
admit a manifest production refuses, which converts a caught problem into an outage. The overlays
change image tags, replica counts, hostnames and secret references. They never change a policy.

### The repository shape

```
deploy/k8s/
  base/                     what is true everywhere
  overlays/staging/         image tags, hostnames, test keys
  overlays/production/      image tags, hostnames, live keys
  policies/                 kyverno/policies bases + the one estate policy
  argocd/                   the ApplicationSet that owns both clusters
  chaos/                    experiments as custom resources
```

---

## 4. The process

**Promotion is a commit, and there is no other path.**

1. A pull request merges to `main`. CI builds an image tagged with the commit SHA. No moving tags,
   because you cannot roll back to a tag that moves.
2. Argo CD syncs **staging** on its own. Nobody deploys.
3. Chaos experiments and the conformance suite run against staging.
4. Promotion to production is a commit that changes one image tag in `overlays/production`. It is
   reviewable, revertable, and it is the audit record.
5. Argo Rollouts takes it to production as a canary and aborts on its own analysis, with no human
   awake.
6. `selfHeal: true` means a change made by hand to either cluster is reverted. This is the answer to
   "total self-healing" for configuration drift, which pod restarts never covered.

**Nobody holds credentials to deploy by hand.** That is register row F-50 and it is what makes the
process real rather than a convention people abandon under pressure at 2am.

### The gates, and what each refuses

| Gate | Refuses | Tool |
|---|---|---|
| Manifests are valid before they reach a cluster | a manifest that would not apply | kubeconform, kube-linter |
| Images carry no known critical vulnerability | the image | Trivy |
| The cluster is genuinely Kubernetes | the cluster | Sonobuoy |
| The cluster meets the CIS benchmark | the cluster | kube-bench |
| Workloads meet Pod Security `restricted` | the workload | Pod Security Admission, built in |
| The money rail keeps one writer | the workload | the one Kyverno policy that is ours |
| A canary is worse than what it replaces | the release | Argo Rollouts analysis |

---

## 5. Ways of working

1. **Read what the platform does before writing anything.** Kubernetes is eleven years old. If a
   need feels universal, it is, and it has a controller.
2. **A custom script is a defect with a deadline.** Write it only for a laptop, and write down when
   it is deleted.
3. **Prove a fence in both directions.** A guard proven only to refuse has never been shown safe to
   install. LAW 38 grades a guard that blocks correct work as an outage, not a false positive.
4. **A shape is not a fact.** `k3d cluster list` said 1/1 while every `kubectl` was refused, and the
   rehearsal box reported three containers `Started` while both HTTP probes returned 000. Ask the
   thing itself: `/readyz`, a readiness probe, a real request.
5. **Never let a timeout destroy state.** k3d's rollback deleted a healthy cluster because its clock
   ran out on a busy machine. Keep what came up and ask it whether it works.
6. **Staging is not optional and is not a namespace.**
7. **Every tool here is Apache-2.0 and self-hosted.** No account, no card, no licence that changes
   under an acquisition. This is LAW 40: the estate has to remain sellable.

---

## 6. What landed, and what is still open

**Landed the same day, and measured rather than described.** This document is research, and research
that stops at a document is the thing people agree with and work around at 2am. So:

- `deploy/k8s/` now holds `base/`, `policies/`, `overlays/{staging,production}/` and `argocd/`.
- Six hand-written policies are gone. `deploy/k8s/policies/RETIRED.md` maps each to its upstream
  replacement. Two stayed, and the test they passed is written there.
- Both overlays build with `kubectl kustomize`, which is part of kubectl and needs no install:

  ```
  $ kubectl kustomize deploy/k8s/overlays/production | grep -c '^kind: ClusterPolicy'
  26
  $ kubectl kustomize deploy/k8s/overlays/production | grep -o 'validationFailureAction: [A-Za-z]*' | sort | uniq -c
    26 validationFailureAction: Enforce
  ```

- `.github/workflows/k8s-manifests.yml` is the enforcement. Four gates, each graded against the
  BUILT output rather than the source, because kustomize patches and remote bases mean the file on
  disk is not what reaches the cluster: every policy enforces and none audits; staging and
  production enforce identical policy; the namespace carries PSA `restricted`; every remote
  kustomize resource is pinned to a commit SHA.
- Each gate was run locally and proved BOTH ways before it was committed, per LAW 38. The
  identical-policy gate was fed a build with one rule softened and one policy removed, and refused
  both. The pinning gate was fed a `?ref=main` and refused it. It had also refused something correct
  on its first draft — this repo's own `repoURL`, which Argo CD is supposed to track at a branch —
  and was rescoped to `kustomization.yaml` resources rather than every URL under `deploy/k8s`.
- `deploy/rehearse_cluster.sh` no longer applies the policy directory with `kubectl apply -f`. It
  applies `overlays/staging` with `-k`, so the drill rehearses the same 26 objects a real cluster
  gets rather than the 7 that happened to be files.

`cmd_resilience` is still superseded by chaos experiments as custom resources once a chaos platform
is installed, and has not moved.

**Still open, and not pretended otherwise:**

- **No cluster has applied any of it.** The build is green and there is no cluster. That is the
  honest state and it is why nothing above is written as done.
- **No policy has been shown to refuse a workload ON A CLUSTER.** That line had no qualifier when it
  was written a few hours earlier, and the qualifier is the change: the policies are now proved to
  decide, offline, by the same admission engine a cluster runs. The Kyverno CLI is a standalone
  binary and needed no API server, which means "does this standard actually work" stopped being a
  question that waits on a rented box. Measured 2026-08-24: 13 assertions pairing each of eleven
  single-violation manifests to the specific policy AND rule that must catch it, all 13 holding, and
  a reference workload admitted with 0 failures out of 87 rules loaded. Register row F-55, `✅`.

  What still needs a live API server, and is therefore still F-47 at `◐`: that the admission webhook
  is reachable, that the policies were installed at all, and that the cluster is not quietly running
  them in `Audit`. LAW 15 wants two angles; this is one of them, and it is the cheap one.

- **Adopting somebody else's library means adopting rules you did not think of, and one of them bit
  the same day.** `secrets-not-from-env-vars` forbids `envFrom.secretRef` outright and
  `env[].valueFrom.secretKeyRef` with it: secrets must be mounted as files, because an environment
  variable is readable from `/proc/<pid>/environ`, lands in crash dumps, and is inherited by every
  child the container spawns. The first draft of the reference workload used `envFrom`, which is how
  this whole estate does it in compose today, and the policy refused it. It is left enforcing rather
  than relaxed: no Kubernetes workload manifests exist yet, so it costs nothing today and forces the
  right shape when they are written. Weakening a fence before it has ever refused real work is how a
  fence stops being one.

- **The grading tool itself reported a shape while the substance said otherwise, which is now the
  sixth instance in one night.** `kyverno test` v1.16.1, with one assertion deliberately violated,
  printed `Test Summary: 13 tests passed and 0 tests failed` and exited **0** — while its own
  `REASON` column on that row read `Want fail, got pass`. Had the gate been wired to the exit code,
  which is the obvious way to wire it, it would have been permanently green and nobody would have
  had a reason to look. The gate parses `-o json` and grades `REASON`. The general rule this estate
  keeps re-learning: find the field that carries the verdict, and never grade the field that carries
  the summary.

- The chaos choice between Litmus and Chaos Mesh is not settled. Both are CNCF Incubating. Chaos Mesh
  has more stars (7,853 against 5,600) and a CLOMonitor score of 40.0, which is the lowest of
  anything on this page. Litmus has no CLOMonitor entry at all. Neither number decides it, and the
  tie-break needs a criterion this estate has not yet stated.
- Neither cluster exists. Both are rented boxes and rented boxes cost money, which is the founder's
  decision under LAW 5.
- Register rows F-45 through F-50 in `docs/MIGRATION_AND_DR_PROGRAM.md` §11 carry these
  requirements. Three of them were added on 2026-08-24 because his sentence had clauses with no row.
