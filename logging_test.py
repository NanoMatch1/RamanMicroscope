import logging
from logging.handlers import RotatingFileHandler
import os
# Create demo log file paths
scriptDir = os.path.dirname(os.path.abspath(__file__))
logDir = os.path.join(scriptDir, "logs")
if not os.path.exists(logDir):
    os.makedirs(logDir)
log_file = os.path.join(logDir, "demo.log")
rotating_log_file = os.path.join(logDir, "demo_rotating.log")


# 1. Configure root logger
logger = logging.getLogger('demo_logger')
logger.setLevel(logging.DEBUG)

# 2. FileHandler (INFO level and above)
file_handler = logging.FileHandler(log_file) # writes to the file, in append by default
file_handler.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s %(name)s [%(levelname)s] %(message)s')
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

# 3. RotatingFileHandler (DEBUG level and above, small size for demo)
rot_handler = RotatingFileHandler(rotating_log_file, maxBytes=200, backupCount=2)
rot_handler.setLevel(logging.DEBUG)
rot_handler.setFormatter(formatter)
logger.addHandler(rot_handler)

# 4. Emit a variety of log messages
logger.debug("DEBUG: This will appear only in the rotating log.")
logger.info("INFO: Standard informational message.")
logger.warning("WARNING: Something to watch out for.")
logger.error("ERROR: A non-fatal error occurred.")
try:
    1 / 0
except ZeroDivisionError:
    logger.exception("EXCEPTION: Caught division by zero!")

# 5. Generate extra debug entries to trigger rotation
for i in range(20):
    logger.debug(f"Rotating entry #{i}")

# 6. Read and display log file contents
print("=== demo.log (INFO+ messages) ===")
with open(log_file, 'r') as f:
    print(f.read())

print("=== demo_rotating.log (latest DEBUG+ messages) ===")
with open(rotating_log_file, 'r') as f:
    print(f.read())

print("=== Backup files: ===")
import glob
for backup in sorted(glob.glob(rotating_log_file + ".*")):
    print(f"\n--- {backup} ---")
    print(open(backup).read())
