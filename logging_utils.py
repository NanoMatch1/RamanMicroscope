
import logging
from PyQt5.QtCore import QObject, pyqtSignal

class QtLogHandler(logging.Handler, QObject):
    """
    A logging.Handler that emits each record as a Qt signal (str).
    """
    logMessage = pyqtSignal(str)

    def __init__(self):
        logging.Handler.__init__(self)
        QObject.__init__(self)

    def emit(self, record):
        msg = self.format(record)
        # Emit the formatted message to any connected slots
        self.logMessage.emit(msg)


class LoggerInterface:
    def __init__(self, name: str = 'instrument'):
        # 1) Define your level number and name
        COMMAND_LEVEL_NUM = 15
        logging.addLevelName(COMMAND_LEVEL_NUM, "CMD")

        # 2) Attach a .command(...) method to all Logger instances
        def cmd(self, message, *args, **kwargs):
            # analogous to logger.info, logger.error, etc.
            if self.isEnabledFor(COMMAND_LEVEL_NUM):
                self._log(COMMAND_LEVEL_NUM, message, args, **kwargs)

        logging.Logger.cmd = cmd
        # 1) Grab or create the root logger for your system
        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.DEBUG)

        # 2) Configure your handlers just once
        self.file_handler = logging.FileHandler('instrument_errors.log')
        self.file_handler.setLevel(logging.ERROR)
        self.file_handler.setFormatter(logging.Formatter(
            '%(asctime)s %(name)s [%(levelname)s] %(message)s'
        ))

        self.cli_handler = logging.StreamHandler()       # CLI/stdout handler
        self.cli_handler.setLevel(logging.DEBUG)
        self.cli_handler.setFormatter(logging.Formatter('[%(levelname)s] %(message)s'))

        # self.qt_handler = QtLogHandler()
        # self.qt_handler.setLevel(logging.DEBUG)
        # self.qt_handler.setFormatter(logging.Formatter('%(message)s'))

        # 3) Attach them
        self.handlers = [self.file_handler, self.cli_handler]
        for h in self.handlers:
            # Add the handler to the logger
            self.logger.addHandler(h)

    def modify_handler(self, handler: str, level: int):
        """
        Modify the level of a handler.
        """
        handler = getattr(self, handler, None)
        if handler is None:
            raise ValueError("Handler not found.")
        handler.setLevel(level)


    def getChild(self, suffix: str):
        """
        Return a LoggerInterface wrapping the child logger
        instrument.<suffix>, inheriting handlers.
        """
        child = self.logger.getChild(suffix)
        child.setLevel(logging.DEBUG)
        return self.__class__.from_logger(child)

    @classmethod
    def from_logger(cls, logger_obj: logging.Logger):
        """
        Internal helper to wrap an existing Logger without
        reconfiguring handlers.
        """
        inst = cls.__new__(cls)
        inst.logger = logger_obj
        return inst

    def __getattr__(self, attr):
        """
        Delegate any unknown attribute or method call to the
        underlying Logger.  That means interface.info(...),
        interface.error(...), etc. all work.
        """
        return getattr(self.logger, attr)