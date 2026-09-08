---
name: differential-verification
description: Use when verifying ogamiOanda legacy parity, golden traces, intentional deltas, or changes to the differential harness.
---

# Differential Verification

Read [the maintained differential workflow](../../../docs/differential-verification.md) before selecting checks.

1. Keep the documented baseline commit and tree identity unchanged.
2. Run differential verification offline; do not cross into API, practice, live, or credentialed gates.
3. Begin with the affected differential test.
4. Expand to the workflow's broader current-versus-golden or provenance gates only when the affected scope requires them.
5. Investigate mismatches before changing golden traces or intentional deltas.

Report the checks, baseline identity used, results, and any unverified boundary.
