from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QImage
# Changes to this file may be overridden by the UI settings command
settings = {
    "HISTORY_FILE":                             "./logs/history.log",
    "APPLICATION_FONT_FAMILY":                  "MS Shell Dlg 2",
    "APPLICATION_FONT_POINT_SIZE":              10,
    "OUTPUT_PYTHON_PATH":                       "./outputs",
    "INPUT_SOURCE_PATH":                        "./inputs",
    "INCLUDE_FILE_PATH":                        ["./inputs", "./includes"],
    # These are the STD lib search location locations.
    "STDLIB":   [r"C:/Users/pmora/AppData/Local/Cygwin64/usr/include/sys/",
                 r"C:/Users/pmora/AppData/Local/Cygwin64/usr/local/etc/ghc/ghc-6.10.3/gcc-lib/install-filters/include/"],
    "RECURSIVE_INCLUDE":                        False,
    "SEQUENCE_FILE_PATH":                       "./sequences",
    "LOG_FILE_PATH":                            "./logs",
    "FONT_FAMILY":                              "Courier New",
    "FONT_POINT_SIZE":                          10,
    "CHECKMARK":                                QImage("icons/tick.png"),
    "EQUAL_COLOR":                              QColor(Qt.GlobalColor.black),
    "DELETE_COLOR":                             QColor(Qt.GlobalColor.red),
    "INSERT_COLOR":                             QColor(Qt.GlobalColor.darkGreen),
    "REPLACE_COLOR":                            QColor(Qt.GlobalColor.darkBlue),
    "EQUAL_BACKGROUND_COLOR":                   QColor(Qt.GlobalColor.white),
    "CHANGE_SOURCE_BACKGROUND_COLOR":           QColor(Qt.GlobalColor.yellow),
    "CHANGE_DESTINATION_BACKGROUND_COLOR":      QColor(Qt.GlobalColor.green),
}
