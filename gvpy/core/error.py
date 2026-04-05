"""
Error handling and logging for the core package.
"""
import logging
from enum import Enum


class Agerrlevel(Enum):
    """Error levels matching Graphviz agerr() severity."""
    AGINFO = 0
    AGWARN = 1
    AGERR = 2
    AGMAX = 3
    AGPREV = 4


logger = logging.getLogger(__name__)
logger.setLevel(logging.WARNING)


class ColorHandler(logging.StreamHandler):
    """ANSI color-coded log handler."""
    GRAY8 = "38;5;8"
    TEAL8 = "38;5;93"
    ORANGE = "33"
    RED = "31"
    WHITE = "0"

    def emit(self, record):
        level_color_map = {
            logging.DEBUG: self.GRAY8,
            logging.INFO: self.TEAL8,
            logging.WARNING: self.ORANGE,
            logging.ERROR: self.RED,
        }
        csi = f"{chr(27)}["
        color = level_color_map.get(record.levelno, self.WHITE)
        self.stream.write(f"{csi}{color}m{self.format(record)}{csi}m\n")


if not logger.hasHandlers():
    handler = ColorHandler()
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)


def agerr(level: Agerrlevel, message: str, *args, **kwargs):
    """Log a message at the specified Graphviz error level."""
    if level == Agerrlevel.AGERR:
        logger.error(message, *args, **kwargs)
    elif level == Agerrlevel.AGWARN:
        logger.warning(message, *args, **kwargs)
    else:
        logger.info(message, *args, **kwargs)
