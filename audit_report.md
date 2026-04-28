# Visual Audit — Python vs. C dot.exe

Generated: 2026-04-27 21:08:46

Metric: **edges whose routed spline crosses a non-member cluster bbox** (sampled bezier → bbox intersection).  A relative signal, not a visual-quality absolute.

## Summary

- Graphs audited: **10** (10 ok, 0 errored/timeout)
- Graphs clean on both sides (0 crossings): **3**
- Python regression cases (py > c): **7**
- Total Python crossings: **130**
- Total C crossings: **0**
- Net delta (py − c): **+130**

## Top regression graphs (py > c)

| File | Py nodes | Py edges | Py cross | C cross | Δ |
|---|---:|---:|---:|---:|---:|
| 1879.dot | 549 | 355 | 95 | 0 | +95 |
| 1332_ref.dot | 91 | 111 | 16 | 0 | +16 |
| 2796.dot | 59 | 91 | 7 | 0 | +7 |
| 1436.dot | 34 | 22 | 3 | 0 | +3 |
| 1472.dot | 135 | 86 | 3 | 0 | +3 |
| 2183.dot | 18 | 18 | 3 | 0 | +3 |
| aa1332.dot | 91 | 111 | 3 | 0 | +3 |

## Failed / timed out

| File | Status | Note |
|---|---|---|
| _(none)_ | | |

## Full results

| File | Status | Py nodes | Py edges | Py cross | C edges | C cross | Δ |
|---|---|---:|---:|---:|---:|---:|---:|
| 1213-1.dot | ok | 12 | 17 | 0 | 0 | 0 | +0 |
| 1213-2.dot | ok | 12 | 17 | 0 | 0 | 0 | +0 |
| 1332_ref.dot | ok | 91 | 111 | 16 | 0 | 0 | +16 |
| 1436.dot | ok | 34 | 22 | 3 | 0 | 0 | +3 |
| 1472.dot | ok | 135 | 86 | 3 | 0 | 0 | +3 |
| 1879.dot | ok | 549 | 355 | 95 | 0 | 0 | +95 |
| 2183.dot | ok | 18 | 18 | 3 | 0 | 0 | +3 |
| 2796.dot | ok | 59 | 91 | 7 | 0 | 0 | +7 |
| aa1332.dot | ok | 91 | 111 | 3 | 0 | 0 | +3 |
| d5_regression.dot | ok | 23 | 20 | 0 | 0 | 0 | +0 |
