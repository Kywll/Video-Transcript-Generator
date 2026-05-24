import os

# Directories
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
DOWNLOAD_DIR = os.path.join(BASE_DIR, "downloads")

# File limits
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB
MAX_VIDEO_DURATION = 120  # seconds

# Cleanup delays
CLEANUP_DELAY_VIDEO = 900  # 15 minutes
CLEANUP_DELAY_AUDIO = 1800  # 30 minutes

# Job queue
NUM_WORKERS = 2
JOB_TIMEOUT = 120000  # 2 minutes