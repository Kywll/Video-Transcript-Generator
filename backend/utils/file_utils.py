import os
import threading
import time

def delete_later(path, delay=900):
    """Delete a file after a delay (in seconds)"""
    def _delete():
        time.sleep(delay)
        if os.path.exists(path):
            os.remove(path)
    threading.Thread(target=_delete, daemon=True).start()

def ensure_dir_exists(dir_path):
    """Create directory if it doesn't exist"""
    os.makedirs(dir_path, exist_ok=True)