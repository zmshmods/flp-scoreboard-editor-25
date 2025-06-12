import os
import json
import tkinter as tk
from tkinter import filedialog, messagebox

# --- Constants and Configuration ---

# Define path for the external converter tool and script directory
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TEXCONV_PATH = os.path.join(SCRIPT_DIR, "texconv.exe")

def load_offsets_data():
    """
    Loads scoreboard offsets from offsets.json.
    Tries the default path first, then prompts the user if not found.
    """
    default_path = 'offsets.json'
    try:
        with open(default_path, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        messagebox.showwarning(
            "File Not Found",
            "offsets.json not found in the default location. Please select it manually."
        )
        # We need a temporary root to show the file dialog
        _temp_root_for_dialog = tk.Tk()
        _temp_root_for_dialog.withdraw()
        file_path_json = filedialog.askopenfilename(
            title="Select offsets.json file", filetypes=[("JSON files", "*.json")]
        )
        _temp_root_for_dialog.destroy()

        if not file_path_json:
            messagebox.showerror("Error", "No offsets.json selected. The application will exit.")
            return None
        try:
            with open(file_path_json, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError) as e:
            messagebox.showerror(
                "Error",
                f"Failed to read the selected offsets.json file: {e}\nThe application will exit."
            )
            return None
    except json.JSONDecodeError as e:
        messagebox.showerror(
            "Error",
            f"Failed to read the default offsets.json file: {e}\nThe application will exit."
        )
        return None

# Load the offset data at startup
OFFSETS_DATA = load_offsets_data()

# --- Static Application Configuration ---

# List of image files to cycle through
IMAGE_FILES = [str(i) for i in range(1, 81)]

# Default text properties for composite view
DEFAULT_TEXT_FONT_FAMILY = "Arial"
DEFAULT_TEXT_BASE_FONT_SIZE = 14
DEFAULT_TEXT_COLOR_FALLBACK = "white"

# Initial configuration for text elements in the composite view
# Format: (tag, text, gui_x, gui_y, design_font_size, font_size_offset_label, color_label_or_special_key, is_fixed, x_offset_label, base_game_x, y_offset_label, base_game_y)
INITIAL_TEXT_ELEMENTS_CONFIG = [
    ("text_hom", "HOM", 188, 19, 24, "Home Team Name Size", "Home Team Name Color", False, "Home Team Name X", 241, "Home Team Name Y", 17),
    ("text_awa", "AWA", 370, 19, 24, "Away Team Name Size", "Away Team Name Color", False, "Away Team Name X", 425, "Away Team Name Y", 17),
    ("text_score1", "1", 280, 22, 24, "Home Score Size", "Home Score Color", False, "Home Score X", 352, "Home Score Y", 17),
    ("text_score2", "2", 325, 22, 24, "Away Score Size", "Away Score Color", False, "Away Score X", 395, "Away Score Y", 17),
    ("text_time_min1", "1", 70, 23, 20, "Time Text Size", "Time Text Color", False, "1st Digit of Time (0--:--) X", -330, "1st Digit of Time (0--:--) Y", 2),
    ("text_time_min2", "0", 85, 23, 20, "Time Text Size", "Time Text Color", False, "2nd Digit of Time (-0-:--) X", -315, "2nd Digit of Time (-0-:--) Y", 2),
    ("text_time_min3", "5", 100, 23, 20, "Time Text Size", "Time Text Color", False, "3rd Digit of Time (--0:--) X", -300, "3rd Digit of Time (--0:--) Y", 2),
    ("text_time_colon", ":", 116, 20, 20, "Time Text Size", "Time Text Color", False, "Colon Separator of Time (---:--) X", -290, "Colon Separator of Time (---:--) Y", -2),
    ("text_time_sec1", "3", 125, 23, 20, "Time Text Size", "Time Text Color", False, "4th Digit of Time (---:0-) X", -280, "4th Digit of Time (---:0-) Y", 2),
    ("text_time_sec2", "8", 140, 23, 20, "Time Text Size", "Time Text Color", False, "5th Digit of Time (---:-0) X", -265, "5th Digit of Time (---:-0) Y", 2),
    ("text_added_time", "+9", 120, 67, 22, "PlaceHolder", "Added Time Text Color", False, "Added Time X", 130, "Added Time Y", 83),
]

# Labels for color values that are text-based ("WHITE"/"BLACK") instead of hex
SPECIAL_TEXT_COLOR_LABELS = ["Added Time Text Color"]

# Predefined coordinates and linking info for images in the composite view
# Format: { 'tag': (gui_x, gui_y, x_offset_label, base_game_x, y_offset_label, base_game_y) }
PREDEFINED_IMAGE_COORDS = {
    "img_10": (5.0, 5.0, None, None, None, None),
    "img_14": (104, 51, None, None, None, None),
    "img_30_orig": (51, -6, "Home Color Bar X", 233, "Home Color Bar Y", 286),
    "img_30_dup": (313, -6, "Away Color Bar X", 586, "Away Color Bar Y", 286)
    
}