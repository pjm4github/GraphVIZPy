"""Per-character width tables for standard PostScript fonts.

Used for text sizing in record field layout and node dimension
computation.  Values are character widths in 1/1000 of the font size
(the standard AFM/PostScript metric convention).

C reference: Graphviz uses the system font engine (GDI+, Cairo, etc.)
for exact text metrics.  These tables provide a close approximation
without requiring a font engine.

TODO: Revisit this module when integrating with pictosync's font
rendering.  May want to:
- Add more fonts (Helvetica, Courier, etc.)
- Use actual font metrics from the rendering engine
- Support font fallback chains
"""

# Times-Roman character widths in 1/1000 of font size.
# Source: Adobe AFM file for Times-Roman (standard PostScript metrics).
# These are the same values used by PostScript interpreters worldwide.
TIMES_ROMAN_WIDTHS: dict[str, int] = {
    ' ': 250, '!': 333, '"': 408, '#': 500, '$': 500,
    '%': 833, '&': 778, "'": 333, '(': 333, ')': 333,
    '*': 500, '+': 564, ',': 250, '-': 333, '.': 250,
    '/': 278, '0': 500, '1': 500, '2': 500, '3': 500,
    '4': 500, '5': 500, '6': 500, '7': 500, '8': 500,
    '9': 500, ':': 278, ';': 278, '<': 564, '=': 564,
    '>': 564, '?': 444, '@': 921, 'A': 722, 'B': 667,
    'C': 667, 'D': 722, 'E': 611, 'F': 556, 'G': 722,
    'H': 722, 'I': 333, 'J': 389, 'K': 722, 'L': 611,
    'M': 889, 'N': 722, 'O': 722, 'P': 556, 'Q': 722,
    'R': 667, 'S': 556, 'T': 611, 'U': 722, 'V': 722,
    'W': 944, 'X': 722, 'Y': 722, 'Z': 611, '[': 333,
    '\\': 278, ']': 333, '^': 469, '_': 500, '`': 333,
    'a': 444, 'b': 500, 'c': 444, 'd': 500, 'e': 444,
    'f': 333, 'g': 500, 'h': 500, 'i': 278, 'j': 278,
    'k': 500, 'l': 278, 'm': 778, 'n': 500, 'o': 500,
    'p': 500, 'q': 500, 'r': 333, 's': 389, 't': 278,
    'u': 500, 'v': 500, 'w': 722, 'x': 500, 'y': 500,
    'z': 444, '{': 480, '|': 200, '}': 480, '~': 541,
}

# Default width for characters not in the table
TIMES_ROMAN_DEFAULT_WIDTH = 500


def text_width_times_roman(text: str, fontsize: float) -> float:
    """Compute text width in points using Times-Roman metrics.

    Args:
        text: The text string to measure.
        fontsize: Font size in points.

    Returns:
        Width in points.
    """
    if not text:
        return 0.0
    total = sum(TIMES_ROMAN_WIDTHS.get(ch, TIMES_ROMAN_DEFAULT_WIDTH)
                for ch in text)
    return total * fontsize / 1000.0


def avg_char_width_times_roman(fontsize: float) -> float:
    """Average character width for Times-Roman at given font size.

    Useful as a fallback when per-character measurement isn't needed.
    Computed from the full ASCII range weighted equally.
    """
    widths = list(TIMES_ROMAN_WIDTHS.values())
    avg = sum(widths) / len(widths) if widths else 500
    return avg * fontsize / 1000.0
