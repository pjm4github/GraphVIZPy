# Build the trapezoid harness against the CLion-managed MinGW toolchain.
# Reuses libortho.a, libcommon.a, libutil.a already built under
# graphviz/cmake-build-debug-mingw.  Never reconfigures cmake — only
# compiles + links this standalone harness.

$ErrorActionPreference = "Stop"

$clion_mingw = "C:\Program Files\JetBrains\CLion 2023.2.2\bin\mingw"
$env:PATH = "$clion_mingw\bin;$env:PATH"

$gv = "C:\Users\pmora\OneDrive\Documents\Git\GitHub\graphviz"
$build = "$gv\cmake-build-debug-mingw"
$here = $PSScriptRoot

& "$clion_mingw\bin\gcc.exe" `
    -O0 -g -Wall -Wextra `
    "-I$gv\lib" `
    "-I$gv\lib\common" `
    "-I$gv\lib\ortho" `
    "-I$build" `
    "-I$build\lib" `
    "-I$build\lib\common" `
    "$here\harness.c" `
    "-L$build\lib\ortho" `
    "-L$build\lib\common" `
    "-L$build\lib\util" `
    "-L$build\lib\cdt" `
    -lortho -lcommon -lutil -lcdt -lm `
    -o "$here\harness.exe"

Write-Host "Built: $here\harness.exe"
