# Visual Audit — Python vs. C dot.exe

Generated: 2026-04-24 22:36:19

Metric: **edges whose routed spline crosses a non-member cluster bbox** (sampled bezier → bbox intersection).  A relative signal, not a visual-quality absolute.

## Summary

- Graphs audited: **197** (173 ok, 24 errored/timeout)
- Graphs clean on both sides (0 crossings): **161**
- Python regression cases (py > c): **12**
- Total Python crossings: **186**
- Total C crossings: **0**
- Net delta (py − c): **+186**

## Top regression graphs (py > c)

| File | Py nodes | Py edges | Py cross | C cross | Δ |
|---|---:|---:|---:|---:|---:|
| 1879.dot | 549 | 355 | 105 | 0 | +105 |
| 2796.dot | 59 | 91 | 37 | 0 | +37 |
| 1332_ref.dot | 91 | 111 | 11 | 0 | +11 |
| 1436.dot | 34 | 22 | 11 | 0 | +11 |
| 1472.dot | 135 | 86 | 8 | 0 | +8 |
| 1213-1.dot | 12 | 17 | 3 | 0 | +3 |
| 1332.dot | 91 | 111 | 3 | 0 | +3 |
| aa1332.dot | 91 | 111 | 3 | 0 | +3 |
| 1213-2.dot | 12 | 17 | 2 | 0 | +2 |
| 2183.dot | 18 | 18 | 1 | 0 | +1 |
| 2239.dot | 94 | 41 | 1 | 0 | +1 |
| d5_regression.dot | 23 | 20 | 1 | 0 | +1 |

## Failed / timed out

| File | Status | Note |
|---|---|---|
| 1494.dot | C_FAIL | RuntimeError: dot.exe rc=3, no SVG in stdout: Warning: Invalid 3-byte UTF8 found in input of graph %1 -  |
| 1652.dot | PY_TIMEOUT |  |
| 1718.dot | PY_TIMEOUT |  |
| 1783.dot | C_FAIL | RuntimeError: dot.exe rc=1, no SVG in stdout: Error: overflow when calculating virtual weight of edge
 |
| 1864.dot | PY_TIMEOUT |  |
| 2064.dot | PY_TIMEOUT |  |
| 2095_1.dot | PY_TIMEOUT |  |
| 2108.dot | PY_TIMEOUT |  |
| 2222.dot | PY_TIMEOUT |  |
| 2343.dot | PY_TIMEOUT |  |
| 2371.dot | PY_TIMEOUT |  |
| 2470.dot | PY_TIMEOUT |  |
| 2471.dot | PY_TIMEOUT |  |
| 2475_1.dot | PY_TIMEOUT |  |
| 2475_2.dot | PY_TIMEOUT |  |
| 2521.dot | C_FAIL | RuntimeError: dot.exe rc=3221225477, no SVG in stdout:  |
| 2593.dot | PY_TIMEOUT |  |
| 2619_1.dot | PY_FAIL | RuntimeError: IndexError: list index out of range |
| 2619_2.dot | PY_FAIL | RuntimeError: IndexError: list index out of range |
| 2620.dot | PY_TIMEOUT |  |
| 2621.dot | PY_TIMEOUT |  |
| 2646.dot | PY_TIMEOUT |  |
| 2723.dot | C_FAIL | RuntimeError: dot.exe rc=3221225477, no SVG in stdout:  |
| 2854.dot | PY_TIMEOUT |  |

## Full results

| File | Status | Py nodes | Py edges | Py cross | C edges | C cross | Δ |
|---|---|---:|---:|---:|---:|---:|---:|
| 121.dot | ok | 6 | 6 | 0 | 0 | 0 | +0 |
| 1213-1.dot | ok | 12 | 17 | 3 | 0 | 0 | +3 |
| 1213-2.dot | ok | 12 | 17 | 2 | 0 | 0 | +2 |
| 1221.dot | ok | 1 | 0 | 0 | 0 | 0 | +0 |
| 1308.dot | ok | 3 | 2 | 0 | 0 | 0 | +0 |
| 1308_1.dot | ok | 11 | 6 | 0 | 0 | 0 | +0 |
| 1314.dot | ok | 2 | 0 | 0 | 0 | 0 | +0 |
| 1323.dot | ok | 3 | 9 | 0 | 0 | 0 | +0 |
| 1323_1.dot | ok | 3 | 3 | 0 | 0 | 0 | +0 |
| 1328.dot | ok | 5 | 3 | 0 | 0 | 0 | +0 |
| 1332.dot | ok | 91 | 111 | 3 | 0 | 0 | +3 |
| 1332_cluster_4117.dot | ok | 3 | 3 | 0 | 0 | 0 | +0 |
| 1332_cluster_4148.dot | ok | 2 | 1 | 0 | 0 | 0 | +0 |
| 1332_cluster_5376.dot | ok | 4 | 3 | 0 | 0 | 0 | +0 |
| 1332_ref.dot | ok | 91 | 111 | 11 | 0 | 0 | +11 |
| 1367.dot | ok | 21 | 10 | 0 | 0 | 0 | +0 |
| 14.dot | ok | 2 | 1 | 0 | 0 | 0 | +0 |
| 1408.dot | ok | 2 | 1 | 0 | 0 | 0 | +0 |
| 1425.dot | ok | 1 | 0 | 0 | 0 | 0 | +0 |
| 1425_1.dot | ok | 4 | 1 | 0 | 0 | 0 | +0 |
| 1435.dot | ok | 12 | 9 | 0 | 0 | 0 | +0 |
| 1436.dot | ok | 34 | 22 | 11 | 0 | 0 | +11 |
| 1444-2.dot | ok | 2 | 1 | 0 | 0 | 0 | +0 |
| 1444.dot | ok | 2 | 1 | 0 | 0 | 0 | +0 |
| 1447.dot | ok | 36 | 35 | 0 | 0 | 0 | +0 |
| 1447_1.dot | ok | 166 | 203 | 0 | 0 | 0 | +0 |
| 144_no_ortho.dot | ok | 4 | 3 | 0 | 0 | 0 | +0 |
| 144_ortho.dot | ok | 4 | 3 | 0 | 0 | 0 | +0 |
| 1453.dot | ok | 26 | 29 | 0 | 0 | 0 | +0 |
| 1472.dot | ok | 135 | 86 | 8 | 0 | 0 | +8 |
| 1474.dot | ok | 156 | 13 | 0 | 0 | 0 | +0 |
| 1489.dot | ok | 36 | 11 | 0 | 0 | 0 | +0 |
| 1494.dot | C_FAIL | 3 | 0 | 0 | 0 | 0 | – |
| 1514.dot | ok | 6 | 5 | 0 | 0 | 0 | +0 |
| 1554.dot | ok | 7 | 10 | 0 | 0 | 0 | +0 |
| 1581.dot | ok | 16 | 13 | 0 | 0 | 0 | +0 |
| 1585_0.dot | ok | 4 | 3 | 0 | 0 | 0 | +0 |
| 1585_1.dot | ok | 4 | 3 | 0 | 0 | 0 | +0 |
| 162.dot | ok | 4 | 3 | 0 | 0 | 0 | +0 |
| 1622_0.dot | ok | 1 | 0 | 0 | 0 | 0 | +0 |
| 1622_1.dot | ok | 1 | 0 | 0 | 0 | 0 | +0 |
| 1622_2.dot | ok | 1 | 0 | 0 | 0 | 0 | +0 |
| 1622_3.dot | ok | 1 | 0 | 0 | 0 | 0 | +0 |
| 1624.dot | ok | 4 | 3 | 0 | 0 | 0 | +0 |
| 1644.dot | ok | 5 | 4 | 0 | 0 | 0 | +0 |
| 165.dot | ok | 1 | 0 | 0 | 0 | 0 | +0 |
| 1652.dot | PY_TIMEOUT | 0 | 0 | 0 | 0 | 0 | – |
| 1658.dot | ok | 21 | 20 | 0 | 0 | 0 | +0 |
| 165_2.dot | ok | 2 | 0 | 0 | 0 | 0 | +0 |
| 165_3.dot | ok | 1 | 0 | 0 | 0 | 0 | +0 |
| 167.dot | ok | 3 | 2 | 0 | 0 | 0 | +0 |
| 1676.dot | ok | 3 | 1 | 0 | 0 | 0 | +0 |
| 1702.dot | ok | 4 | 3 | 0 | 0 | 0 | +0 |
| 1718.dot | PY_TIMEOUT | 0 | 0 | 0 | 0 | 0 | – |
| 1724.dot | ok | 3 | 1 | 0 | 0 | 0 | +0 |
| 1767.dot | ok | 12 | 10 | 0 | 0 | 0 | +0 |
| 1783.dot | C_FAIL | 2 | 1 | 0 | 0 | 0 | – |
| 1845.dot | ok | 2 | 1 | 0 | 0 | 0 | +0 |
| 1855.dot | ok | 32 | 31 | 0 | 0 | 0 | +0 |
| 1856.dot | ok | 5 | 5 | 0 | 0 | 0 | +0 |
| 1864.dot | PY_TIMEOUT | 0 | 0 | 0 | 0 | 0 | – |
| 1865.dot | ok | 1 | 0 | 0 | 0 | 0 | +0 |
| 1879-2.dot | ok | 2 | 1 | 0 | 0 | 0 | +0 |
| 1879.dot | ok | 549 | 355 | 105 | 0 | 0 | +105 |
| 1880.dot | ok | 16 | 16 | 0 | 0 | 0 | +0 |
| 1896.dot | ok | 3 | 2 | 0 | 0 | 0 | +0 |
| 1898.dot | ok | 24 | 0 | 0 | 0 | 0 | +0 |
| 1902.dot | ok | 5 | 3 | 0 | 0 | 0 | +0 |
| 1909.dot | ok | 3 | 2 | 0 | 0 | 0 | +0 |
| 1925.dot | ok | 6 | 2 | 0 | 0 | 0 | +0 |
| 1939.dot | ok | 7 | 6 | 0 | 0 | 0 | +0 |
| 1949.dot | ok | 9 | 6 | 0 | 0 | 0 | +0 |
| 1990.dot | ok | 15 | 14 | 0 | 0 | 0 | +0 |
| 2064.dot | PY_TIMEOUT | 0 | 0 | 0 | 0 | 0 | – |
| 2082.dot | ok | 7 | 10 | 0 | 0 | 0 | +0 |
| 2087.dot | ok | 5 | 5 | 0 | 0 | 0 | +0 |
| 2095.dot | ok | 275 | 274 | 0 | 0 | 0 | +0 |
| 2095_1.dot | PY_TIMEOUT | 0 | 0 | 0 | 0 | 0 | – |
| 2108.dot | PY_TIMEOUT | 0 | 0 | 0 | 0 | 0 | – |
| 2159.dot | ok | 2 | 0 | 0 | 0 | 0 | +0 |
| 2168.dot | ok | 2 | 2 | 0 | 0 | 0 | +0 |
| 2168_1.dot | ok | 2 | 1 | 0 | 0 | 0 | +0 |
| 2168_2.dot | ok | 2 | 1 | 0 | 0 | 0 | +0 |
| 2168_3.dot | ok | 2 | 2 | 0 | 0 | 0 | +0 |
| 2168_4.dot | ok | 2 | 1 | 0 | 0 | 0 | +0 |
| 2168_5.dot | ok | 2 | 1 | 0 | 0 | 0 | +0 |
| 2183.dot | ok | 18 | 18 | 1 | 0 | 0 | +1 |
| 2184.dot | ok | 9 | 7 | 0 | 0 | 0 | +0 |
| 2193.dot | ok | 58 | 41 | 0 | 0 | 0 | +0 |
| 2222.dot | PY_TIMEOUT | 0 | 0 | 0 | 0 | 0 | – |
| 2225.dot | ok | 3 | 3 | 0 | 0 | 0 | +0 |
| 2239.dot | ok | 94 | 41 | 1 | 0 | 0 | +1 |
| 2241.dot | ok | 2 | 2 | 0 | 0 | 0 | +0 |
| 2242.dot | ok | 18 | 12 | 0 | 0 | 0 | +0 |
| 2257.dot | ok | 2 | 1 | 0 | 0 | 0 | +0 |
| 2258.dot | ok | 2 | 1 | 0 | 0 | 0 | +0 |
| 2282.dot | ok | 4 | 3 | 0 | 0 | 0 | +0 |
| 2283.dot | ok | 7 | 6 | 0 | 0 | 0 | +0 |
| 2285.dot | ok | 0 | 0 | 0 | 0 | 0 | +0 |
| 2295.dot | ok | 1 | 0 | 0 | 0 | 0 | +0 |
| 2325.dot | ok | 1 | 0 | 0 | 0 | 0 | +0 |
| 2342.dot | ok | 6 | 5 | 0 | 0 | 0 | +0 |
| 2343.dot | PY_TIMEOUT | 0 | 0 | 0 | 0 | 0 | – |
| 2352.dot | ok | 2 | 1 | 0 | 0 | 0 | +0 |
| 2352_1.dot | ok | 2 | 1 | 0 | 0 | 0 | +0 |
| 2352_2.dot | ok | 2 | 1 | 0 | 0 | 0 | +0 |
| 2361.dot | ok | 14 | 18 | 0 | 0 | 0 | +0 |
| 2368.dot | ok | 11 | 20 | 0 | 0 | 0 | +0 |
| 2368_1.dot | ok | 5 | 5 | 0 | 0 | 0 | +0 |
| 2371.dot | PY_TIMEOUT | 0 | 0 | 0 | 0 | 0 | – |
| 2391.dot | ok | 4 | 4 | 0 | 0 | 0 | +0 |
| 2391_1.dot | ok | 4 | 4 | 0 | 0 | 0 | +0 |
| 2406.dot | ok | 4 | 3 | 0 | 0 | 0 | +0 |
| 2413_1.dot | ok | 4 | 0 | 0 | 0 | 0 | +0 |
| 2413_2.dot | ok | 27 | 0 | 0 | 0 | 0 | +0 |
| 241_0.dot | ok | 11 | 14 | 0 | 0 | 0 | +0 |
| 241_1.dot | ok | 13 | 24 | 0 | 0 | 0 | +0 |
| 2436.dot | ok | 2 | 1 | 0 | 0 | 0 | +0 |
| 2437.dot | ok | 2 | 1 | 0 | 0 | 0 | +0 |
| 2457_1.dot | ok | 5 | 4 | 0 | 0 | 0 | +0 |
| 2457_2.dot | ok | 5 | 4 | 0 | 0 | 0 | +0 |
| 2458.dot | ok | 3 | 0 | 0 | 0 | 0 | +0 |
| 2460.dot | ok | 1 | 0 | 0 | 0 | 0 | +0 |
| 2470.dot | PY_TIMEOUT | 0 | 0 | 0 | 0 | 0 | – |
| 2471.dot | PY_TIMEOUT | 0 | 0 | 0 | 0 | 0 | – |
| 2475_1.dot | PY_TIMEOUT | 0 | 0 | 0 | 0 | 0 | – |
| 2475_2.dot | PY_TIMEOUT | 0 | 0 | 0 | 0 | 0 | – |
| 2476.dot | ok | 26 | 21 | 0 | 0 | 0 | +0 |
| 2484.dot | ok | 4 | 3 | 0 | 0 | 0 | +0 |
| 2490.dot | ok | 2 | 1 | 0 | 0 | 0 | +0 |
| 2497.dot | ok | 4 | 0 | 0 | 0 | 0 | +0 |
| 2502.dot | ok | 2 | 1 | 0 | 0 | 0 | +0 |
| 2516.dot | ok | 1 | 0 | 0 | 0 | 0 | +0 |
| 2521.dot | C_FAIL | 11 | 6 | 0 | 0 | 0 | – |
| 2521_1.dot | ok | 9 | 14 | 0 | 0 | 0 | +0 |
| 2538.dot | ok | 17 | 1 | 0 | 0 | 0 | +0 |
| 2556.dot | ok | 20 | 20 | 0 | 0 | 0 | +0 |
| 2559.dot | ok | 4 | 2 | 0 | 0 | 0 | +0 |
| 2563.dot | ok | 4 | 3 | 0 | 0 | 0 | +0 |
| 2564.dot | ok | 2 | 1 | 0 | 0 | 0 | +0 |
| 2572.dot | ok | 6 | 4 | 0 | 0 | 0 | +0 |
| 258.dot | ok | 6 | 5 | 0 | 0 | 0 | +0 |
| 2592.dot | ok | 6 | 3 | 0 | 0 | 0 | +0 |
| 2593.dot | PY_TIMEOUT | 0 | 0 | 0 | 0 | 0 | – |
| 2609.dot | ok | 4 | 3 | 0 | 0 | 0 | +0 |
| 2613.dot | ok | 2 | 0 | 0 | 0 | 0 | +0 |
| 2614.dot | ok | 2 | 1 | 0 | 0 | 0 | +0 |
| 2615.dot | ok | 6 | 6 | 0 | 0 | 0 | +0 |
| 2619.dot | ok | 1 | 0 | 0 | 0 | 0 | +0 |
| 2619_1.dot | PY_FAIL | 0 | 0 | 0 | 0 | 0 | – |
| 2619_2.dot | PY_FAIL | 0 | 0 | 0 | 0 | 0 | – |
| 2620.dot | PY_TIMEOUT | 0 | 0 | 0 | 0 | 0 | – |
| 2621.dot | PY_TIMEOUT | 0 | 0 | 0 | 0 | 0 | – |
| 2636.dot | ok | 1 | 0 | 0 | 0 | 0 | +0 |
| 2636_1.dot | ok | 1 | 0 | 0 | 0 | 0 | +0 |
| 2636_2.dot | ok | 1 | 0 | 0 | 0 | 0 | +0 |
| 2639.dot | ok | 14 | 10 | 0 | 0 | 0 | +0 |
| 2643.dot | ok | 3 | 2 | 0 | 0 | 0 | +0 |
| 2646.dot | PY_TIMEOUT | 0 | 0 | 0 | 0 | 0 | – |
| 2669.dot | ok | 177 | 204 | 0 | 0 | 0 | +0 |
| 2682.dot | ok | 3 | 0 | 0 | 0 | 0 | +0 |
| 2683.dot | ok | 11 | 0 | 0 | 0 | 0 | +0 |
| 2699.dot | ok | 2 | 1 | 0 | 0 | 0 | +0 |
| 2717.dot | ok | 9 | 2 | 0 | 0 | 0 | +0 |
| 2721.dot | ok | 1 | 0 | 0 | 0 | 0 | +0 |
| 2723.dot | C_FAIL | 14 | 15 | 0 | 0 | 0 | – |
| 2727.dot | ok | 2 | 0 | 0 | 0 | 0 | +0 |
| 2734.dot | ok | 15 | 14 | 0 | 0 | 0 | +0 |
| 2743.dot | ok | 1 | 0 | 0 | 0 | 0 | +0 |
| 2782.dot | ok | 7 | 1 | 0 | 0 | 0 | +0 |
| 2796.dot | ok | 59 | 91 | 37 | 0 | 0 | +37 |
| 2801.dot | ok | 6 | 0 | 0 | 0 | 0 | +0 |
| 2825.dot | ok | 10 | 14 | 0 | 0 | 0 | +0 |
| 2854.dot | PY_TIMEOUT | 0 | 0 | 0 | 0 | 0 | – |
| 358.dot | ok | 9 | 0 | 0 | 0 | 0 | +0 |
| 42.dot | ok | 25 | 32 | 0 | 0 | 0 | +0 |
| 56.dot | ok | 14 | 0 | 0 | 0 | 0 | +0 |
| 705.dot | ok | 6 | 3 | 0 | 0 | 0 | +0 |
| 813.dot | ok | 1 | 0 | 0 | 0 | 0 | +0 |
| 925.dot | ok | 2 | 0 | 0 | 0 | 0 | +0 |
| aa1332.dot | ok | 91 | 111 | 3 | 0 | 0 | +3 |
| d5_regression.dot | ok | 23 | 20 | 1 | 0 | 0 | +1 |
| html_img_link.dot | ok | 9 | 8 | 0 | 0 | 0 | +0 |
| html_labels.dot | ok | 17 | 1 | 0 | 0 | 0 | +0 |
| html_port_mixed.dot | ok | 5 | 4 | 0 | 0 | 0 | +0 |
| html_spec.dot | ok | 8 | 7 | 0 | 0 | 0 | +0 |
| html_style.dot | ok | 8 | 7 | 0 | 0 | 0 | +0 |
| html_tables.dot | ok | 7 | 5 | 0 | 0 | 0 | +0 |
| negative-dpi.dot | ok | 2 | 1 | 0 | 0 | 0 | +0 |
| test_3in1out.dot | ok | 5 | 4 | 0 | 0 | 0 | +0 |
| test_3in1out_labeled.dot | ok | 5 | 4 | 0 | 0 | 0 | +0 |
| test_3in1out_labeled_lr.dot | ok | 5 | 4 | 0 | 0 | 0 | +0 |
| test_3in1out_lr.dot | ok | 5 | 4 | 0 | 0 | 0 | +0 |
| test_nodelabel.dot | ok | 5 | 4 | 0 | 0 | 0 | +0 |
| test_nodelabel_lr.dot | ok | 5 | 4 | 0 | 0 | 0 | +0 |
| trigraph_test.dot | ok | 3 | 0 | 0 | 0 | 0 | +0 |
| usershape.dot | ok | 1 | 0 | 0 | 0 | 0 | +0 |
