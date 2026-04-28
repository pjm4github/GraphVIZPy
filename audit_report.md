# Visual Audit — Python vs. C dot.exe

Generated: 2026-04-27 21:37:27

Metric: **edges whose routed spline crosses a non-member cluster bbox** (sampled bezier → bbox intersection).  A relative signal, not a visual-quality absolute.

## Summary

- Graphs audited: **10** (10 ok, 0 errored/timeout)
- Graphs clean on both sides (0 crossings): **0**
- Python regression cases (py > c): **4**
- Total Python crossings: **133**
- Total C crossings: **57**
- Net delta (py − c): **+76**

## Top regression graphs (py > c)

| File | Py nodes | Py edges | Py cross | C cross | Δ |
|---|---:|---:|---:|---:|---:|
| 1879.dot | 549 | 355 | 96 | 2 | +94 |
| 1332_ref.dot | 91 | 111 | 16 | 6 | +10 |
| 2183.dot | 18 | 18 | 3 | 0 | +3 |
| 1436.dot | 34 | 22 | 3 | 1 | +2 |

## Failed / timed out

| File | Status | Note |
|---|---|---|
| _(none)_ | | |

## Full results

| File | Status | Py nodes | Py edges | Py cross | C edges | C cross | Δ |
|---|---|---:|---:|---:|---:|---:|---:|
| 1213-1.dot | ok | 12 | 17 | 0 | 16 | 3 | -3 |
| 1213-2.dot | ok | 12 | 17 | 0 | 16 | 3 | -3 |
| 1332_ref.dot | ok | 91 | 111 | 16 | 116 | 6 | +10 |
| 1436.dot | ok | 34 | 22 | 3 | 22 | 1 | +2 |
| 1472.dot | ok | 135 | 86 | 3 | 154 | 9 | -6 |
| 1879.dot | ok | 549 | 355 | 96 | 355 | 2 | +94 |
| 2183.dot | ok | 18 | 18 | 3 | 0 | 0 | +3 |
| 2796.dot | ok | 59 | 91 | 9 | 212 | 16 | -7 |
| aa1332.dot | ok | 91 | 111 | 3 | 117 | 15 | -12 |
| d5_regression.dot | ok | 23 | 20 | 0 | 19 | 2 | -2 |
