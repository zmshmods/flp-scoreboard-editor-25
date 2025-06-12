import os
import logging
from typing import Optional

def format_filesize(byte_count: int) -> str:
    """Formats a size in bytes into a human-readable string (KB, MB)."""
    if byte_count < 1024:
        return f"{byte_count} bytes"
    elif byte_count < 1024 * 1024:
        return f"{byte_count / 1024:.2f} KB"
    else:
        return f"{byte_count / (1024 * 1024):.2f} MB"

def read_internal_name(file_path: str) -> Optional[str]:
    """
    Reads the beginning of a file to detect a known internal scoreboard name.
    """
    if not file_path or not os.path.exists(file_path):
        return None
    try:
        with open(file_path, 'rb') as f:
            content = f.read(200 * 1024)  # Read first 200KB
        text = content.decode('utf-8', errors='ignore')
        
        # List of known internal names to search for
        names_to_check = ["15002", "2002", "3002", "4002", "5002", "6002", "8002"]
        for name in names_to_check:
            if name in text:
                return name
        return None
    except Exception as e:
        logging.error(f"Failed to read internal name from {file_path}: {e}")
        return None