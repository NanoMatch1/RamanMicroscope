import logging

COMMAND_LEVEL_NUM = 5
logging.addLevelName(COMMAND_LEVEL_NUM, "COMS")

def coms(self, message, *args, **kwargs):
    if self.isEnabledFor(COMMAND_LEVEL_NUM):
        self._log(COMMAND_LEVEL_NUM, message, args, **kwargs)

logging.Logger.coms = coms

logger = logging.getLogger("test")
logger.setLevel(COMMAND_LEVEL_NUM)

handler = logging.StreamHandler()
handler.setLevel(COMMAND_LEVEL_NUM)
formatter = logging.Formatter('[%(levelname)s](%(name)s): %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)

print(logger.level)
logger.setLevel(1)  # Set to DEBUG to see all messages
logger.coms("This is a COMS message")
logger.debug("This won't show unless level is <= 10")
