Rename, tools to Filters
    gvpy/tools/ → keep it, rename it gvpy/filters/
The Graphviz project itself calls these graph filters — they're in cmd/ in the C source (acyclic, ccomps, tred, sccmap etc. are all filter programs).
Renaming to filters or graph_filters makes the purpose immediately clear:

    gvpy/
        filters/              ← was gvpy/tools/
            __init__.py
            acyclic.py
            ccomps.py
            tred.py
            sccmap.py
            bcomps.py
            mingle.py         ← post-processor, fits here too
            gvgen.py
            gc.py
            gvcolor.py
            nop.py
            unflatten.py
            edgepaint.py


User-facing import stays clean:

    from gvpy.filters import ccomps, tred, acyclic