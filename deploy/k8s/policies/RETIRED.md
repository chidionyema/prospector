# The six policies this estate retired, and what replaced each one

Founder, 2026-08-24: *"not write custon scripts for production cluster"*, *"never reinvent the
wheel"*, *"reserch what always works"*.

`estate-standards.yaml` held seven hand-written Kyverno `ClusterPolicy` objects. Six of them
restate something the Kyverno project already publishes and maintains. Those six moved to the
upstream library, pinned to commit `ef9843f08d25b3555fe69616f8612c9f915af5d4`
(`main` as of 2026-07-04T06:01:43Z). Two stayed, in `estate.yaml`.

Measured 2026-08-24 with `gh api repos/kyverno/policies/contents/<dir>`.

| Retired policy | What it said | Upstream replacement |
|---|---|---|
| `secure-by-default` | no privileged containers, no privilege escalation, run as non-root | `pod-security/restricted` — six policies: `disallow-capabilities-strict`, `disallow-privilege-escalation`, `require-run-as-non-root-user`, `require-run-as-nonroot`, `restrict-seccomp-strict`, `restrict-volume-types`. It also pulls in `pod-security/baseline`. **And Pod Security Admission**, built into Kubernetes since 1.25, does the same at the namespace edge with no controller at all |
| `images-must-be-traceable` | no `:latest`, no untagged image | `best-practices/disallow-latest-tag` |
| `workloads-declare-what-they-need` | requests and limits on every container | `best-practices/require-pod-requests-limits` |
| `serving-workloads-must-be-probed` | liveness and readiness probes | `best-practices/require-probes` |
| `no-literal-credentials-in-pod-spec` | a credential in `env.value` rather than a `secretKeyRef` | `other/disallow-secrets-from-env-vars` |
| — (never written, and it should have been) | drop all capabilities; read-only root filesystem; nothing in the `default` namespace | `best-practices/require-drop-all`, `best-practices/require-ro-rootfs`, `best-practices/disallow-default-namespace`. Adopting the library got the estate three rules it had not thought of, which is the argument for a library in one line |

## The two that stayed, and the test they passed

A policy earns a hand-written slot only when it encodes something true about this business that no
upstream library could know. Two do.

**`money-rail-single-writer`.** Refuses more than one replica, or a `RollingUpdate` strategy, on
anything labelled `prospector.estate/single-writer`. SQLite permits one writer. Two engines keep two
spend ledgers and each honours `config.yaml spend.daily_cap_usd` separately, so a $100 cap silently
becomes $200. No upstream library knows this estate's store is SQLite or that its cap is per-process.

**`no-optional-secret-references`.** Refuses `optional: true` on a `secretRef`. This is the
2026-08-24 incident written as a rule: compose's `required: false` let a box start carrying none of
its 24 settings, and the deploy script reported success. `optional: true` is the Kubernetes spelling
of the same trap. **Searched upstream and found no equivalent** — the closest,
`other/disallow-secrets-from-env-vars`, is about a different failure. If one appears, this one
retires too.

## What was deliberately not adopted

`best-practices/` holds twenty policies. Four of them MUTATE rather than refuse —
`add-network-policy`, `add-ns-quota`, `add-rolebinding`, `add-safe-to-evict` — and a policy that
silently edits a workload is harder to debug at 2am than one that refuses it with a message. They
are left out until each is a deliberate decision with its own reason.

`best-practices/restrict-image-registries` needs the estate's allowed registry list, which is not
yet written down anywhere. That is a gap, not a rejection.

## Enforce, not Audit

Upstream ships every policy as `validationFailureAction: Audit`: it writes a report and admits the
workload. `enforce.yaml` flips the whole build to `Enforce`. An audit-only rule is a log line
nobody reads, which LAW 28 grades as not an instrument at all.

The rules are identical in staging and production. That is the entire value of having a staging
cluster: one with softer rules admits manifests production refuses, which converts a caught problem
into an outage.

## What has not been proved yet

No policy in this directory has been shown to refuse anything on a live cluster. LAW 38 says a
guard that blocks correct work is an outage, so each needs proving BOTH ways — one manifest refused
and one admitted — before any of this counts. Register rows F-47 in
`docs/MIGRATION_AND_DR_PROGRAM.md` §11 carry that, and it is `◐`, not `✅`.
