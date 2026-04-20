# Build the partition harness against the CLion MinGW toolchain.
# Reuses libortho.a / libcommon.a / libutil.a / libcdt.a — never
# reconfigures the cmake cache in the graphviz build tree.

$ErrorActionPreference = "Stop"

$clion_mingw = "C:\Program Files\JetBrains\CLion 2023.2.2\bin\mingw"
$env:PATH = "$clion_mingw\bin;$env:PATH"

$gv = "C:\Users\pmora\OneDrive\Documents\Git\GitHub\graphviz"
$build = "$gv\cmake-build-debug-mingw"
$here = $PSScriptRoot

# Link directly against the two ortho object files we need, plus libutil.
# This dodges libcommon.a's libgvc dependency chain — partition.c calls
# only inline helpers from common, plus drand48/srand48 which the harness
# provides locally.
$obj_dir = "$build\lib\ortho\CMakeFiles\ortho_obj.dir"

& "$clion_mingw\bin\gcc.exe" `
    -O0 -g -Wall -Wextra `
    "-I$gv\lib" `
    "-I$gv\lib\common" `
    "-I$gv\lib\ortho" `
    "-I$gv\lib\gvc" `
    "-I$gv\lib\cdt" `
    "-I$gv\lib\cgraph" `
    "-I$gv\lib\pathplan" `
    "-I$build" `
    "-I$build\lib" `
    "-I$build\lib\common" `
    "$here\harness.c" `
    "$obj_dir\partition.c.obj" `
    "$obj_dir\trapezoid.c.obj" `
    "-L$build\lib\util" `
    "-L$build\lib\cdt" `
    -lutil -lcdt -lm `
    -o "$here\harness.exe"

Write-Host "Built: $here\harness.exe"
