# Layout Engine TODO

Status of each Graphviz layout engine port in `pycode/`.

## Implemented

### dot — Hierarchical layout (`pycode/dot/dot_layout.py`)
- **Status:** Complete
- **Algorithm:** 4-phase Sugiyama (rank assignment, crossing minimization, coordinate assignment, edge routing)
- **Features:** Network simplex ranking/positioning, 101+ DOT attributes, virtual nodes, clusters, compound edges, Bézier/polyline/ortho routing, collision-aware label placement
- **Tests:** 165+ tests passing

### circo — Circular layout (`pycode/circo/circo_layout.py`)
- **Status:** Complete
- **Algorithm:** Biconnected decomposition → block-cutpoint tree → node ordering (longest path + crossing reduction) → circular placement → recursive block positioning
- **Features:** `mindist`, `root`, `oneblock` attributes, component packing, edge crossing reduction, SVG/JSON/DOT output
- **Tests:** 25 tests passing

## Stub — Not Yet Implemented

### neato — Spring-model force-directed (`pycode/neato/`)
- **C reference:** `lib/neatogen/`
- **Algorithm:** Stress majorization or Kamada-Kawai
- **Best for:** Undirected graphs up to ~1000 nodes
- **Key features to implement:**
  - Graph-theoretic shortest-path distances
  - Stress function minimization
  - `overlap` attribute (scale, prism, voronoi removal)
  - `sep` attribute for minimum node separation
  - `start` attribute for initial layout seed

### fdp — Force-directed placement (`pycode/fdp/`)
- **C reference:** `lib/fdpgen/`
- **Algorithm:** Fruchterman-Reingold spring-electrical model
- **Best for:** Undirected graphs with clusters
- **Key features to implement:**
  - Attractive/repulsive force simulation
  - Cluster support (rectangular constraints)
  - Grid-based force approximation
  - `K` attribute (spring constant)

### sfdp — Scalable force-directed (`pycode/sfdp/`)
- **C reference:** `lib/sfdpgen/`
- **Algorithm:** Multi-level coarsening + Barnes-Hut approximation
- **Best for:** Large graphs (10K+ nodes)
- **Key features to implement:**
  - Coarsening/uncoarsening hierarchy
  - Barnes-Hut octree for repulsive forces
  - `levels` attribute
  - `smoothing` attribute

### twopi — Radial layout (`pycode/twopi/`)
- **C reference:** `lib/twopigen/`
- **Algorithm:** BFS from root, concentric ring placement
- **Best for:** Trees, rooted DAGs, network topologies
- **Key features to implement:**
  - Root selection (automatic or via `root` attribute)
  - BFS level assignment
  - Angular span allocation per subtree
  - `ranksep` as ring gap

### osage — Cluster packing (`pycode/osage/`)
- **C reference:** `lib/osage/`
- **Algorithm:** Recursive rectangular packing within clusters
- **Best for:** Hierarchical cluster diagrams, org charts, package structure
- **Key features to implement:**
  - Recursive cluster subdivision
  - Node packing within cluster rectangles
  - Cluster label placement
  - `pack` and `packmode` attributes

### patchwork — Treemap (`pycode/patchwork/`)
- **C reference:** `lib/patchwork/`
- **Algorithm:** Squarified treemap with nested rectangles
- **Best for:** Hierarchical data visualization, size comparisons
- **Key features to implement:**
  - Squarified treemap algorithm
  - Node area proportional to weight/count
  - Nested cluster rectangles
  - Color mapping from attributes

### mingle — Edge bundling (`pycode/mingle/`)
- **C reference:** `lib/mingle/`
- **Algorithm:** Agglomerative bundling + nearest-neighbor graphs
- **Best for:** Post-processing dense graphs to reduce clutter
- **Key features to implement:**
  - Edge compatibility scoring (angle, position, length)
  - Agglomerative clustering of compatible edges
  - Cubic Bézier control point computation for bundled edges
  - `bundleweight` attribute

## Suggested Implementation Order

1. **neato** — most commonly used after dot, well-documented algorithm
2. ~~**circo**~~ — **DONE**
3. **twopi** — straightforward BFS-based, useful for trees
4. **fdp** — similar to neato but with cluster support
5. **osage** — unique cluster-focused layout
6. **patchwork** — treemap is self-contained
7. **sfdp** — requires multi-level infrastructure
8. **mingle** — post-processor, not a layout engine
