
import logging
from enum import Enum

# Example error level enumeration similar to your Agerrlevel.
class Agerrlevel(Enum):
    AGERR = "error"
    AGWARN = "warning"
    AGINFO = "info"

# Configure a logger for this module
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)  # or INFO, WARNING, etc.

# https://github.com/Lightning-AI/pytorch-lightning/issues/16081

class ColorHandler(logging.StreamHandler):
    # https://en.wikipedia.org/wiki/ANSI_escape_code#Colors
    GRAY8 = "38;5;8"
    GRAY7 = "38;5;7"
    TEAL8 = "38;5;93"
    ORANGE = "33"
    RED = "31"
    WHITE = "0"

    def emit(self, record):
        # Don't use white for any logging, to help distinguish from user print statements
        level_color_map = {
            logging.DEBUG: self.GRAY8,
            logging.INFO: self.TEAL8,
            logging.WARNING: self.ORANGE,
            logging.ERROR: self.RED,
        }

        csi = f"{chr(27)}["  # control sequence introducer
        color = level_color_map.get(record.levelno, self.WHITE)

        self.stream.write(f"{csi}{color}m{self.format(record)}{csi}m\n")


# logging.getLogger(__name__).addHandler(ColorHandler())

# Optionally, add a handler if not already configured by the root logger.
if not logger.hasHandlers():
    handler = ColorHandler()
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)


class Agerrlevel(Enum):
    """
    Enumeration for error levels used in agerr function.
    """
    AGINFO = 0
    AGWARN = 1
    AGERR = 2
    AGMAX = 3
    AGPREV = 4


def agerr(level: Agerrlevel, message: str, *args, **kwargs):
    if level == Agerrlevel.AGERR:
        logger.error(message, *args, **kwargs)
        # raise RuntimeError(message % args)
    elif level == Agerrlevel.AGWARN:
        logger.warning(message, *args, **kwargs)
    else:
        logger.info(message, *args, **kwargs)
