/*
 * Standalone harness for lib/ortho/partition.c::partition.
 *
 * Reads an outer bounding box + cell bboxes from a text fixture, runs
 * partition(), and prints the decomposition rectangles to stdout.
 * Output is sorted lexicographically so parity tests can diff against
 * the Python port without depending on C-vs-Python RNG agreement
 * (partition() uses srand48(173) + drand48() internally to randomize
 * segment-insertion order; the final rectangle set is deterministic
 * but its numbering in the raw array is not).
 *
 * Fixture format (all numbers space-separated):
 *   <ncells>
 *   <bb.LL.x> <bb.LL.y> <bb.UR.x> <bb.UR.y>
 *   <cell[0].LL.x> <cell[0].LL.y> <cell[0].UR.x> <cell[0].UR.y>
 *   <cell[1].LL.x> <cell[1].LL.y> <cell[1].UR.x> <cell[1].UR.y>
 *   ...
 *
 * Output format:
 *   partition_result ncells=<n> nrects=<m>
 *   rect LL=<x>,<y> UR=<x>,<y>
 *   rect LL=<x>,<y> UR=<x>,<y>
 *   ...
 *
 * The per-rect lines are sorted by (LL.x, LL.y, UR.x, UR.y) so the
 * output is canonical regardless of internal trapezoid ordering.
 *
 * Link line: see build.ps1 (reuses libortho.a etc. from the CLion
 * MinGW build tree).
 */

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

#include <common/geom.h>
#include <ortho/maze.h>
#include <ortho/partition.h>

/*
 * Provide local drand48/srand48 shims so we can avoid linking libcommon.a
 * (whose object file chain drags libgvc + libcgraph + …).  These match
 * the fallback in common/utils.c:1550 exactly so partition()'s RNG
 * behaviour is identical to a full dot.exe run on the same Windows
 * toolchain.
 */
double drand48(void) { return (double)rand() / (double)RAND_MAX; }
void srand48(long seed) { srand((unsigned)seed); }

static void die(const char *msg) {
    fprintf(stderr, "harness error: %s\n", msg);
    exit(1);
}

static int cmp_boxf(const void *a, const void *b) {
    const boxf *x = (const boxf *)a;
    const boxf *y = (const boxf *)b;
    if (x->LL.x < y->LL.x) return -1;
    if (x->LL.x > y->LL.x) return 1;
    if (x->LL.y < y->LL.y) return -1;
    if (x->LL.y > y->LL.y) return 1;
    if (x->UR.x < y->UR.x) return -1;
    if (x->UR.x > y->UR.x) return 1;
    if (x->UR.y < y->UR.y) return -1;
    if (x->UR.y > y->UR.y) return 1;
    return 0;
}

int main(int argc, char **argv) {
    if (argc != 2) {
        fprintf(stderr, "usage: %s <fixture.in>\n", argv[0]);
        return 1;
    }

    FILE *f = fopen(argv[1], "r");
    if (!f) die("cannot open fixture");

    size_t ncells = 0;
    if (fscanf(f, "%zu", &ncells) != 1) die("bad ncells");

    boxf bb = {0};
    if (fscanf(f, "%lf %lf %lf %lf",
               &bb.LL.x, &bb.LL.y, &bb.UR.x, &bb.UR.y) != 4) {
        die("bad bb");
    }

    cell *cells = NULL;
    if (ncells > 0) {
        cells = calloc(ncells, sizeof(cell));
        if (!cells) die("oom cells");
        for (size_t i = 0; i < ncells; i++) {
            if (fscanf(f, "%lf %lf %lf %lf",
                       &cells[i].bb.LL.x, &cells[i].bb.LL.y,
                       &cells[i].bb.UR.x, &cells[i].bb.UR.y) != 4) {
                die("bad cell row");
            }
        }
    }
    fclose(f);

    size_t nrects = 0;
    boxf *rects = partition(cells, ncells, &nrects, bb);

    qsort(rects, nrects, sizeof(boxf), cmp_boxf);

    printf("partition_result ncells=%zu nrects=%zu\n", ncells, nrects);
    for (size_t i = 0; i < nrects; i++) {
        printf("rect LL=%.6f,%.6f UR=%.6f,%.6f\n",
               rects[i].LL.x, rects[i].LL.y,
               rects[i].UR.x, rects[i].UR.y);
    }

    free(rects);
    free(cells);
    return 0;
}
