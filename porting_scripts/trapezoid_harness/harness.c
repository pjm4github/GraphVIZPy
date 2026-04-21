/*
 * Standalone harness for lib/ortho/trapezoid.c::construct_trapezoids.
 *
 * Reads a segment set + insertion permutation from a text fixture and
 * prints the resulting trapezoid list to stdout.  The output is
 * line-comparable against the Python port's [TRACE ortho-trapezoid]
 * emissions and drives the Phase 3 parity tests.
 *
 * Fixture format (one-indexed segments, matching C's seg[1..nseg]):
 *   <nseg>
 *   <v0x> <v0y> <v1x> <v1y> <next> <prev>   # segment 1
 *   <v0x> <v0y> <v1x> <v1y> <next> <prev>   # segment 2
 *   ...
 *   <p1> <p2> ... <pN>                       # permutation (1-indexed)
 *
 * Output format (one line per valid trap, sentinel trap 0 skipped):
 *   trap i=<N> lseg=<N> rseg=<N> hi=<X>,<Y> lo=<X>,<Y>
 *        u0=<N> u1=<N> d0=<N> d1=<N>
 *
 * u0/u1/d0/d1 emit literal `-1` for SIZE_MAX (C's "explicitly invalid"
 * sentinel) and `0` for "unset" — matches the Python port's
 * INVALID_TRAP/UNSET_TRAP convention.
 *
 * Link line (from the repo root):
 *   gcc -O0 -g -I../../lib -I../../lib/common -I../../build/mingw/lib \
 *       harness.c \
 *       -L<build>/lib/ortho -L<build>/lib/common -L<build>/lib/util \
 *       -lortho -lcommon -lutil -lm -o harness.exe
 *
 * See build.ps1 for the exact invocation against the CLion MinGW tree.
 */

#include <float.h>
#include <inttypes.h>
#include <math.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

#include <common/geom.h>
#include <ortho/trap.h>
#include <util/list.h>

static void die(const char *msg) {
    fprintf(stderr, "harness error: %s\n", msg);
    exit(1);
}

static void emit_idx(const char *label, size_t v) {
    /* Mirror the Python port:
     *   SIZE_MAX -> -1
     *   0        -> 0 (unset)
     *   otherwise -> decimal
     */
    if (v == SIZE_MAX) {
        printf(" %s=-1", label);
    } else {
        printf(" %s=%zu", label, v);
    }
}

/* init_query_structure seeds the topmost/bottommost trapezoids with
 * DBL_MAX / -DBL_MAX as y-infinity sentinels.  Round-tripping those
 * through printf gives unreadable 309-digit numerals; collapse them
 * so the expected output stays human-readable and the Python port
 * can match with its own INF / -INF symbols.
 */
static void emit_pt(const char *label, pointf p) {
    printf(" %s=", label);
    if (p.x >= DBL_MAX * 0.5)      printf("INF,");
    else if (p.x <= -DBL_MAX * 0.5) printf("-INF,");
    else                            printf("%.6f,", p.x);
    if (p.y >= DBL_MAX * 0.5)      printf("INF");
    else if (p.y <= -DBL_MAX * 0.5) printf("-INF");
    else                            printf("%.6f", p.y);
}

int main(int argc, char **argv) {
    if (argc != 2) {
        fprintf(stderr, "usage: %s <fixture.in>\n", argv[0]);
        return 1;
    }

    FILE *f = fopen(argv[1], "r");
    if (!f) die("cannot open fixture");

    int nseg = 0;
    if (fscanf(f, "%d", &nseg) != 1 || nseg < 1) die("bad nseg");

    /* C expects seg[0] unused and seg[1..nseg] populated.
     * Allocate nseg+1 slots, zero-init.
     */
    segment_t *seg = calloc((size_t)(nseg + 1), sizeof(segment_t));
    if (!seg) die("oom seg");

    for (int i = 1; i <= nseg; i++) {
        int next, prev;
        if (fscanf(f, "%lf %lf %lf %lf %d %d",
                   &seg[i].v0.x, &seg[i].v0.y,
                   &seg[i].v1.x, &seg[i].v1.y,
                   &next, &prev) != 6) {
            die("bad segment row");
        }
        seg[i].next = next;
        seg[i].prev = prev;
        seg[i].is_inserted = false;
        seg[i].root0 = 0;
        seg[i].root1 = 0;
    }

    /* Permutation is 0-indexed in C, holds 1-indexed segment numbers. */
    int *permute = calloc((size_t)(nseg + 1), sizeof(int));
    if (!permute) die("oom permute");
    for (int i = 0; i < nseg; i++) {
        if (fscanf(f, "%d", &permute[i]) != 1) die("bad permute");
    }
    fclose(f);

    traps_t tr = construct_trapezoids(nseg, seg, permute);

    /* Emit every valid trap; skip the sentinel at index 0. */
    size_t ntraps = LIST_SIZE(&tr);
    printf("trapezoids ntraps=%zu\n", ntraps);
    for (size_t i = 1; i < ntraps; i++) {
        trap_t *t = LIST_AT(&tr, i);
        if (!t->is_valid) continue;
        printf("trap i=%zu lseg=%d rseg=%d", i, t->lseg, t->rseg);
        emit_pt("hi", t->hi);
        emit_pt("lo", t->lo);
        emit_idx("u0", t->u0);
        emit_idx("u1", t->u1);
        emit_idx("d0", t->d0);
        emit_idx("d1", t->d1);
        printf("\n");
    }

    LIST_FREE(&tr);
    free(seg);
    free(permute);
    return 0;
}
