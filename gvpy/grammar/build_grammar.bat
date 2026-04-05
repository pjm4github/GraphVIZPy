@echo off
REM build_grammar.bat
REM Compiles GVLexer.g4 + GVParser.g4 into Python3 lexer, parser, and visitor.

set JAR=C:\javalib\antlr-4.13.0-complete.jar
set G4_DIR=%~dp0
set OUT_DIR=%G4_DIR%generated

echo.
echo === ANTLR4 Grammar Compile (GV) ===
echo G4 dir:  %G4_DIR%
echo Out dir: %OUT_DIR%
echo.

java -jar "%JAR%" ^
     -Dlanguage=Python3 ^
     -visitor ^
     -no-listener ^
     -o "%OUT_DIR%" ^
     -lib "%OUT_DIR%" ^
     "%G4_DIR%GVLexer.g4" ^
     "%G4_DIR%GVParser.g4"

if %ERRORLEVEL% == 0 (
    echo.
    echo === Compile OK ===
) else (
    echo.
    echo === Compile FAILED ===
    exit /b 1
)
