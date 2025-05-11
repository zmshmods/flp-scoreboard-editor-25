import tkinter as tk
from tkinter import filedialog, messagebox, ttk, colorchooser
import struct
import webbrowser
import os
import tempfile
from PIL import Image, ImageTk
import json
import logging
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Dict, Any

# Configure logging
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s')

# Load offsets from JSON file
try:
    with open('offsets.json', 'r') as f:
        offsets_data = json.load(f)
except FileNotFoundError:
    logging.warning(
        "offsets.json not found in default path. Prompting user.")
    messagebox.showwarning("File not found",
                           "offsets.json not found in default location. Please select manually.")
    # Need a root window for filedialog if it's called this early
    # For now, assuming root will be created before this becomes a hard error if the initial load fails
    # This initial load failure logic might need adjustment if root isn't available for filedialog
    # A simple solution: make root a global earlier or handle this post-root creation.
    # However, the code structure tries to load it immediately.
    # If Tk() is not yet called, filedialog will raise an error.
    # For now, I'll proceed, but this is a potential initialization order issue.
    _temp_root_for_dialog = tk.Tk()
    _temp_root_for_dialog.withdraw() # Hide the temporary root window
    file_path_json = filedialog.askopenfilename(
        title="Select offsets.json file", filetypes=[("JSON files", "*.json")])
    _temp_root_for_dialog.destroy()

    if not file_path_json:
        messagebox.showerror(
            "Error", "No offsets.json selected. Application will exit.")
        # Can't destroy root here if it's not the main one yet.
        exit()
    try:
        with open(file_path_json, 'r') as f:
            offsets_data = json.load(f)
    except json.JSONDecodeError:
        logging.error("Error decoding selected offsets.json.")
        messagebox.showerror(
            "Error", "Error reading selected offsets.json file. The application will be terminated.")
        exit()
    except FileNotFoundError: # Should not happen if file_path_json was selected
        logging.error("Selected offsets.json somehow not found.")
        messagebox.showerror(
            "Error", "Selected offsets.json file not found. The application will be terminated.")
        exit()

except json.JSONDecodeError:
    logging.error("Error decoding default offsets.json.")
    messagebox.showerror(
        "Error", "Error reading default offsets.json file. The application will be terminated.")
    exit()

file_path: Optional[str] = None
offsets = {}
colors = {}
current_image: Optional[Image.Image] = None

original_loaded_offsets = {}
original_loaded_colors = {}

preview_bg_color_is_white = True
current_image_index = 0
image_files = [str(i) for i in range(1, 81)] # Default for many scoreboards

single_view_zoom_level = 1.0
single_view_pan_offset_x = 0.0
single_view_pan_offset_y = 0.0
drag_data = {"x": 0, "y": 0, "item": None,
             "is_panning": False, "is_panning_rmb": False}

composite_mode_active = False
composite_elements: List[Dict[str, Any]] = []
current_reference_width: Optional[int] = None
current_reference_height: Optional[int] = None
composite_drag_data = {
    "x": 0, "y": 0, "item": None, "element_data": None,
    "start_original_x": 0.0, "start_original_y": 0.0,
    "initial_game_offset_x_at_drag_start": 0.0,
    "initial_game_offset_y_at_drag_start": 0.0
}
composite_zoom_level = 1.0
composite_pan_offset_x = 0.0
composite_pan_offset_y = 0.0

DEFAULT_TEXT_FONT_FAMILY = "Arial"
DEFAULT_TEXT_BASE_FONT_SIZE = 14
DEFAULT_TEXT_COLOR_FALLBACK = "white"

initial_text_elements_config = [
    ("text_hom", "HOM", 185, 22, 22, "Home Team Name Color",
     False, "Home Team Name X", 241, "Home Team Name Y", 17),
    ("text_awa", "AWA", 375, 22, 22, "Away Team Name Color",
     False, "Away Team Name X", 425, "Away Team Name Y", 17),
    ("text_score1", "1", 280, 22, 22, "Home Score Color",
     False, "Home Score X", 352, "Home Score Y", 17),
    ("text_score2", "2", 325, 22, 22, "Away Score Color",
     False, "Away Score X", 395, "Away Score Y", 17),
    ("text_time_min1",  "2", 63, 23, 22, "Time Text Color", False,
     "1st Digit of Time (0--:--) X", -330, "1st Digit of Time (0--:--) Y", 2),
    ("text_time_min2",  "3", 80, 23, 22, "Time Text Color", False,
     "2nd Digit of Time (-0-:--) X", -315, "2nd Digit of Time (-0-:--) Y", 2),
    ("text_time_min3",  "4", 98, 23, 22, "Time Text Color", False,
     "3rd Digit of Time (--0:--) X", -300, "3rd Digit of Time (--0:--) Y", 2),
    ("text_time_colon", ":", 113, 20, 22, "Time Text Color", False,
     "Colon Seperator of Time (---:--) X", -290, "Colon Seperator of Time (---:--) Y", -2),
    ("text_time_sec1",  "5", 123, 23, 22, "Time Text Color", False,
     "4th Digit of Time (---:0-) X", -280, "4th Digit of Time (---:0-) Y", 2),
    ("text_time_sec2",  "6", 138, 23, 22, "Time Text Color", False,
     "5th Digit of Time (---:-0) X", -265, "5th Digit of Time (---:-0) Y", 2),
    ("text_added_time", "+9", 120, 67, 22, None, # Color None means use fallback or specific logic
     False, "Added Time X", 130, "Added Time Y", 83),
]

predefined_image_coords: Dict[str, tuple[float, float, Optional[str], Optional[float], Optional[str], Optional[float]]] = {
    "img_10":       (5.0, 5.0, None, None, None, None), # Base image, no game offsets to link, fixed
    "img_14":       (104, 51, None, None, None, None), # Positioned relative to text_added_time, not directly linked to offsets
    "img_30_orig":  (135, 8, "Home Color Bar X", 212, "Home Color Bar Y", 103.5),
    "img_30_dup":   (436, 8, "Away Color Bar X", 502, "Away Color Bar Y", 103.5)
}

highlighted_offset_entries = [] # Stores (widget, original_bg) tuples


class EditAction:
    def __init__(self, string_var, old_value, new_value, key_tuple, entry_widget_ref, description="value change"):
        self.string_var = string_var
        self.old_value = old_value
        self.new_value = new_value
        self.key_tuple = key_tuple # The offset list (as tuple) or color list (as tuple)
        self.entry_widget_ref = entry_widget_ref # Reference to the tk.Entry widget if applicable
        self.description = description

    def undo(self):
        self.string_var.set(self.old_value)

    def redo(self):
        self.string_var.set(self.new_value)

    def __str__(self):
        return f"EditAction({self.description}: {self.old_value} -> {self.new_value})"


class UndoManager:
    def __init__(self, max_history=50):
        self.undo_stack: List[EditAction] = []
        self.redo_stack: List[EditAction] = []
        self.max_history = max_history

    def record_action(self, action: EditAction):
        self.redo_stack.clear()
        self.undo_stack.append(action)
        if len(self.undo_stack) > self.max_history:
            self.undo_stack.pop(0)
        self.update_menu_states()
        logging.debug(f"Recorded action: {action}")

    def can_undo(self):
        return bool(self.undo_stack)

    def can_redo(self):
        return bool(self.redo_stack)

    def _apply_action_and_update_ui(self, action_to_apply: EditAction, is_undo: bool):
        logging.debug(f"Applying {'undo' if is_undo else 'redo'} for: {action_to_apply}")
        if is_undo:
            action_to_apply.undo()
        else:
            action_to_apply.redo()

        # After setting the variable, trigger the appropriate update logic
        is_offset_var = False
        if hasattr(root, 'offsets_vars'):
            for key, var in root.offsets_vars.items():
                if var == action_to_apply.string_var:
                    # Pass from_undo_redo=True to prevent re-recording and handle UI updates
                    update_value(key, action_to_apply.string_var, from_undo_redo=True)
                    is_offset_var = True
                    break
        
        if not is_offset_var and hasattr(root, 'color_vars'):
            for key, var in root.color_vars.items():
                if var == action_to_apply.string_var:
                    update_color_preview_from_entry(key, action_to_apply.string_var, from_undo_redo=True)
                    break
        
        # Ensure focus is sensible if an entry widget was involved
        if action_to_apply.entry_widget_ref and isinstance(action_to_apply.entry_widget_ref, tk.Entry):
            try:
                action_to_apply.entry_widget_ref.focus_set()
                action_to_apply.entry_widget_ref.selection_range(0, tk.END)
            except tk.TclError:
                logging.debug("TclError focusing widget during undo/redo, widget might be destroyed.")

        self.update_menu_states()


    def undo(self):
        if not self.can_undo():
            return
        action = self.undo_stack.pop()
        self._apply_action_and_update_ui(action, is_undo=True)
        self.redo_stack.append(action)
        self.update_menu_states()
        logging.info(f"Undone: {action}")


    def redo(self):
        if not self.can_redo():
            return
        action = self.redo_stack.pop()
        self._apply_action_and_update_ui(action, is_undo=False)
        self.undo_stack.append(action)
        self.update_menu_states()
        logging.info(f"Redone: {action}")

    def clear_history(self):
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.update_menu_states()
        logging.info("Undo/Redo history cleared.")

    def update_menu_states(self):
        if hasattr(root, 'editmenu'): # Ensure editmenu exists
            root.editmenu.entryconfig("Undo", state=tk.NORMAL if self.can_undo() else tk.DISABLED)
            root.editmenu.entryconfig("Redo", state=tk.NORMAL if self.can_redo() else tk.DISABLED)

undo_manager = UndoManager()


class Compression(Enum):
    NONE = "None"
    EAHD = "EAHD"

@dataclass
class FileEntry:
    offset: int
    size: int           # Decompressed size
    name: str
    file_type: str
    compression: Compression
    data: bytes         # Decompressed data
    raw_size: int       # Size in BIG file (compressed or uncompressed)

class BinaryReader:
    def __init__(self, data: bytearray):
        self.data = data
        self.pos = 0

    def read_byte(self) -> int:
        if self.pos >= len(self.data):
            raise ValueError("End of stream reached while trying to read a byte.")
        value = self.data[self.pos]
        self.pos += 1
        return value

    def read_int(self, bytes_count: int = 4, big_endian: bool = False) -> int:
        if self.pos + bytes_count > len(self.data):
            raise ValueError(f"Not enough data to read {bytes_count} bytes for an integer.")
        chunk = self.data[self.pos:self.pos + bytes_count]
        self.pos += bytes_count
        return int.from_bytes(chunk, "big" if big_endian else "little")

    def read_string(self, encoding: str) -> str:
        start = self.pos
        while self.pos < len(self.data) and self.data[self.pos] != 0:
            self.pos += 1
        
        result_bytes = self.data[start:self.pos]
        
        if self.pos < len(self.data) and self.data[self.pos] == 0: # If null terminator found
            self.pos += 1  # Skip null terminator
        # Else, if end of data reached without null terminator, self.pos is already at end

        return result_bytes.decode(encoding, errors="ignore")

    def skip(self, count: int):
        if self.pos + count > len(self.data):
            # logging.warning(f"Attempted to skip {count} bytes, but only {len(self.data) - self.pos} bytes remain. Skipping to end.")
            self.pos = len(self.data)
        else:
            self.pos += count

class Decompressor:
    @staticmethod
    def detect_compression(data: bytes) -> Compression:
        return Compression.EAHD if len(data) >= 2 and data[:2] == b"\xfb\x10" else Compression.NONE

    @staticmethod
    def decompress_eahd(data: bytes) -> bytes:
        try:
            reader = BinaryReader(bytearray(data))
            if reader.read_int(2, True) != 0xFB10: # Check EAHD magic
                return data # Not EAHD or malformed, return as is

            total_size = reader.read_int(3, True)
            output = bytearray(total_size)
            pos = 0

            while reader.pos < len(reader.data) and pos < total_size:
                ctrl = reader.read_byte()
                to_read = 0
                to_copy = 0
                offset_val = 0

                if ctrl < 0x80:
                    a = reader.read_byte()
                    to_read = ctrl & 0x03
                    to_copy = ((ctrl & 0x1C) >> 2) + 3
                    offset_val = ((ctrl & 0x60) << 3) + a + 1
                elif ctrl < 0xC0:
                    a, b = reader.read_byte(), reader.read_byte()
                    to_read = (a >> 6) & 0x03
                    to_copy = (ctrl & 0x3F) + 4
                    offset_val = ((a & 0x3F) << 8) + b + 1
                elif ctrl < 0xE0:
                    a, b, c = reader.read_byte(), reader.read_byte(), reader.read_byte()
                    to_read = ctrl & 0x03
                    to_copy = ((ctrl & 0x0C) << 6) + c + 5
                    offset_val = ((ctrl & 0x10) << 12) + (a << 8) + b + 1
                elif ctrl < 0xFC:
                    to_read = ((ctrl & 0x1F) << 2) + 4
                else:
                    to_read = ctrl & 0x03
                
                if pos + to_read > total_size:
                    # logging.warning(f"EAHD: to_read ({to_read}) would exceed total_size ({total_size}) at pos ({pos}). Clamping.")
                    to_read = total_size - pos
                
                for _ in range(to_read):
                    if reader.pos >= len(reader.data): # Check source bounds
                        # logging.error("EAHD: Read attempt beyond source data during literal copy.")
                        return data # Error state
                    output[pos] = reader.read_byte()
                    pos += 1
                
                if to_copy > 0:
                    copy_start = pos - offset_val
                    if copy_start < 0:
                        logging.error("EAHD Decompression: Invalid copy offset (negative).")
                        return data
                    
                    if pos + to_copy > total_size:
                        # logging.warning(f"EAHD: to_copy ({to_copy}) would exceed total_size ({total_size}) at pos ({pos}). Clamping.")
                        to_copy = total_size - pos

                    for _ in range(to_copy):
                        if copy_start >= pos: # Should not happen with valid EAHD if pos advances correctly
                            logging.error("EAHD Decompression: copy_start >= pos, implies data error or logic flaw.")
                            return data
                        if copy_start < 0 or copy_start >= total_size: # Defensive check for output bounds
                            logging.error(f"EAHD: copy_start ({copy_start}) out of bounds for output array (size {total_size}).")
                            return data
                        output[pos] = output[copy_start]
                        pos += 1
                        copy_start += 1
            
            return bytes(output[:pos])
        except ValueError as e:
            logging.error(f"ERROR: EAHD decompression failed (ValueError) - {e}")
            return data
        except Exception as e:
            logging.error(f"ERROR: EAHD decompression failed (General Exception) - {e}", exc_info=True)
            return data

class Compressor:
    @staticmethod
    def compress_eahd(data: bytes) -> bytes:
        logging.warning("EAHD COMPRESSION IS NOT IMPLEMENTED. Returning uncompressed data.")
        return data

class FifaBigFile:
    def __init__(self, filename):
        self.filename = filename
        self.entries: List[FileEntry] = []
        self._load()

    def _load(self):
        try:
            with open(self.filename, 'rb') as f:
                self.data_content = bytearray(f.read())
        except FileNotFoundError:
            logging.error(f"BIG file not found: {self.filename}")
            raise
        
        reader = BinaryReader(self.data_content)
        try:
            magic = bytes(self.data_content[:4])
            if magic not in (b'BIGF', b'BIG4'): # Could add more if needed
                raise ValueError(f"Invalid BIG file magic: {magic.hex()}")
            reader.skip(4)

            _ = reader.read_int(4, False) # total_data_size_in_header (often full file size for BIGF, or size of data part for BIG4)
            num_entries = reader.read_int(4, True) # num_entries is Big Endian
            _ = reader.read_int(4, True) # header_block_size or offset_of_first_file (Big Endian)
        except ValueError as e:
            logging.error(f"Error reading BIG file header: {e}")
            raise

        current_type_tag = "DAT" # Default
        for i in range(num_entries):
            try:
                entry_offset = reader.read_int(4, True)
                entry_raw_size = reader.read_int(4, True)
                entry_name = reader.read_string('utf-8')
            except ValueError as e:
                logging.error(f"Error reading entry definition {i+1}/{num_entries} in BIG file: {e}")
                continue

            if entry_raw_size == 0 and entry_name in {"sg1", "sg2"}:
                current_type_tag = {"sg1": "DDS", "sg2": "APT"}[entry_name]
                self.entries.append(FileEntry(entry_offset, 0, entry_name, current_type_tag, Compression.NONE, b"", 0))
                continue

            actual_raw_size_to_read = entry_raw_size
            if entry_offset + entry_raw_size > len(self.data_content):
                logging.warning(f"Entry '{entry_name}' (offset {entry_offset}, size {entry_raw_size}) extends beyond EOF ({len(self.data_content)}). Clamping read size.")
                actual_raw_size_to_read = len(self.data_content) - entry_offset
                if actual_raw_size_to_read < 0: actual_raw_size_to_read = 0
            
            raw_data = bytes(self.data_content[entry_offset : entry_offset + actual_raw_size_to_read]) if actual_raw_size_to_read > 0 else b""

            compression_type = Decompressor.detect_compression(raw_data)
            decompressed_data = Decompressor.decompress_eahd(raw_data) if compression_type == Compression.EAHD else raw_data
            
            determined_file_type = current_type_tag 
            if decompressed_data[:4] == b'DDS ': # Check magic of decompressed data
                determined_file_type = "DDS"
            # Add more type detections here if necessary (e.g., APT based on its magic)

            self.entries.append(FileEntry(offset=entry_offset, 
                                           size=len(decompressed_data), 
                                           name=entry_name, 
                                           file_type=determined_file_type, 
                                           compression=compression_type, 
                                           data=decompressed_data,
                                           raw_size=entry_raw_size)) # Store original raw_size from header

    def list_files(self) -> List[str]:
        return [entry.name for entry in self.entries if entry.size > 0] # Only list files with actual data

# --- Helper Functions ---
def format_filesize(size_bytes: int) -> str:
    """Converts a size in bytes to a human-readable string (KB or MB)."""
    if size_bytes < 1024:
        return f"{size_bytes} bytes"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.2f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.2f} MB"

def read_internal_name(fp_to_check: str) -> Optional[str]:
    if not fp_to_check or not os.path.exists(fp_to_check):
        return None
    try:
        # Read a limited amount, as internal names are usually found early
        with open(fp_to_check, 'rb') as file:
            content_chunk = file.read(200 * 1024) # Read first 200KB
        
        text_content = content_chunk.decode('utf-8', errors='ignore')
        
        # Common internal name patterns for scoreboards
        # Order might matter if one is a substring of another, but unlikely for these
        names_to_find = ["15002", "2002", "3002", "4002", "5002", "6002", "8002"]
        for name_str in names_to_find:
            if name_str in text_content:
                return name_str
        return None # Not found
    except Exception as e:
        logging.error(f"Failed to read internal name from {fp_to_check}: {e}")
        return None

# --- UI Update and Core Logic Functions ---
def open_file():
    global file_path, current_image_index, composite_mode_active, undo_manager
    global original_loaded_offsets, original_loaded_colors

    fp_temp = filedialog.askopenfilename(
        filetypes=[("FIFA Big Files", "*.big")])
    if fp_temp:
        file_path = fp_temp
        current_image_index = 0 # Reset to first image
        undo_manager.clear_history()
        original_loaded_offsets.clear()
        original_loaded_colors.clear()
        if hasattr(root, 'asterisk_labels'): # Clear asterisks
            for asterisk_label in root.asterisk_labels.values():
                asterisk_label.config(text="")

        file_path_label.config(text=f"File: {os.path.basename(file_path)}")
        add_internal_name() # This will load configs, recreate widgets, and load values

        # Post add_internal_name, check if composite mode needs to be adjusted or texture displayed
        is_internal_name_ok = internal_name_label.cget("text").startswith("Internal Name: ") and \
            not internal_name_label.cget("text").endswith("(No Config)") and \
            not internal_name_label.cget("text").endswith("(Detection Failed)")

        if composite_mode_active:
            is_comp_eligible = (file_path and 0 <= current_image_index < len(image_files) and image_files[current_image_index] == "10")
            if not is_comp_eligible or not is_internal_name_ok:
                toggle_composite_mode() # Will switch to single view
            else:
                display_composite_view() # Refresh composite view
        else:
            if is_internal_name_ok:
                extract_and_display_texture() # Display the (now first) texture
            else:
                # Clear preview if internal name failed
                preview_canvas.delete("all")
                current_image = None
                texture_label.config(text="Load .big / Invalid internal name config")
                image_dimensions_label.config(text="")
    else:
        if not file_path: # If no file was selected and no previous file path exists
            file_path_label.config(text="File: None")


def redraw_single_view_image():
    global current_image, preview_canvas, single_view_zoom_level, single_view_pan_offset_x, single_view_pan_offset_y
    if current_image is None:
        preview_canvas.delete("all")
        return

    canvas_w = preview_canvas.winfo_width()
    canvas_h = preview_canvas.winfo_height()
    if canvas_w <= 1: canvas_w = 580 # Fallback if not drawn
    if canvas_h <= 1: canvas_h = 150

    img_to_display = current_image # This is already the RGBA composited image

    zoomed_w = int(img_to_display.width * single_view_zoom_level)
    zoomed_h = int(img_to_display.height * single_view_zoom_level)

    if zoomed_w <= 0 or zoomed_h <= 0: return # Avoid division by zero or invalid size

    try:
        resized_img_pil = img_to_display.resize((zoomed_w, zoomed_h), Image.LANCZOS)
        img_tk_display = ImageTk.PhotoImage(resized_img_pil)
        
        preview_canvas.delete("all")
        
        # Calculate draw position based on pan and center
        draw_x = canvas_w / 2 + single_view_pan_offset_x
        draw_y = canvas_h / 2 + single_view_pan_offset_y
        
        preview_canvas.create_image(draw_x, draw_y, anchor=tk.CENTER, image=img_tk_display, tags="image_on_canvas")
        preview_canvas.image_ref = img_tk_display # Keep reference
    except Exception as e:
        logging.error(f"Error redrawing single view image: {e}", exc_info=True)

def extract_and_display_texture() -> bool:
    global file_path, current_image, current_image_index, preview_bg_color_is_white, composite_mode_active
    global single_view_zoom_level, single_view_pan_offset_x, single_view_pan_offset_y

    if composite_mode_active: # Do not extract/display individual textures in composite mode
        return False 

    if not file_path:
        preview_canvas.delete("all")
        texture_label.config(text="No file loaded")
        current_image = None
        return False

    try:
        big_file = FifaBigFile(file_path) # This re-parses the BIG file
        
        if not (0 <= current_image_index < len(image_files)):
            logging.warning(f"Invalid current_image_index {current_image_index} for image_files length {len(image_files)}")
            return False
            
        img_name_to_find = image_files[current_image_index]
        
        entry = next((e for e in big_file.entries if e.name == img_name_to_find), None)

        if not entry or entry.size == 0 or not entry.data:
            logging.info(f"Texture '{img_name_to_find}' not found or has no data in {file_path}.")
            preview_canvas.delete("all")
            texture_label.config(text=f"{img_name_to_find}.dds (Not Found/Empty)")
            image_dimensions_label.config(text="")
            current_image = None
            return False

        if entry.file_type != "DDS" or entry.data[:4] != b'DDS ':
            logging.info(f"Entry '{img_name_to_find}' is not a valid DDS file (Type: {entry.file_type}, Magic: {entry.data[:4].hex()}).")
            preview_canvas.delete("all")
            texture_label.config(text=f"{img_name_to_find} (Not a DDS)")
            image_dimensions_label.config(text="")
            current_image = None
            return False

        temp_dds_path = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".dds") as tmp_f:
                tmp_f.write(entry.data)
                temp_dds_path = tmp_f.name

            pil_img_raw = Image.open(temp_dds_path)
            w_orig, h_orig = pil_img_raw.width, pil_img_raw.height

            # Prepare background for alpha compositing
            bg_color_tuple = (255, 255, 255, 255) if preview_bg_color_is_white else (0, 0, 0, 255)
            
            pil_img_rgba = pil_img_raw.convert('RGBA') if pil_img_raw.mode != 'RGBA' else pil_img_raw
            
            background_img = Image.new('RGBA', pil_img_rgba.size, bg_color_tuple)
            current_image = Image.alpha_composite(background_img, pil_img_rgba) # Store composited PIL image

            # Reset zoom and pan for new image in single view
            single_view_zoom_level = 1.0
            single_view_pan_offset_x = 0.0
            single_view_pan_offset_y = 0.0
            
            redraw_single_view_image() # This will handle display

            texture_label.config(text=f"{img_name_to_find}.dds")
            image_dimensions_label.config(text=f"{w_orig}x{h_orig}")
            return True
        except Exception as e_display:
            logging.warning(f"Failed to display DDS texture '{img_name_to_find}': {e_display}", exc_info=True)
            preview_canvas.delete("all")
            texture_label.config(text=f"{img_name_to_find}.dds (Display Error)")
            current_image = None
            return False
        finally:
            if temp_dds_path and os.path.exists(temp_dds_path):
                os.remove(temp_dds_path)
    except Exception as e_outer:
        logging.error(f"Outer error in extract_and_display_texture: {e_outer}", exc_info=True)
        preview_canvas.delete("all")
        texture_label.config(text="Error loading texture")
        current_image = None
        return False

def zoom_image_handler(event):
    if composite_mode_active:
        zoom_composite_view(event)
    else:
        zoom_single_view(event)

def zoom_single_view(event):
    global single_view_zoom_level
    if current_image is None: return

    factor = 1.1 if event.delta > 0 else (1 / 1.1)
    new_zoom = max(0.05, min(single_view_zoom_level * factor, 10.0)) # Zoom limits
    
    # Panning adjustment to zoom towards mouse cursor (simplified for now)
    # More complex math needed for true "zoom towards cursor", current version zooms towards center.
    # For now, we'll keep it simple, zooming relative to the current pan.
    
    single_view_zoom_level = new_zoom
    redraw_single_view_image()

def start_drag_handler(event): # Combined for single and composite
    if composite_mode_active:
        start_drag_composite(event)
    else:
        start_drag_single(event)

def on_drag_handler(event): # Combined
    if composite_mode_active:
        on_drag_composite(event)
    else:
        on_drag_single(event)

def on_drag_release_handler(event): # Combined
    global drag_data, composite_mode_active
    drag_data["is_panning"] = False # For single view left-click pan
    drag_data["is_panning_rmb"] = False # For composite view right-click pan
    if composite_mode_active:
        # This is also where drag_data for composite element drag would be reset if needed.
        # For now, composite_drag_data.item is implicitly reset on next start_drag_composite.
        clear_all_highlights() # Clear highlights on mouse release in composite


def start_drag_single(event):
    global drag_data
    # For single view, left-click drag is for panning the image
    drag_data["is_panning"] = True
    drag_data["x"] = event.x
    drag_data["y"] = event.y

def on_drag_single(event):
    global drag_data, single_view_pan_offset_x, single_view_pan_offset_y
    if not drag_data["is_panning"] or current_image is None:
        return
    
    dx = event.x - drag_data["x"]
    dy = event.y - drag_data["y"]
    
    single_view_pan_offset_x += dx
    single_view_pan_offset_y += dy
    
    drag_data["x"] = event.x
    drag_data["y"] = event.y
    redraw_single_view_image()

def load_current_values():
    global file_path, original_loaded_offsets, original_loaded_colors
    if not file_path or not hasattr(root, 'offsets_vars') or not hasattr(root, 'color_vars'):
        return

    original_loaded_offsets.clear()
    original_loaded_colors.clear()
    
    try:
        with open(file_path, 'rb') as file:
            # Load offsets
            for off_tuple_key, var_obj in root.offsets_vars.items():
                if not off_tuple_key: continue # Should not happen
                try:
                    # Assuming the first address in the list is the primary one for reading
                    file.seek(off_tuple_key[0]) 
                    data_bytes = file.read(4) # Read 4 bytes for a float
                    value_float = struct.unpack('<f', data_bytes)[0]
                    val_str_formatted = f"{value_float:.2f}" # Format for display and storage
                    var_obj.set(val_str_formatted)
                    original_loaded_offsets[off_tuple_key] = val_str_formatted
                    if off_tuple_key in root.asterisk_labels:
                        root.asterisk_labels[off_tuple_key].config(text="")
                except struct.error:
                    logging.warning(f"Struct error for offset {off_tuple_key[0]}. Data: {data_bytes.hex() if 'data_bytes' in locals() else 'N/A'}")
                    var_obj.set("ERR")
                except Exception as e_off:
                    logging.error(f"Error reading offset {off_tuple_key}: {e_off}")
                    var_obj.set("ERR")
            
            # Load colors
            for off_tuple_key, var_obj in root.color_vars.items():
                if not off_tuple_key: continue
                try:
                    file.seek(off_tuple_key[0])
                    data_bytes = file.read(4) # Expect BGRA
                    hex_color_code = f'#{data_bytes[2]:02X}{data_bytes[1]:02X}{data_bytes[0]:02X}' # BGR to #RRGGBB
                    var_obj.set(hex_color_code)
                    original_loaded_colors[off_tuple_key] = hex_color_code
                    if off_tuple_key in root.color_previews: # Update preview swatch
                        root.color_previews[off_tuple_key].config(bg=hex_color_code)
                    if off_tuple_key in root.asterisk_labels:
                        root.asterisk_labels[off_tuple_key].config(text="")
                except struct.error:
                    logging.warning(f"Struct error for color {off_tuple_key[0]}. Data: {data_bytes.hex() if 'data_bytes' in locals() else 'N/A'}")
                    var_obj.set("#ERR")
                except Exception as e_col:
                    logging.error(f"Error reading color offset {off_tuple_key}: {e_col}")
                    var_obj.set("#ERR")
    except FileNotFoundError:
        messagebox.showerror("Error", f"File not found: {file_path}")
    except Exception as e_load_all:
        messagebox.showerror("Error", f"Failed to read values from file: {e_load_all}")

def add_internal_name():
    global file_path, previous_file_path, offsets, colors, current_reference_width, current_reference_height, composite_mode_active
    
    if not file_path:
        internal_name_label.config(text="Internal Name: Not Loaded")
        clear_editor_widgets()
        current_reference_width = None
        current_reference_height = None
        if composite_mode_active: toggle_composite_mode() # Exit composite if no file
        return

    internal_name_str = read_internal_name(file_path)
    if internal_name_str:
        internal_name_label.config(text=f"Internal Name: {internal_name_str}")
        
        if internal_name_str in offsets_data:
            config_for_name = offsets_data[internal_name_str]
            current_reference_width = config_for_name.get("reference_width")
            current_reference_height = config_for_name.get("reference_height")
            
            # Convert hex string offsets from JSON to integer lists
            offsets_from_json = config_for_name.get("offsets", {})
            offsets = {
                label: [int(str(addr), 16) for addr in (addr_list if isinstance(addr_list, list) else [addr_list])]
                for label, addr_list in offsets_from_json.items()
            }
            
            colors_from_json = config_for_name.get("colors", {})
            colors = {
                label: [int(str(addr), 16) for addr in (addr_list if isinstance(addr_list, list) else [addr_list])]
                for label, addr_list in colors_from_json.items()
            }
            
            recreate_widgets() # This will define root.offsets_vars, root.color_vars etc.
            load_current_values() # Populate them from the file
            
            previous_file_path = file_path # Store this as the last successfully loaded file
        else:
            messagebox.showerror("Config Error", f"Configuration for internal name '{internal_name_str}' not found in offsets.json.")
            internal_name_label.config(text=f"Internal Name: {internal_name_str} (No Config)")
            clear_editor_widgets()
            current_reference_width = None
            current_reference_height = None
            if composite_mode_active: toggle_composite_mode()
    else:
        messagebox.showerror("Detection Error", "No internal name detected. Please check the file or offsets.json.")
        current_reference_width = None
        current_reference_height = None
        if previous_file_path and previous_file_path != file_path: # If detection failed on a NEW file, try to revert
            file_path = previous_file_path # Revert global file_path
            add_internal_name() # Attempt to reload the previous good state
            update_status(f"Reverted to: {os.path.basename(file_path)} due to detection failure.", "orange")
        else: # No previous file or detection failed on the same file again
            internal_name_label.config(text="Internal Name: Detection Failed")
            clear_editor_widgets()
            preview_canvas.delete("all"); current_image = None
            texture_label.config(text=""); image_dimensions_label.config(text="")
            if composite_mode_active: toggle_composite_mode()

def clear_editor_widgets():
    for frame in [positions_frame, sizes_frame, colors_frame]:
        for widget in frame.winfo_children():
            widget.destroy()
    # Clear root-level stores for these widgets
    for attr_name in ['offsets_vars', 'color_vars', 'color_previews', 'offset_entry_widgets', 'asterisk_labels']:
        if hasattr(root, attr_name):
            getattr(root, attr_name).clear()

def recreate_widgets():
    clear_editor_widgets()
    global offsets, colors # These are populated by add_internal_name from JSON

    # Initialize dictionaries on root for widget variables and references
    root.offsets_vars = {tuple(val_list): tk.StringVar() for val_list in offsets.values()}
    root.color_vars = {tuple(val_list): tk.StringVar(value='#000000') for val_list in colors.values()}
    root.color_previews = {} # Stores {offset_tuple_key: preview_label_widget}
    root.offset_entry_widgets = {} # Stores {offset_tuple_key: entry_widget}
    root.asterisk_labels = {} # Stores {offset_tuple_key: asterisk_label_widget}

    # --- Lambda factory for offset updates (handles undo/redo) ---
    def make_offset_update_lambda(key_tuple, var, entry_widget):
        def on_offset_update(event=None): # event=None for programmatic calls
            current_value_in_var = var.get()
            # original_loaded_offsets contains the value as loaded from file or last save
            original_value_str = original_loaded_offsets.get(key_tuple, "") 

            # Check if this update is due to FocusOut immediately after a KeyRelease that already recorded undo
            is_redundant_focus_out = (event and event.type == tk.EventType.FocusOut and
                                     hasattr(entry_widget, '_undo_recorded_for_this_change') and
                                     entry_widget._undo_recorded_for_this_change)

            if not is_redundant_focus_out:
                # Try to compare floats for actual change, but store strings for undo if parse fails
                try:
                    # Compare with tolerance for float precision
                    if abs(float(current_value_in_var) - float(original_value_str)) > 1e-5 :
                        # Only record if there's a meaningful change from the original
                        action = EditAction(var, original_value_str, current_value_in_var, key_tuple, entry_widget, f"Offset change for {key_tuple}")
                        undo_manager.record_action(action)
                except ValueError: # If conversion fails, compare as strings (e.g. "ERR" vs new value)
                    if current_value_in_var != original_value_str:
                        action = EditAction(var, original_value_str, current_value_in_var, key_tuple, entry_widget, f"Offset change (non-float) for {key_tuple}")
                        undo_manager.record_action(action)
            
            if event and event.type == tk.EventType.KeyRelease:
                entry_widget._undo_recorded_for_this_change = True # Mark that KeyRelease handled this
            
            update_value(key_tuple, var) # This updates asterisk and status

            if event and event.type == tk.EventType.FocusOut: # Reset flag on FocusOut
                if hasattr(entry_widget, '_undo_recorded_for_this_change'):
                    delattr(entry_widget, '_undo_recorded_for_this_change')
        return on_offset_update

    # --- Lambda factory for increment/decrement (handles undo/redo) ---
    def make_increment_lambda(key_tuple, var, entry_widget, direction_str):
        def on_increment(event=None):
            old_value_str = var.get()
            entry_widget.unbind("<KeyRelease>") # Temporarily unbind to prevent double recording

            increment_value(event, var, direction_str) # Modifies var in-place
            new_value_str = var.get()

            if old_value_str != new_value_str:
                action = EditAction(var, old_value_str, new_value_str, key_tuple, entry_widget, f"Increment {direction_str}")
                undo_manager.record_action(action)
            
            update_value(key_tuple, var) # Update asterisk and status

            # Rebind KeyRelease with the standard update lambda
            entry_widget.bind("<KeyRelease>", make_offset_update_lambda(key_tuple, var, entry_widget))
        return on_increment

    # --- Create Position Widgets ---
    row_p = 0
    for label_text, offset_val_list in offsets.items():
        if "Size" not in label_text and not label_text.startswith("Image_"): # Filter for positions
            key_tuple = tuple(offset_val_list)
            
            # Determine column based on X/Y or Width/Height in label
            col = 0 if "X" in label_text or "Width" in label_text else 4 # 0 for left, 4 for right column
            
            tk.Label(positions_frame, text=label_text).grid(row=row_p, column=col, padx=5, pady=5, sticky="w")
            
            entry = tk.Entry(positions_frame, textvariable=root.offsets_vars[key_tuple], width=10)
            entry.grid(row=row_p, column=col + 1, padx=0, pady=5)
            root.offset_entry_widgets[key_tuple] = entry
            
            update_lambda = make_offset_update_lambda(key_tuple, root.offsets_vars[key_tuple], entry)
            entry.bind("<KeyRelease>", update_lambda)
            entry.bind("<FocusOut>", update_lambda) # Capture changes on losing focus
            entry.bind('<KeyPress-Up>', make_increment_lambda(key_tuple, root.offsets_vars[key_tuple], entry, "Up"))
            entry.bind('<KeyPress-Down>', make_increment_lambda(key_tuple, root.offsets_vars[key_tuple], entry, "Down"))

            asterisk_lbl = tk.Label(positions_frame, text="", fg="red", width=1)
            asterisk_lbl.grid(row=row_p, column=col + 2, padx=(0,5), pady=5, sticky="w")
            root.asterisk_labels[key_tuple] = asterisk_lbl

            if col == 4 or "Y" in label_text or "Height" in label_text : # If it's a Y/Height or in the right column, advance row
                 row_p += 1
    
    # --- Create Size Widgets ---
    row_s = 0
    for label_text, offset_val_list in offsets.items():
        if "Size" in label_text: # Filter for sizes
            key_tuple = tuple(offset_val_list)
            tk.Label(sizes_frame, text=label_text).grid(row=row_s, column=0, padx=5, pady=5, sticky="w")
            
            entry = tk.Entry(sizes_frame, textvariable=root.offsets_vars[key_tuple], width=10)
            entry.grid(row=row_s, column=1, padx=0, pady=5)
            root.offset_entry_widgets[key_tuple] = entry

            update_lambda_size = make_offset_update_lambda(key_tuple, root.offsets_vars[key_tuple], entry)
            entry.bind("<KeyRelease>", update_lambda_size)
            entry.bind("<FocusOut>", update_lambda_size)
            entry.bind('<KeyPress-Up>', make_increment_lambda(key_tuple, root.offsets_vars[key_tuple], entry, "Up"))
            entry.bind('<KeyPress-Down>', make_increment_lambda(key_tuple, root.offsets_vars[key_tuple], entry, "Down"))

            asterisk_lbl_size = tk.Label(sizes_frame, text="", fg="red", width=1)
            asterisk_lbl_size.grid(row=row_s, column=2, padx=(0,5), pady=5, sticky="w")
            root.asterisk_labels[key_tuple] = asterisk_lbl_size
            row_s += 1

    # --- Create Color Widgets ---
    row_c = 0
    # Lambda factory for color updates (handles undo/redo)
    def make_color_update_lambda(k_tuple, var_obj, entry_w_ref):
        def on_color_update(event=None):
            current_hex = var_obj.get()
            original_hex = original_loaded_colors.get(k_tuple, "")

            is_redundant_focus_out_color = (event and event.type == tk.EventType.FocusOut and
                                           hasattr(entry_w_ref, '_undo_recorded_for_this_color_change') and
                                           entry_w_ref._undo_recorded_for_this_color_change)

            if not is_redundant_focus_out_color and current_hex != original_hex:
                 action = EditAction(var_obj, original_hex, current_hex, k_tuple, entry_w_ref, f"Color change for {k_tuple}")
                 undo_manager.record_action(action)
            
            if event and event.type == tk.EventType.KeyRelease:
                entry_w_ref._undo_recorded_for_this_color_change = True
            
            update_color_preview_from_entry(k_tuple, var_obj) # Updates preview, asterisk, status

            if event and event.type == tk.EventType.FocusOut:
                if hasattr(entry_w_ref, '_undo_recorded_for_this_color_change'):
                    delattr(entry_w_ref, '_undo_recorded_for_this_color_change')
        return on_color_update

    for label_text, offset_val_list in colors.items():
        key_tuple = tuple(offset_val_list)
        tk.Label(colors_frame, text=label_text).grid(row=row_c, column=0, padx=5, pady=5, sticky="w")
        
        entry = tk.Entry(colors_frame, textvariable=root.color_vars[key_tuple], width=10)
        entry.grid(row=row_c, column=1, padx=0, pady=5)
        # root.offset_entry_widgets[key_tuple] = entry # Colors don't go here, they are not "offset_entry_widgets"
        
        color_update_lambda = make_color_update_lambda(key_tuple, root.color_vars[key_tuple], entry)
        entry.bind('<KeyPress>', lambda e, var=root.color_vars[key_tuple]: restrict_color_entry(e, var))
        entry.bind('<KeyRelease>', color_update_lambda)
        entry.bind("<FocusOut>", color_update_lambda)
        
        preview_label = tk.Label(colors_frame, bg=root.color_vars[key_tuple].get(), width=3, height=1, relief="sunken")
        preview_label.grid(row=row_c, column=2, padx=5, pady=5)
        root.color_previews[key_tuple] = preview_label

        # Lambda for color chooser that handles undo
        def make_choose_color_lambda(k_t, var_obj, preview_w, entry_r):
            def on_choose_color(event=None):
                old_color_hex = var_obj.get()
                choose_color(k_t, var_obj, preview_w) # choose_color will set var_obj
                new_color_hex = var_obj.get()
                if old_color_hex != new_color_hex:
                    action = EditAction(var_obj, old_color_hex, new_color_hex, k_t, entry_r, f"Choose color for {k_t}")
                    undo_manager.record_action(action)
                # update_color_preview_from_entry already called by choose_color if value changed
            return on_choose_color

        preview_label.bind("<Button-1>", make_choose_color_lambda(key_tuple, root.color_vars[key_tuple], preview_label, entry))
        
        asterisk_lbl_color = tk.Label(colors_frame, text="", fg="red", width=1)
        asterisk_lbl_color.grid(row=row_c, column=3, padx=(0,5), pady=5, sticky="w")
        root.asterisk_labels[key_tuple] = asterisk_lbl_color
        row_c += 1

def save_file():
    global file_path, original_loaded_offsets, original_loaded_colors
    if not file_path:
        messagebox.showerror("Error", "No file loaded to save.")
        return
    if not hasattr(root, 'offsets_vars') or not hasattr(root, 'color_vars'):
        messagebox.showerror("Error", "Editor data not initialized. Cannot save.")
        return

    try:
        with open(file_path, 'r+b') as file: # Read-write binary mode
            # Save offsets
            for off_tuple_key, var_obj in root.offsets_vars.items():
                value_str = var_obj.get()
                try:
                    value_float = float(value_str)
                    packed_float = struct.pack('<f', value_float) # Little-endian float
                    for single_addr in off_tuple_key: # Write to all addresses in the list
                        file.seek(single_addr)
                        file.write(packed_float)
                    original_loaded_offsets[off_tuple_key] = value_str # Update baseline
                    if off_tuple_key in root.asterisk_labels:
                        root.asterisk_labels[off_tuple_key].config(text="")
                except ValueError:
                    messagebox.showerror("Save Error", f"Invalid float value '{value_str}' for offset key {off_tuple_key}. Save aborted.")
                    return
                except Exception as e_write_off:
                    messagebox.showerror("Save Error", f"Failed writing offset {off_tuple_key} (addr: {single_addr}): {e_write_off}")
                    return
            
            # Save colors
            for off_tuple_key, var_obj in root.color_vars.items():
                hex_color_str = var_obj.get()
                if not (len(hex_color_str) == 7 and hex_color_str.startswith('#')):
                    messagebox.showerror("Save Error", f"Invalid color format '{hex_color_str}' for key {off_tuple_key}. Expected #RRGGBB. Save aborted.")
                    return
                try:
                    r = int(hex_color_str[1:3], 16)
                    g = int(hex_color_str[3:5], 16)
                    b = int(hex_color_str[5:7], 16)
                    # BGRA format for game files (Alpha often 0xFF or ignored but set)
                    color_bytes_bgra = bytes([b, g, r, 0xFF]) 
                    for single_addr in off_tuple_key:
                        file.seek(single_addr)
                        file.write(color_bytes_bgra)
                    original_loaded_colors[off_tuple_key] = hex_color_str # Update baseline
                    if off_tuple_key in root.asterisk_labels:
                        root.asterisk_labels[off_tuple_key].config(text="")
                except ValueError:
                    messagebox.showerror("Save Error", f"Invalid hex value in color '{hex_color_str}' for key {off_tuple_key}. Save aborted.")
                    return
                except Exception as e_write_col:
                    messagebox.showerror("Save Error", f"Failed writing color {off_tuple_key} (addr: {single_addr}): {e_write_col}")
                    return

        update_status("File saved successfully.", "green")
        undo_manager.clear_history() # Clear undo history after successful save
    except FileNotFoundError:
        messagebox.showerror("Save Error", f"File not found: {file_path}")
    except Exception as e_file_open:
        messagebox.showerror("Save Error", f"Failed to open or save file: {e_file_open}")

def update_value(offset_key_tuple, string_var, from_undo_redo=False):
    global composite_mode_active, composite_elements, offsets, initial_text_elements_config, predefined_image_coords
    global original_loaded_offsets
    
    val_str_from_var = string_var.get()
    if not from_undo_redo: # Avoid logging spam from undo/redo itself
        logging.debug(f"update_value called for {offset_key_tuple} with '{val_str_from_var}'")

    new_game_offset_val_float = None
    try:
        new_game_offset_val_float = float(val_str_from_var)
    except ValueError:
        if not from_undo_redo: # Only show status if it's a direct user error
            update_status(f"Invalid float value '{val_str_from_var}' entered.", "red")
        if offset_key_tuple in root.asterisk_labels:
            root.asterisk_labels[offset_key_tuple].config(text="!") # Indicate error
        return # Cannot proceed if value is not a valid float

    # Update asterisk based on comparison with original loaded value
    if offset_key_tuple in root.asterisk_labels:
        original_val_str = original_loaded_offsets.get(offset_key_tuple)
        is_changed_from_original = True # Assume changed unless proven otherwise
        if original_val_str is not None:
            try:
                if abs(float(original_val_str) - new_game_offset_val_float) < 0.0001: # Tolerance for float comparison
                    is_changed_from_original = False
            except ValueError: # If original was "ERR" or similar
                pass # Keep is_changed_from_original as True
        root.asterisk_labels[offset_key_tuple].config(text="*" if is_changed_from_original else "")
    
    if not from_undo_redo:
        update_status(f"Game offset for {offset_key_tuple} set to {new_game_offset_val_float:.2f}", "blue")

    # If in composite mode, check if this offset is linked to any visual element
    if composite_mode_active:
        visual_element_updated = None
        for el_data in composite_elements:
            is_x_linked = False
            is_y_linked = False
            
            x_label_key = el_data.get('x_offset_label_linked')
            if x_label_key and x_label_key in offsets and tuple(offsets[x_label_key]) == offset_key_tuple:
                is_x_linked = True
            
            y_label_key = el_data.get('y_offset_label_linked')
            if y_label_key and y_label_key in offsets and tuple(offsets[y_label_key]) == offset_key_tuple:
                is_y_linked = True

            if is_x_linked or is_y_linked:
                gui_ref_x_val = el_data.get('gui_ref_x')
                gui_ref_y_val = el_data.get('gui_ref_y')
                base_game_x_val = el_data.get('base_game_x')
                base_game_y_val = el_data.get('base_game_y')

                if gui_ref_x_val is not None and gui_ref_y_val is not None: # Ensure base GUI refs exist
                    if is_x_linked and base_game_x_val is not None:
                        # New visual original_x = GUI_Ref_X + (CurrentGameOffset_X - BaseGameOffset_X)
                        el_data['original_x'] = float(gui_ref_x_val) + (new_game_offset_val_float - base_game_x_val)
                        visual_element_updated = el_data
                    if is_y_linked and base_game_y_val is not None:
                        el_data['original_y'] = float(gui_ref_y_val) + (new_game_offset_val_float - base_game_y_val)
                        visual_element_updated = el_data
                
                if visual_element_updated:
                    logging.info(f"Composite: Visual for '{el_data.get('display_tag')}' updated via Entry to (X:{el_data['original_x']:.1f}, Y:{el_data['original_y']:.1f})")
                    # If this element is a leader of a conjoined group, update followers
                    leader_tag_name = visual_element_updated.get('display_tag')
                    if leader_tag_name:
                        for follower_el in composite_elements:
                            if follower_el.get('conjoined_to_tag') == leader_tag_name:
                                follower_el['original_x'] = visual_element_updated['original_x'] + follower_el.get('relative_offset_x', 0)
                                follower_el['original_y'] = visual_element_updated['original_y'] + follower_el.get('relative_offset_y', 0)
                    break # Assume one entry updates one (primary) element's coordinate
        
        if visual_element_updated:
            redraw_composite_view()

def increment_value(event, str_var, direction_str): # event is KeyPress, str_var is the tk.StringVar
    try:
        current_val_str = str_var.get()
        if not current_val_str or current_val_str == "ERR":
            current_val_str = "0.0" # Default to 0 if current is invalid
        
        value_float = float(current_val_str)
        
        # Determine increment amount based on modifier keys
        increment_amt = 1.0 # Default
        if event.state & 0x0001: # Shift key
            increment_amt = 0.1
        if event.state & 0x0004: # Control key
            increment_amt = 0.01
            if event.state & 0x0001: # Shift + Control
                 increment_amt = 0.001


        if direction_str == 'Up':
            value_float += increment_amt
        elif direction_str == 'Down':
            value_float -= increment_amt
        
        str_var.set(f"{value_float:.4f}") # Set with precision, update_value will handle the rest
    except ValueError:
        update_status("Invalid value for increment.", "red")
        # str_var is not changed if current value was not float-convertible

def update_color_preview_from_entry(off_key_tuple, str_var, from_undo_redo=False):
    global original_loaded_colors
    hex_color_str = str_var.get()
    is_valid_hex = False

    if len(hex_color_str) == 7 and hex_color_str.startswith('#'):
        try:
            int(hex_color_str[1:], 16) # Validate actual hex
            is_valid_hex = True
            if hasattr(root, 'color_previews') and off_key_tuple in root.color_previews:
                root.color_previews[off_key_tuple].config(bg=hex_color_str)
            if not from_undo_redo:
                update_status("Color preview updated.", "blue")
            if composite_mode_active: # If in composite, redraw might be needed if text uses this color
                redraw_composite_view()
        except ValueError: # Invalid hex characters after #
            if not from_undo_redo:
                update_status("Invalid hex color code.", "red")
    elif not from_undo_redo and len(hex_color_str) > 0 and not hex_color_str.startswith('#') and \
         all(c in "0123456789abcdefABCDEF" for c in hex_color_str) and len(hex_color_str) <= 6:
        # If user types hex without '#', prepend it and recall
        str_var.set("#" + hex_color_str.upper()) # Standardize to uppercase hex
        update_color_preview_from_entry(off_key_tuple, str_var, from_undo_redo) # Recursive call
        return # Avoid double status/asterisk update

    # Update asterisk
    if off_key_tuple in root.asterisk_labels:
        original_color_str = original_loaded_colors.get(off_key_tuple)
        is_changed = True # Assume changed
        if is_valid_hex:
            is_changed = (original_color_str.lower() != hex_color_str.lower()) if original_color_str else True
        root.asterisk_labels[off_key_tuple].config(text="*" if is_changed else "")


def choose_color(off_key_tuple, str_var, preview_widget_ref): # str_var is tk.StringVar
    old_color_hex = str_var.get()
    # Ensure current_color_for_dialog is a valid hex for colorchooser
    current_color_for_dialog = old_color_hex
    if not (current_color_for_dialog.startswith("#") and len(current_color_for_dialog) == 7):
        current_color_for_dialog = "#000000" # Default if current is invalid
    
    new_color_tuple_result = colorchooser.askcolor(initialcolor=current_color_for_dialog, title="Choose Color")
    
    if new_color_tuple_result and new_color_tuple_result[1]: # If a color was chosen ([1] is the hex string)
        chosen_hex_color = new_color_tuple_result[1].lower() # Standardize to lowercase
        
        if old_color_hex.lower() != chosen_hex_color: # Record undo only if color actually changed
            # Find the entry widget associated with this color for the undo action
            # This is a bit indirect; color vars are not directly tied to specific entry widgets in root.offset_entry_widgets
            # For colors, the entry widget reference might be less critical for undo/redo focus,
            # but good to have if we can find it.
            # For now, pass None as entry_widget_ref for color chooser actions.
            # Or, we'd need to iterate through color_frame's children to find the entry.
            # Simpler: the lambda creating this call in recreate_widgets has entry_ref.
            # The action needs entry_ref, but this function doesn't have it directly.
            # The calling lambda (make_choose_color_lambda) *does* have it and should handle undo recording.
            # This function will just set the variable. The caller records the action.
            pass # Undo is handled by the lambda that calls choose_color

        str_var.set(chosen_hex_color)
        # preview_widget_ref.config(bg=chosen_hex_color) # This is now handled by update_color_preview_from_entry
        update_color_preview_from_entry(off_key_tuple, str_var) # This updates preview, asterisk, status

def update_status(message_text, fg_color_str):
    status_label.config(text=message_text, fg=fg_color_str)

def about():
    win_about = tk.Toplevel(root)
    win_about.title("About FLP Scoreboard Editor 25")
    win_about.geometry("450x300") # Adjusted size
    win_about.resizable(False, False)
    win_about.transient(root) # Keep on top of root
    win_about.grab_set()      # Modal behavior

    tk.Label(win_about, text="FLP Scoreboard Editor 25", pady=10, font=("Helvetica", 12, "bold")).pack()
    tk.Label(win_about, text="Version 1.13 [Build 10 May 2025]", pady=5).pack() # Placeholder version
    tk.Label(win_about, text="© 2025 FIFA Legacy Project. All Rights Reserved.", pady=5).pack()
    tk.Label(win_about, text="Designed & Developed By: Emran_Ahm3d", pady=5).pack()
    tk.Label(win_about, text="Special Thanks: Riesscar, KO, MCK, Marconis (Research)", pady=5, wraplength=400).pack()
    tk.Label(win_about, text="Discord: @emran_ahm3d", pady=5).pack()
    
    ok_button = ttk.Button(win_about, text="OK", command=win_about.destroy, width=10)
    ok_button.pack(pady=10)
    win_about.wait_window()


def show_documentation():
    webbrowser.open("https://soccergaming.com/") # Placeholder URL

def restrict_color_entry(event, str_var): # event is KeyPress
    # Allow navigation, deletion, selection
    allowed_keysyms = ['Left', 'Right', 'BackSpace', 'Delete', 'Tab', 'Home', 'End', 'Shift_L', 'Shift_R', 'Control_L', 'Control_R']
    if event.keysym in allowed_keysyms:
        return # Allow the key press

    # Allow copy/paste (Ctrl+C, Ctrl+V, Ctrl+X)
    if event.state & 0x4 and event.keysym.lower() in ('c', 'v', 'x'): # Check for Control modifier
        return

    current_text = str_var.get()
    char_typed = event.char

    if not char_typed or not char_typed.isprintable(): # Ignore non-printable characters
        return

    # Handle '#' prefix automatically
    if not current_text and char_typed != '#':
        str_var.set('#' + char_typed.upper())
        # Need to move cursor after the typed char
        event.widget.after_idle(lambda: event.widget.icursor(tk.END))
        return 'break' # Prevent default insertion of char_typed alone
    if current_text == '#' and char_typed == '#': # Prevent '##'
        return 'break'

    # Limit length (including '#')
    # Check if text is selected - if so, allow typing to replace selection
    has_selection = False
    try:
        if event.widget.selection_present():
            has_selection = True
    except tk.TclError:
        pass # Widget might not support selection_present or is in a weird state

    if len(current_text) >= 7 and not has_selection:
        return 'break'

    # Allow only valid hex characters after '#'
    if current_text.startswith('#'):
        if not char_typed.lower() in '0123456789abcdef':
            return 'break'
    
    # Standardize to uppercase after typing
    # This is tricky with KeyPress; KeyRelease is better for formatting, but update_color_preview handles it.

def exit_app():
    # Could add a check for unsaved changes here
    if messagebox.askyesno("Exit Application", "Are you sure you want to exit?"):
        root.destroy()

def import_texture():
    global file_path, current_image_index, image_files

    if not file_path:
        messagebox.showerror("Error", "No .big file loaded.")
        return

    if composite_mode_active:
        messagebox.showinfo("Info", "Import/Export is disabled in Composite View mode.")
        return

    try:
        big_file_obj = FifaBigFile(file_path)
    except Exception as e:
        messagebox.showerror("Error", f"Failed to read BIG file for import: {e}")
        logging.error(f"Failed to read BIG file for import: {e}", exc_info=True)
        return

    if not image_files or not (0 <= current_image_index < len(image_files)):
        messagebox.showerror("Error", "No valid texture selected for import.")
        return
    
    file_name_to_replace = image_files[current_image_index]
    
    original_entry_obj = next((entry for entry in big_file_obj.entries if entry.name == file_name_to_replace), None)
    
    if original_entry_obj is None:
        messagebox.showerror("Error", f"File '{file_name_to_replace}' not found in the BIG archive structure.")
        return
    
    new_texture_path = filedialog.askopenfilename(
        title=f"Import texture for {file_name_to_replace}.dds",
        filetypes=[("DDS Files", "*.dds"), ("PNG Files", "*.png")]
    )
    if not new_texture_path:
        return

    new_data_uncompressed = None
    temp_dds_for_import_path = None

    try:
        if new_texture_path.lower().endswith(".png"):
            try:
                with Image.open(new_texture_path) as pil_img:
                    pil_img_rgba = pil_img.convert("RGBA") 
                with tempfile.NamedTemporaryFile(delete=False, suffix=".dds") as temp_dds_f:
                    temp_dds_for_import_path = temp_dds_f.name
                    pil_img_rgba.save(temp_dds_for_import_path, "DDS")
                with open(temp_dds_for_import_path, 'rb') as f_dds_read:
                    new_data_uncompressed = f_dds_read.read()
                logging.info(f"Converted {new_texture_path} to temporary DDS for import.")
            except Exception as e_png_conv:
                messagebox.showerror("PNG Conversion Error", f"Failed to convert PNG to DDS: {e_png_conv}")
                logging.error(f"PNG to DDS conversion error: {e_png_conv}", exc_info=True)
                return
        elif new_texture_path.lower().endswith(".dds"):
            with open(new_texture_path, 'rb') as new_f:
                new_data_uncompressed = new_f.read()
            logging.info(f"Read DDS file {new_texture_path} for import.")
        else:
            messagebox.showerror("Error", "Unsupported file type. Please select a DDS or PNG file.")
            return

        if not new_data_uncompressed:
            messagebox.showerror("Error", "Failed to read new texture data.")
            return

        data_to_write_in_big = new_data_uncompressed
        compression_applied_msg = ""

        if original_entry_obj.compression == Compression.EAHD:
            logging.info(f"Original texture '{file_name_to_replace}' was EAHD. Attempting to compress new texture.")
            data_to_write_in_big = Compressor.compress_eahd(new_data_uncompressed)
            if data_to_write_in_big is new_data_uncompressed:
                 compression_applied_msg = "(EAHD compression placeholder used; data written uncompressed)"
            else:
                 compression_applied_msg = "(EAHD compression attempted)"
            logging.info(f"Compression status: {compression_applied_msg}")

        if original_entry_obj.raw_size > 0 and len(data_to_write_in_big) > original_entry_obj.raw_size:
            msg = (f"New file data ({format_filesize(len(data_to_write_in_big))}) is larger than the "
                   f"original allocated space ({format_filesize(original_entry_obj.raw_size)}) "
                   f"for '{file_name_to_replace}'. Import aborted. {compression_applied_msg}")
            messagebox.showerror("Size Error", msg)
            logging.warning(msg)
            return
        
        with open(file_path, 'r+b') as f_big_write:
            f_big_write.seek(original_entry_obj.offset)
            f_big_write.write(data_to_write_in_big)
            if original_entry_obj.raw_size > 0 and len(data_to_write_in_big) < original_entry_obj.raw_size:
                padding_size = original_entry_obj.raw_size - len(data_to_write_in_big)
                f_big_write.write(b'\x00' * padding_size)
                logging.info(f"Padded imported texture with {padding_size} null bytes.")
        
        success_msg = (f"Successfully imported '{os.path.basename(new_texture_path)}' as '{file_name_to_replace}.dds'.\n"
                       f"Original raw slot: {format_filesize(original_entry_obj.raw_size)}, "
                       f"New data written: {format_filesize(len(data_to_write_in_big))}. {compression_applied_msg}")
        messagebox.showinfo("Import Successful", success_msg)
        logging.info(success_msg)

        if not extract_and_display_texture():
            messagebox.showwarning("Preview Warning", "Could not refresh preview after import. The file was modified, but the display might be stale.")
        else:
            update_status(f"Texture {file_name_to_replace}.dds imported and preview updated.", "green")

    except Exception as e_import:
        messagebox.showerror("Import Error", f"An unexpected error occurred during import: {e_import}")
        logging.error(f"General import texture error: {e_import}", exc_info=True)
    finally:
        if temp_dds_for_import_path and os.path.exists(temp_dds_for_import_path):
            try:
                os.remove(temp_dds_for_import_path)
            except Exception as e_clean:
                logging.warning(f"Could not remove temp import file {temp_dds_for_import_path}: {e_clean}")


def export_selected_file():
    global file_path, current_image_index, image_files

    if not file_path:
        messagebox.showerror("Error", "No .big file loaded.")
        return
    
    if composite_mode_active:
        messagebox.showinfo("Info", "Import/Export is disabled in Composite View mode.")
        return

    if not image_files or not (0 <= current_image_index < len(image_files)):
        messagebox.showerror("Error", "No texture selected for export.")
        return

    file_name_to_export = image_files[current_image_index]
    
    try:
        big_file_obj = FifaBigFile(file_path)
    except Exception as e:
        messagebox.showerror("Error", f"Could not read BIG file for export: {e}")
        logging.error(f"Could not read BIG file for export: {e}", exc_info=True)
        return

    entry_obj_to_export = next((e for e in big_file_obj.entries if e.name == file_name_to_export), None)
    
    if not entry_obj_to_export or entry_obj_to_export.size == 0 or not entry_obj_to_export.data:
        messagebox.showerror("Error", f"File '{file_name_to_export}' not found in archive or has no data.")
        return

    data_for_export = entry_obj_to_export.data
    
    export_target_path = filedialog.asksaveasfilename(
        defaultextension=".png",
        filetypes=[("PNG Files", "*.png"), ("DDS Files", "*.dds")],
        initialfile=f"{file_name_to_export}"
    )
    if not export_target_path:
        return

    temp_dds_path_for_export = None
    try:
        if export_target_path.lower().endswith(".png"):
            with tempfile.NamedTemporaryFile(delete=False, suffix=".dds") as temp_dds_f:
                temp_dds_f.write(data_for_export)
                temp_dds_path_for_export = temp_dds_f.name
            
            with Image.open(temp_dds_path_for_export) as pil_img_export:
                pil_img_export.save(export_target_path, "PNG")
            messagebox.showinfo("Export Successful", f"Exported '{file_name_to_export}.dds' as PNG to:\n'{export_target_path}'")
            logging.info(f"Exported {file_name_to_export}.dds as PNG to {export_target_path}")

        elif export_target_path.lower().endswith(".dds"):
            with open(export_target_path, 'wb') as out_f_dds:
                out_f_dds.write(data_for_export)
            messagebox.showinfo("Export Successful", f"Exported '{file_name_to_export}.dds' as DDS to:\n'{export_target_path}'")
            logging.info(f"Exported {file_name_to_export}.dds as DDS to {export_target_path}")
        else:
            messagebox.showerror("Error", "Unsupported export format. Please choose .png or .dds.")
    except Exception as e_export:
        messagebox.showerror("Export Error", f"Failed to export file: {e_export}")
        logging.error(f"Failed to export file: {e_export}", exc_info=True)
    finally:
        if temp_dds_path_for_export and os.path.exists(temp_dds_path_for_export):
            try:
                os.remove(temp_dds_path_for_export)
            except Exception as e_clean_export:
                 logging.warning(f"Could not remove temp export file {temp_dds_path_for_export}: {e_clean_export}")

def previous_image():
    global current_image_index, composite_mode_active
    if composite_mode_active or not file_path or not image_files:
        return # No image navigation in composite mode or if no file/images

    original_idx = current_image_index
    num_img_files = len(image_files)
    if num_img_files == 0: return

    for i in range(num_img_files): # Try each image at most once
        current_image_index = (original_idx - 1 - i + num_img_files*2) % num_img_files # Ensures positive index
        if extract_and_display_texture(): # If successful, break
            return
    # If loop completes, no displayable texture found going previous
    current_image_index = original_idx # Revert to original if none found
    if not extract_and_display_texture(): # Try to display original again or show error
        preview_canvas.delete("all")
        texture_label.config(text="No displayable textures found.")
        current_image = None


def next_image():
    global current_image_index, composite_mode_active
    if composite_mode_active or not file_path or not image_files:
        return

    original_idx = current_image_index
    num_img_files = len(image_files)
    if num_img_files == 0: return
    
    for i in range(num_img_files):
        current_image_index = (original_idx + 1 + i) % num_img_files
        if extract_and_display_texture():
            return
    current_image_index = original_idx 
    if not extract_and_display_texture():
        preview_canvas.delete("all")
        texture_label.config(text="No displayable textures found.")
        current_image = None


def toggle_preview_background():
    global preview_bg_color_is_white, composite_mode_active
    if composite_mode_active: # Background toggle is for single view only
        return
    preview_bg_color_is_white = not preview_bg_color_is_white
    
    if file_path and current_image: # Only refresh if an image is currently displayed
        # Re-composite with new background and redraw
        # extract_and_display_texture handles the full logic of reading and compositing
        extract_and_display_texture() 
    # If no image is displayed, the next time one is loaded, it will use the new bg color.


# --- Composite Mode Functions ---
def toggle_composite_mode():
    global composite_mode_active, current_image_index, image_files, current_image
    global composite_zoom_level, composite_pan_offset_x, composite_pan_offset_y
    global import_button, export_button, highlighted_offset_entries, toggle_bg_button

    logging.info(f"Toggling composite mode. Current state: {composite_mode_active}")

    if not composite_mode_active: # Switching TO composite mode
        is_internal_name_ok = internal_name_label.cget("text").startswith("Internal Name: ") and \
            not internal_name_label.cget("text").endswith("(No Config)") and \
            not internal_name_label.cget("text").endswith("(Detection Failed)")
        
        if not file_path or not is_internal_name_ok:
            messagebox.showinfo("Info", "Load a .big file with a valid internal name configuration first to use Composite View.")
            logging.warning("Prerequisites for composite mode not met (file/internal name).")
            return

        # Composite mode requires "10.dds" to be the current texture context
        # If not on "10", try to switch to it.
        target_image_name_for_composite = "10"
        if not (0 <= current_image_index < len(image_files) and image_files[current_image_index] == target_image_name_for_composite):
            logging.info(f"Not on {target_image_name_for_composite}. Attempting to switch for composite mode.")
            try:
                idx_10 = image_files.index(target_image_name_for_composite)
                current_image_index = idx_10
                # We need to extract it to ensure it's valid, but we won't display it in single view immediately
                # The display_composite_view will handle its own rendering.
                # This step is more of a validation that 10.dds exists and is loadable.
                # We store the result of extract_and_display_texture but then clear single view stuff.
                # Temporarily allow single view to load it.
                _temp_composite_active = composite_mode_active
                composite_mode_active = False # Force single view logic for this temp extraction
                success_loading_10 = extract_and_display_texture()
                composite_mode_active = _temp_composite_active # Restore

                if not success_loading_10:
                    messagebox.showerror("Error", f"Could not load {target_image_name_for_composite}.dds. Cannot enter composite mode.")
                    logging.error(f"Failed to load {target_image_name_for_composite}.dds for composite mode entry.")
                    return
                # update_status(f"Context set to {target_image_name_for_composite}.dds for composite mode", "blue") # No explicit status message
                root.update_idletasks() # Allow UI to catch up if needed
            except ValueError:
                messagebox.showerror("Error", f"'{target_image_name_for_composite}' not found in image_files list. Cannot enter composite mode.")
                return

        # Clear single view artifacts before entering composite
        preview_canvas.delete("all")
        current_image = None # Single view PIL image no longer relevant
        texture_label.config(text="") # Clear single view labels
        image_dimensions_label.config(text="")

        composite_mode_active = True
        composite_zoom_level = 1.0
        composite_pan_offset_x = 250.0 # Initial pan for better default view
        composite_pan_offset_y = 50.0
        
        display_composite_view() # This populates composite_elements and draws

        if not composite_mode_active: # If display_composite_view failed and reset the flag
            logging.warning("display_composite_view failed, reverting composite mode toggle.")
            # UI elements might need to be reset if they were partially changed
            return

        composite_view_button.config(text="Single View")
        left_arrow_button.pack_forget() # Hide single view navigation
        right_arrow_button.pack_forget()
        import_button.config(state=tk.DISABLED) # Disable import/export in composite
        export_button.config(state=tk.DISABLED)
        toggle_bg_button.config(state=tk.DISABLED) # Disable bg toggle
        logging.info("Switched TO composite mode successfully.")
    
    else: # Switching FROM composite mode (to single view)
        clear_all_highlights()
        logging.info("Attempting to switch FROM composite mode.")
        composite_mode_active = False
        clear_composite_view() # Clear canvas and composite_elements
        
        composite_view_button.config(text="Composite View")
        # Restore single view controls
        left_arrow_button.pack(side=tk.LEFT, padx=(0, 5), pady=5, anchor='center')
        right_arrow_button.pack(side=tk.LEFT, padx=5, pady=5, anchor='center')
        import_button.config(state=tk.NORMAL)
        export_button.config(state=tk.NORMAL)
        toggle_bg_button.config(state=tk.NORMAL)

        if file_path: # If a file is loaded, display its current texture
            # current_image_index should still be valid (or reset to 0 if "10" was not found)
            extract_and_display_texture()
        else: # No file loaded, clear single view
            preview_canvas.delete("all")
            texture_label.config(text="No file loaded")
            image_dimensions_label.config(text="")
        logging.info("Switched FROM composite mode.")

def clear_all_highlights():
    global highlighted_offset_entries
    for entry_widget, original_bg_color in highlighted_offset_entries:
        try:
            if entry_widget.winfo_exists(): # Check if widget still exists
                entry_widget.config(bg=original_bg_color)
        except tk.TclError:
            pass # Widget might have been destroyed
    highlighted_offset_entries.clear()

def clear_composite_view():
    global composite_elements, preview_canvas
    preview_canvas.delete("composite_item") # Delete items by shared tag
    for el_data in composite_elements: # Clean up TkImage references if any
        if 'tk_image_ref' in el_data and el_data['tk_image_ref']:
            # Python's GC should handle these, but explicit deletion is safer for Tkinter image refs
            del el_data['tk_image_ref'] 
    composite_elements.clear()
    preview_canvas.config(bg="#CCCCCC") # Reset background to default single view color

def redraw_composite_view():
    global composite_elements, preview_canvas, composite_zoom_level, composite_pan_offset_x, composite_pan_offset_y
    global colors, root # For text colors

    preview_canvas.delete("composite_item") # Clear old items

    canvas_w = preview_canvas.winfo_width()
    canvas_h = preview_canvas.winfo_height()
    if canvas_w <= 1: canvas_w = 580 # Fallback
    if canvas_h <= 1: canvas_h = 150

    # Calculate view origin based on pan and zoom (center of canvas is (0,0) in view space)
    view_origin_x_on_canvas = canvas_w / 2.0
    view_origin_y_on_canvas = canvas_h / 2.0
    
    # Pan offsets are in original coordinate space, so scale them by zoom for canvas offset
    effective_pan_x = composite_pan_offset_x * composite_zoom_level
    effective_pan_y = composite_pan_offset_y * composite_zoom_level


    for el_data in composite_elements:
        # Calculate current screen coordinates for the element's original_x, original_y
        # Element's (0,0) in its own original space is at:
        # (view_origin_x_on_canvas - effective_pan_x + el_data['original_x'] * composite_zoom_level,
        #  view_origin_y_on_canvas - effective_pan_y + el_data['original_y'] * composite_zoom_level)
        
        # Top-left corner of the element on canvas:
        screen_x = view_origin_x_on_canvas - effective_pan_x + (el_data['original_x'] * composite_zoom_level)
        screen_y = view_origin_y_on_canvas - effective_pan_y + (el_data['original_y'] * composite_zoom_level)

        el_data['current_x_on_canvas'] = screen_x # Store for potential hit testing
        el_data['current_y_on_canvas'] = screen_y

        if el_data.get('type') == "text":
            base_font_sz = el_data.get('base_font_size', DEFAULT_TEXT_BASE_FONT_SIZE)
            zoomed_font_sz = max(1, int(base_font_sz * composite_zoom_level))
            font_fam = el_data.get('font_family', DEFAULT_TEXT_FONT_FAMILY)
            
            text_col = DEFAULT_TEXT_COLOR_FALLBACK # Default
            color_label_key = el_data.get('color_offset_label')
            if color_label_key and color_label_key in colors and hasattr(root, 'color_vars'):
                color_json_key_tuple = tuple(colors[color_label_key])
                if color_json_key_tuple in root.color_vars:
                    current_hex_val = root.color_vars[color_json_key_tuple].get()
                    if current_hex_val and current_hex_val.startswith("#") and len(current_hex_val) == 7:
                        text_col = current_hex_val
                    else:
                        logging.warning(f"Invalid hex '{current_hex_val}' for color label '{color_label_key}'. Using fallback.")
                else:
                    logging.warning(f"Variable for color key {color_json_key_tuple} (label: {color_label_key}) not in root.color_vars.")
            elif color_label_key: # Label exists in config but not in loaded 'colors' for this internal name
                logging.warning(f"Color label '{color_label_key}' for text '{el_data['display_tag']}' not found in global 'colors' dict.")

            item_id = preview_canvas.create_text(int(screen_x), int(screen_y), anchor=tk.NW,
                                                 text=el_data['text_content'],
                                                 font=(font_fam, zoomed_font_sz, "bold"), # Consider "normal" or configurable weight
                                                 fill=text_col,
                                                 tags=("composite_item", el_data['display_tag']))
            el_data['canvas_id'] = item_id
        
        elif el_data.get('type') == "image":
            pil_image_obj = el_data['pil_image']
            zoomed_w_img = int(pil_image_obj.width * composite_zoom_level)
            zoomed_h_img = int(pil_image_obj.height * composite_zoom_level)

            if zoomed_w_img <= 0 or zoomed_h_img <= 0: continue # Skip if too small

            try:
                resized_pil_for_display = pil_image_obj.resize((zoomed_w_img, zoomed_h_img), Image.LANCZOS)
                el_data['tk_image_ref'] = ImageTk.PhotoImage(resized_pil_for_display) # Store ref on element
                
                item_id = preview_canvas.create_image(int(screen_x), int(screen_y), anchor=tk.NW,
                                                      image=el_data['tk_image_ref'],
                                                      tags=("composite_item", el_data['display_tag']))
                el_data['canvas_id'] = item_id
            except Exception as e_redraw_img:
                logging.error(f"Error redrawing composite image {el_data.get('display_tag')}: {e_redraw_img}")
        else:
            logging.warning(f"Unknown element type encountered in redraw_composite_view: {el_data.get('type')}")


def display_composite_view():
    global composite_elements, preview_canvas, file_path, composite_mode_active
    global initial_text_elements_config, predefined_image_coords, offsets, root, current_reference_width, current_reference_height

    logging.info("Attempting to display composite view.")
    if not file_path: # Should be caught by toggle_composite_mode, but defensive
        composite_mode_active = False # Ensure exit if somehow entered without file
        return
    
    preview_canvas.config(bg="gray70") # Distinct background for composite mode

    try:
        big_file = FifaBigFile(file_path) # Re-parse for fresh image data
        # Internal name should already be validated by toggle_composite_mode
        # Reference width/height should be set by add_internal_name
        if current_reference_width is None or current_reference_height is None:
            logging.warning("Reference dimensions not set. Composite view might be inaccurate.")
            # Could default them here, e.g., to canvas size, but better if JSON provides them.

        canvas_w = preview_canvas.winfo_width()
        canvas_h = preview_canvas.winfo_height()
        if canvas_w <= 1: canvas_w = 580
        if canvas_h <= 1: canvas_h = 150

        # Prepare image elements
        images_to_load_from_config = [ # (name_in_big_file, display_tag_suffix_in_predefined_coords)
            ("10", "10"), 
            ("14", "14"), 
            ("30", "30_orig"), 
            ("30", "30_dup") # "30" is loaded twice for home/away bars
        ]
        # Cache source DDS entries from BIG file
        source_dds_entries = {
            entry.name: entry for entry in big_file.entries 
            if entry.name in [cfg[0] for cfg in images_to_load_from_config] and \
               entry.file_type == "DDS" and entry.data
        }

        temp_composite_elements_map: Dict[str, Dict[str, Any]] = {} # Use dict for easier linking later

        # --- Load Image Elements ---
        for big_file_img_name, display_tag_key_suffix in images_to_load_from_config:
            if big_file_img_name not in source_dds_entries:
                logging.warning(f"Image '{big_file_img_name}' for composite element not found in BIG file.")
                continue
            
            source_entry = source_dds_entries[big_file_img_name]
            current_img_display_tag = f"img_{display_tag_key_suffix}" # e.g., "img_10", "img_30_orig"

            # Get config for this specific image instance
            img_instance_config = predefined_image_coords.get(current_img_display_tag)
            if not img_instance_config:
                logging.error(f"Missing predefined_image_coords config for '{current_img_display_tag}'. Skipping.")
                continue
            
            gui_ref_x_cfg, gui_ref_y_cfg, x_offset_label_cfg, base_game_x_cfg, y_offset_label_cfg, base_game_y_cfg = img_instance_config

            temp_dds_render_path = None
            try:
                with tempfile.NamedTemporaryFile(delete=False, suffix=".dds") as tmp_f:
                    tmp_f.write(source_entry.data)
                    temp_dds_render_path = tmp_f.name
                pil_img_obj = Image.open(temp_dds_render_path).convert("RGBA") # Ensure RGBA

                # Calculate initial visual position based on GUI_Ref and game data deviation
                current_visual_original_x = float(gui_ref_x_cfg)
                current_visual_original_y = float(gui_ref_y_cfg)
                linked_x_var_obj = None
                linked_y_var_obj = None

                if x_offset_label_cfg and y_offset_label_cfg and base_game_x_cfg is not None and base_game_y_cfg is not None and \
                   hasattr(root, 'offsets_vars') and offsets: # Check if essential linking info exists
                    if x_offset_label_cfg in offsets and y_offset_label_cfg in offsets:
                        x_key_tuple_json = tuple(offsets[x_offset_label_cfg])
                        y_key_tuple_json = tuple(offsets[y_offset_label_cfg])
                        if x_key_tuple_json in root.offsets_vars and y_key_tuple_json in root.offsets_vars:
                            linked_x_var_obj = root.offsets_vars[x_key_tuple_json]
                            linked_y_var_obj = root.offsets_vars[y_key_tuple_json]
                            try:
                                current_game_offset_x_val = float(linked_x_var_obj.get())
                                current_game_offset_y_val = float(linked_y_var_obj.get())
                                deviation_x_from_base = current_game_offset_x_val - base_game_x_cfg
                                deviation_y_from_base = current_game_offset_y_val - base_game_y_cfg
                                current_visual_original_x = float(gui_ref_x_cfg) + deviation_x_from_base
                                current_visual_original_y = float(gui_ref_y_cfg) + deviation_y_from_base
                            except ValueError: # If current game offset in Entry is not a float
                                logging.warning(f"Non-float value in Entry for linked offset of '{current_img_display_tag}'. Using GUI Ref only.")
                                linked_x_var_obj = None # Break link if data is bad
                                linked_y_var_obj = None
                
                is_fixed_img = (current_img_display_tag == "img_10") # img_10 is the base, always fixed
                # img_14's fixed status determined during conjoining logic

                img_element_data = {
                    'type': "image", 'pil_image': pil_img_obj,
                    'original_x': current_visual_original_x, 'original_y': current_visual_original_y,
                    'image_name_in_big': source_entry.name, 'display_tag': current_img_display_tag,
                    'tk_image_ref': None, 'canvas_id': None, 'is_fixed': is_fixed_img,
                    'x_offset_label_linked': x_offset_label_cfg, 'y_offset_label_linked': y_offset_label_cfg,
                    'x_var_linked': linked_x_var_obj, 'y_var_linked': linked_y_var_obj,
                    'base_game_x': base_game_x_cfg, 'base_game_y': base_game_y_cfg,
                    'gui_ref_x': gui_ref_x_cfg, 'gui_ref_y': gui_ref_y_cfg
                }
                temp_composite_elements_map[current_img_display_tag] = img_element_data
            except Exception as e_img_prep:
                logging.error(f"Error preparing composite image element '{current_img_display_tag}' (from {source_entry.name}): {e_img_prep}", exc_info=True)
            finally:
                if temp_dds_render_path and os.path.exists(temp_dds_render_path):
                    os.remove(temp_dds_render_path)

        # --- Load Text Elements ---
        for tag_cfg, text_content_cfg, gui_ref_x_cfg, gui_ref_y_cfg, font_size_override_cfg, color_label_cfg, \
            is_fixed_text_cfg, x_offset_label_cfg, base_game_x_cfg, y_offset_label_cfg, base_game_y_cfg in initial_text_elements_config:
            
            current_visual_original_x = float(gui_ref_x_cfg)
            current_visual_original_y = float(gui_ref_y_cfg)
            linked_x_var_obj = None
            linked_y_var_obj = None

            if x_offset_label_cfg and y_offset_label_cfg and base_game_x_cfg is not None and base_game_y_cfg is not None and \
               hasattr(root, 'offsets_vars') and offsets:
                if x_offset_label_cfg in offsets and y_offset_label_cfg in offsets:
                    x_key_tuple_json = tuple(offsets[x_offset_label_cfg])
                    y_key_tuple_json = tuple(offsets[y_offset_label_cfg])
                    if x_key_tuple_json in root.offsets_vars and y_key_tuple_json in root.offsets_vars:
                        linked_x_var_obj = root.offsets_vars[x_key_tuple_json]
                        linked_y_var_obj = root.offsets_vars[y_key_tuple_json]
                        try:
                            current_game_offset_x_val = float(linked_x_var_obj.get())
                            current_game_offset_y_val = float(linked_y_var_obj.get())
                            deviation_x_from_base = current_game_offset_x_val - base_game_x_cfg
                            deviation_y_from_base = current_game_offset_y_val - base_game_y_cfg
                            current_visual_original_x = float(gui_ref_x_cfg) + deviation_x_from_base
                            current_visual_original_y = float(gui_ref_y_cfg) + deviation_y_from_base
                        except ValueError:
                            logging.warning(f"Non-float value in Entry for linked offset of text '{tag_cfg}'. Using GUI Ref only.")
                            linked_x_var_obj = None 
                            linked_y_var_obj = None
            
            text_element_data = {
                'type': "text", 'text_content': text_content_cfg,
                'original_x': current_visual_original_x, 'original_y': current_visual_original_y,
                'base_font_size': font_size_override_cfg or DEFAULT_TEXT_BASE_FONT_SIZE,
                'font_family': DEFAULT_TEXT_FONT_FAMILY, 'color_offset_label': color_label_cfg,
                'display_tag': tag_cfg, 'canvas_id': None, 'is_fixed': is_fixed_text_cfg,
                'x_offset_label_linked': x_offset_label_cfg, 'y_offset_label_linked': y_offset_label_cfg,
                'x_var_linked': linked_x_var_obj, 'y_var_linked': linked_y_var_obj,
                'base_game_x': base_game_x_cfg, 'base_game_y': base_game_y_cfg,
                'gui_ref_x': gui_ref_x_cfg, 'gui_ref_y': gui_ref_y_cfg
            }
            temp_composite_elements_map[tag_cfg] = text_element_data

        # --- Apply Conjoining Logic (e.g., img_14 to text_added_time) ---
        leader_tag_for_img14_conjoin = "text_added_time"
        follower_tag_img14_conjoin = "img_14"
        
        if leader_tag_for_img14_conjoin in temp_composite_elements_map and \
           follower_tag_img14_conjoin in temp_composite_elements_map:
            
            leader_el_data = temp_composite_elements_map[leader_tag_for_img14_conjoin]
            follower_el_data = temp_composite_elements_map[follower_tag_img14_conjoin]

            # GUI Ref for img_14 from predefined_image_coords
            img14_gui_ref_x_abs = predefined_image_coords[follower_tag_img14_conjoin][0]
            img14_gui_ref_y_abs = predefined_image_coords[follower_tag_img14_conjoin][1]

            # GUI Ref for text_added_time from initial_text_elements_config
            text_added_time_config_item = next(item for item in initial_text_elements_config if item[0] == leader_tag_for_img14_conjoin)
            text_added_time_gui_ref_x_abs = text_added_time_config_item[2]
            text_added_time_gui_ref_y_abs = text_added_time_config_item[3]

            # Calculate the *design-time* relative offset
            design_relative_offset_x = img14_gui_ref_x_abs - text_added_time_gui_ref_x_abs
            design_relative_offset_y = img14_gui_ref_y_abs - text_added_time_gui_ref_y_abs
            
            # Set follower's position based on leader's *current* visual position + design relative offset
            follower_el_data['original_x'] = leader_el_data['original_x'] + design_relative_offset_x
            follower_el_data['original_y'] = leader_el_data['original_y'] + design_relative_offset_y

            # Mark as conjoined and store relative offset
            follower_el_data['conjoined_to_tag'] = leader_tag_for_img14_conjoin
            follower_el_data['relative_offset_x'] = design_relative_offset_x
            follower_el_data['relative_offset_y'] = design_relative_offset_y
            follower_el_data['is_fixed'] = True # Conjoined elements are fixed relative to leader (leader might be draggable)

            # Ensure leader is draggable if not explicitly fixed in its own config
            # (if the leader's is_fixed was False from its config, it remains False)
            # If leader was True, it remains True. If it was False, user can drag it, and follower moves too.
            # The logic for leader_el_data['is_fixed'] is already set from its config.

        composite_elements = list(temp_composite_elements_map.values()) # Convert map to list
        redraw_composite_view() # Initial draw
        
        texture_label.config(text="Composite Mode Active")
        image_dimensions_label.config(text=f"Canvas: {canvas_w}x{canvas_h} | Ref: {current_reference_width or 'N/A'}x{current_reference_height or 'N/A'}")
    
    except Exception as e_comp_disp:
        messagebox.showerror("Composite View Error", f"Failed to display composite view: {e_comp_disp}")
        logging.error(f"CRITICAL: Error displaying composite view: {e_comp_disp}", exc_info=True)
        composite_mode_active = False # Attempt to gracefully exit composite mode
        toggle_composite_mode() # This will try to switch back to single view


def zoom_composite_view(event):
    global composite_zoom_level, composite_pan_offset_x, composite_pan_offset_y, preview_canvas
    if not composite_elements: return

    factor = 1.1 if event.delta > 0 else (1 / 1.1)
    new_zoom = max(0.05, min(composite_zoom_level * factor, 10.0)) # Zoom limits

    # Zoom towards mouse cursor
    canvas_w = preview_canvas.winfo_width()
    canvas_h = preview_canvas.winfo_height()

    # Mouse position relative to canvas center
    mouse_x_from_center = event.x - (canvas_w / 2.0)
    mouse_y_from_center = event.y - (canvas_h / 2.0)

    # Adjust pan offset to keep the point under the mouse stationary
    # The amount the view "shifts" due to zoom change, relative to center:
    # pan_adjust_x = mouse_x_from_center * (1/old_zoom - 1/new_zoom)
    # pan_adjust_y = mouse_y_from_center * (1/old_zoom - 1/new_zoom)
    # This pan_adjust is in *original coordinate space*
    if abs(composite_zoom_level) > 1e-6 and abs(new_zoom) > 1e-6: # Avoid division by zero
        pan_adjust_x = mouse_x_from_center * ( (1.0 / composite_zoom_level) - (1.0 / new_zoom) )
        pan_adjust_y = mouse_y_from_center * ( (1.0 / composite_zoom_level) - (1.0 / new_zoom) )
        
        composite_pan_offset_x += pan_adjust_x
        composite_pan_offset_y += pan_adjust_y

    composite_zoom_level = new_zoom
    redraw_composite_view()

def start_pan_composite(event): # Called on RMB press
    global drag_data
    drag_data["is_panning_rmb"] = True
    drag_data["x"] = event.x
    drag_data["y"] = event.y
    logging.debug(f"Composite RMB Pan started at ({event.x},{event.y})")

def on_pan_composite(event): # Called on RMB drag
    global drag_data, composite_pan_offset_x, composite_pan_offset_y, composite_zoom_level
    if not drag_data.get("is_panning_rmb"):
        return
    
    dx_canvas = event.x - drag_data["x"]
    dy_canvas = event.y - drag_data["y"]

    if abs(composite_zoom_level) > 1e-6: # Avoid division by zero
        # Convert canvas delta to original coordinate delta
        delta_orig_x = dx_canvas / composite_zoom_level
        delta_orig_y = dy_canvas / composite_zoom_level
        
        composite_pan_offset_x -= delta_orig_x # Subtract because panning moves the "camera"
        composite_pan_offset_y -= delta_orig_y
    
    drag_data["x"] = event.x
    drag_data["y"] = event.y
    redraw_composite_view()

def start_drag_composite(event): # Called on LMB press in composite mode
    global composite_drag_data, composite_elements, drag_data, highlighted_offset_entries, offsets, root
    
    clear_all_highlights() # Clear previous highlights

    if event.num == 3: # Right mouse button
        start_pan_composite(event)
        return

    # Reset left-click pan flags from single view (shouldn't be active, but defensive)
    drag_data["is_panning"] = False 
    drag_data["is_panning_rmb"] = False # Ensure RMB pan is false if LMB is pressed

    # Find which composite item was clicked (if any)
    # Use canvas coordinates from event
    # Need to convert canvas click (event.x, event.y) to original coordinate space
    # then check against element bounding boxes (more complex)
    # OR, simpler: use find_closest and check tags.

    item_tuple_under_mouse = event.widget.find_closest(event.x, event.y)
    if not item_tuple_under_mouse:
        composite_drag_data['item'] = None # Clicked on empty space
        return
    
    clicked_canvas_item_id = item_tuple_under_mouse[0]
    
    # Check if the clicked item is part of our composite scene
    if "composite_item" not in preview_canvas.gettags(clicked_canvas_item_id):
        composite_drag_data['item'] = None
        return

    # Find the element data corresponding to this canvas item
    for el_data in composite_elements:
        if el_data.get('canvas_id') == clicked_canvas_item_id:
            if el_data.get('is_fixed', False):
                logging.info(f"Attempted to drag fixed composite item: {el_data.get('display_tag')}")
                composite_drag_data['item'] = None # Cannot drag fixed items
                return

            # Store initial game offsets if linked, for relative update during drag
            initial_game_x_val, initial_game_y_val = 0.0, 0.0
            x_var_link = el_data.get('x_var_linked')
            y_var_link = el_data.get('y_var_linked')
            if x_var_link and y_var_link:
                try:
                    initial_game_x_val = float(x_var_link.get())
                    initial_game_y_val = float(y_var_link.get())
                except ValueError:
                    logging.warning(f"Could not parse initial game offsets for '{el_data.get('display_tag')}' during drag start. Using 0,0.")
            
            composite_drag_data.update({
                'item': clicked_canvas_item_id, 
                'x': event.x, # Canvas click X
                'y': event.y, # Canvas click Y
                'element_data': el_data,
                'start_original_x': el_data['original_x'], # Element's original_x at drag start
                'start_original_y': el_data['original_y'], # Element's original_y at drag start
                'initial_game_offset_x_at_drag_start': initial_game_x_val,
                'initial_game_offset_y_at_drag_start': initial_game_y_val
            })
            preview_canvas.tag_raise(clicked_canvas_item_id) # Bring to front

            # Highlight linked offset entries
            x_label_for_highlight = el_data.get('x_offset_label_linked')
            y_label_for_highlight = el_data.get('y_offset_label_linked')
            if x_label_for_highlight and x_label_for_highlight in offsets and hasattr(root, 'offset_entry_widgets'):
                x_key_tuple_h = tuple(offsets[x_label_for_highlight])
                if x_key_tuple_h in root.offset_entry_widgets:
                    entry_w_h = root.offset_entry_widgets[x_key_tuple_h]
                    highlighted_offset_entries.append((entry_w_h, entry_w_h.cget("background")))
                    entry_w_h.config(bg="lightyellow")
            if y_label_for_highlight and y_label_for_highlight in offsets and hasattr(root, 'offset_entry_widgets'):
                y_key_tuple_h = tuple(offsets[y_label_for_highlight])
                if y_key_tuple_h in root.offset_entry_widgets:
                    entry_w_h = root.offset_entry_widgets[y_key_tuple_h]
                    # Avoid double-adding if X and Y use same entry (unlikely for positions)
                    if not any(he[0] == entry_w_h for he in highlighted_offset_entries):
                        highlighted_offset_entries.append((entry_w_h, entry_w_h.cget("background")))
                        entry_w_h.config(bg="lightyellow")
            return # Found and set up drag data for one element
            
    composite_drag_data['item'] = None # No draggable element found under cursor

def on_drag_composite(event): # Called on LMB drag in composite mode
    global composite_drag_data, composite_zoom_level, drag_data, composite_elements, offsets, root
    
    if event.num == 3 or drag_data.get("is_panning_rmb"): # If it's a right-click drag
        on_pan_composite(event) # Handle as pan
        return

    if composite_drag_data.get('item') is None or drag_data.get("is_panning"): # No item selected or in single-view pan
        return

    dragged_el_data = composite_drag_data.get('element_data')
    if not dragged_el_data: return

    # Delta mouse movement on canvas
    mouse_dx_on_canvas = event.x - composite_drag_data['x']
    mouse_dy_on_canvas = event.y - composite_drag_data['y']

    if abs(composite_zoom_level) < 1e-6: return # Avoid division by zero

    # Convert canvas delta to delta in original coordinate space
    delta_visual_original_x = mouse_dx_on_canvas / composite_zoom_level
    delta_visual_original_y = mouse_dy_on_canvas / composite_zoom_level

    # New visual original position for the dragged element
    new_visual_orig_x = composite_drag_data['start_original_x'] + delta_visual_original_x
    new_visual_orig_y = composite_drag_data['start_original_y'] + delta_visual_original_y
    
    dragged_el_data['original_x'] = new_visual_orig_x
    dragged_el_data['original_y'] = new_visual_orig_y
    
    # If linked to game offsets, update them 1:1 with the visual change
    x_var_to_update = dragged_el_data.get('x_var_linked')
    y_var_to_update = dragged_el_data.get('y_var_linked')

    if x_var_to_update and y_var_to_update:
        initial_game_x_at_drag = composite_drag_data['initial_game_offset_x_at_drag_start']
        initial_game_y_at_drag = composite_drag_data['initial_game_offset_y_at_drag_start']
        
        # New game offset = Initial game offset at drag start + delta in visual original space
        new_game_offset_x_val = initial_game_x_at_drag + delta_visual_original_x
        new_game_offset_y_val = initial_game_y_at_drag + delta_visual_original_y

        old_x_str_val = x_var_to_update.get()
        old_y_str_val = y_var_to_update.get()
        new_x_str_val = f"{new_game_offset_x_val:.2f}"
        new_y_str_val = f"{new_game_offset_y_val:.2f}"

        x_var_to_update.set(new_x_str_val)
        y_var_to_update.set(new_y_str_val)
        
        logging.info(f"Drag: Element '{dragged_el_data.get('display_tag')}' moved. Linked game offsets updated to X={new_x_str_val}, Y={new_y_str_val}")

        # Record undo actions for these changes
        x_offset_label_linked = dragged_el_data.get('x_offset_label_linked')
        y_offset_label_linked = dragged_el_data.get('y_offset_label_linked')

        if x_offset_label_linked and x_offset_label_linked in offsets:
            x_key_tuple_undo = tuple(offsets[x_offset_label_linked])
            if old_x_str_val != new_x_str_val: # Only record if value changed
                action_x_drag = EditAction(x_var_to_update, old_x_str_val, new_x_str_val, x_key_tuple_undo, 
                                           root.offset_entry_widgets.get(x_key_tuple_undo), 
                                           f"Drag {dragged_el_data.get('display_tag')} X")
                undo_manager.record_action(action_x_drag)
            # Call update_value to refresh asterisk etc., pass from_undo_redo=True to avoid re-recording
            update_value(x_key_tuple_undo, x_var_to_update, from_undo_redo=True)

        if y_offset_label_linked and y_offset_label_linked in offsets:
            y_key_tuple_undo = tuple(offsets[y_offset_label_linked])
            if old_y_str_val != new_y_str_val:
                action_y_drag = EditAction(y_var_to_update, old_y_str_val, new_y_str_val, y_key_tuple_undo,
                                           root.offset_entry_widgets.get(y_key_tuple_undo),
                                           f"Drag {dragged_el_data.get('display_tag')} Y")
                undo_manager.record_action(action_y_drag)
            update_value(y_key_tuple_undo, y_var_to_update, from_undo_redo=True)

    # If this dragged element is a leader for conjoined elements, update them
    dragged_el_tag_name = dragged_el_data.get('display_tag')
    if dragged_el_tag_name:
        for follower_el_data in composite_elements:
            if follower_el_data.get('conjoined_to_tag') == dragged_el_tag_name:
                follower_el_data['original_x'] = dragged_el_data['original_x'] + follower_el_data.get('relative_offset_x', 0)
                follower_el_data['original_y'] = dragged_el_data['original_y'] + follower_el_data.get('relative_offset_y', 0)
    
    redraw_composite_view()

def on_drag_release_composite(event): # Called on RMB release
    global drag_data
    if event.num == 3: # Right mouse button release
        drag_data["is_panning_rmb"] = False
        logging.debug("Composite RMB Pan released.")
    # LMB release is handled by the general on_drag_release_handler for clearing highlights

# --- UI Setup ---
root = tk.Tk()
root.title("FLP Scoreboard Editor 25 (v1.13)")
root.geometry("930x710")
root.resizable(False, False)

# --- Menubar ---
menubar = tk.Menu(root)
# File Menu
filemenu = tk.Menu(menubar, tearoff=0)
filemenu.add_command(label="Open", command=open_file, accelerator="Ctrl+O")
filemenu.add_command(label="Save", command=save_file, accelerator="Ctrl+S")
filemenu.add_separator()
filemenu.add_command(label="Exit", command=exit_app)
menubar.add_cascade(label="File", menu=filemenu)
# Edit Menu (for Undo/Redo)
editmenu = tk.Menu(menubar, tearoff=0)
editmenu.add_command(label="Undo", command=lambda: undo_manager.undo(), accelerator="Ctrl+Z", state=tk.DISABLED)
editmenu.add_command(label="Redo", command=lambda: undo_manager.redo(), accelerator="Ctrl+Y", state=tk.DISABLED)
menubar.add_cascade(label="Edit", menu=editmenu)
root.editmenu = editmenu # Store reference for UndoManager to update states
# Help Menu
helpmenu = tk.Menu(menubar, tearoff=0)
helpmenu.add_command(label="About", command=about)
helpmenu.add_separator()
helpmenu.add_command(label="Documentation", command=show_documentation)
menubar.add_cascade(label="Help", menu=helpmenu)
root.config(menu=menubar)

# Bind Ctrl+O, Ctrl+S, Ctrl+Z, Ctrl+Y globally
root.bind_all("<Control-o>", lambda event: open_file())
root.bind_all("<Control-s>", lambda event: save_file())
root.bind_all("<Control-z>", lambda event: undo_manager.undo())
root.bind_all("<Control-y>", lambda event: undo_manager.redo())


# --- Main Editor Tabs (Notebook) ---
notebook = ttk.Notebook(root)
# Positions Tab with Scrollbar
positions_frame_container = ttk.Frame(notebook) # Container for canvas+scrollbar
positions_canvas = tk.Canvas(positions_frame_container, highlightthickness=0)
positions_scrollbar = ttk.Scrollbar(positions_frame_container, orient="vertical", command=positions_canvas.yview)
positions_frame = ttk.Frame(positions_canvas) # Actual frame for widgets

positions_frame.bind(
    "<Configure>", # Update scrollregion when frame size changes
    lambda e: positions_canvas.configure(scrollregion=positions_canvas.bbox("all"))
)
positions_canvas.create_window((0, 0), window=positions_frame, anchor="nw") # Embed frame in canvas
positions_canvas.configure(yscrollcommand=positions_scrollbar.set)

positions_canvas.pack(side="left", fill="both", expand=True)
positions_scrollbar.pack(side="right", fill="y")
notebook.add(positions_frame_container, text="Positions")

# Sizes Tab
sizes_frame = ttk.Frame(notebook)
notebook.add(sizes_frame, text="Sizes")
# Colors Tab
colors_frame = ttk.Frame(notebook)
notebook.add(colors_frame, text="Colors")
notebook.pack(expand=1, fill="both", padx=10, pady=5)


# --- Preview Area and Controls ---
preview_controls_frame = tk.Frame(root)
preview_controls_frame.pack(fill=tk.X, padx=10, pady=5)

left_arrow_button = ttk.Button(preview_controls_frame, text="◀", command=previous_image, width=2)
left_arrow_button.pack(side=tk.LEFT, padx=(0, 5), pady=5, anchor='center')

preview_canvas = tk.Canvas(preview_controls_frame, width=580, height=150, bg="#CCCCCC", relief="solid", bd=1)
preview_canvas.pack(side=tk.LEFT, padx=5, pady=5, anchor='center')
# Bindings for preview canvas (zoom, drag)
preview_canvas.bind("<MouseWheel>", zoom_image_handler) # Handles both single and composite zoom
preview_canvas.bind("<ButtonPress-1>", start_drag_handler) # Handles L-click drag for single/composite
preview_canvas.bind("<B1-Motion>", on_drag_handler)
preview_canvas.bind("<ButtonRelease-1>", on_drag_release_handler)
# Bindings for composite view right-click pan
preview_canvas.bind("<ButtonPress-3>", start_pan_composite) # Specifically for composite pan start
preview_canvas.bind("<B3-Motion>", on_pan_composite)       # Composite pan drag
preview_canvas.bind("<ButtonRelease-3>", on_drag_release_composite) # Composite pan release

right_arrow_button = ttk.Button(preview_controls_frame, text="▶", command=next_image, width=2)
right_arrow_button.pack(side=tk.LEFT, padx=5, pady=5, anchor='center')

# Vertical stack of buttons next to preview (Toggle Alpha, Composite View)
vertical_buttons_frame = tk.Frame(preview_controls_frame)
vertical_buttons_frame.pack(side=tk.LEFT, padx=(10, 0), pady=0, anchor='n') # Anchor North

toggle_bg_button = ttk.Button(vertical_buttons_frame, text="Toggle Alpha", command=toggle_preview_background, width=15)
toggle_bg_button.pack(side=tk.TOP, pady=(5, 2)) # pady top, then small gap below

composite_view_button = ttk.Button(vertical_buttons_frame, text="Composite View", command=toggle_composite_mode, width=15)
composite_view_button.pack(side=tk.TOP, pady=(2, 5))


# --- Texture Info Labels (below preview) ---
texture_info_frame = tk.Frame(root)
texture_info_frame.pack(fill=tk.X, padx=10, pady=(0, 5))
texture_label = tk.Label(texture_info_frame, text="No texture loaded", font=('Helvetica', 9), anchor='w')
texture_label.pack(side=tk.LEFT, padx=5)
image_dimensions_label = tk.Label(texture_info_frame, text=" ", font=('Helvetica', 10), anchor='e')
image_dimensions_label.pack(side=tk.RIGHT, padx=10)


# --- Main Action Buttons (Import, Export, Save) ---
# Placed using .place for fixed position relative to bottom right, above status bar
buttons_frame = tk.Frame(root)
buttons_frame.place(relx=1.0, rely=1.0, anchor='se', x=-10, y=-85) # y adjusted for status bar

import_button = ttk.Button(buttons_frame, text="IMPORT", command=import_texture, width=10)
import_button.pack(pady=2)
export_button = ttk.Button(buttons_frame, text="EXPORT", command=export_selected_file, width=10)
export_button.pack(pady=2)
save_button_main = ttk.Button(buttons_frame, text="SAVE", command=save_file, width=10)
save_button_main.pack(pady=(2, 0)) # No pady below last button


# --- Status Bar and File Info (Bottom) ---
bottom_frame = tk.Frame(root)
bottom_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=(0, 5)) # pady adjusted
status_label = tk.Label(bottom_frame, text="Ready", anchor=tk.W, fg="blue", font=('Helvetica', 10))
status_label.pack(side=tk.LEFT, padx=0)
file_path_label = tk.Label(bottom_frame, text="File: None", anchor=tk.W, font=('Helvetica', 9)) # Shows only basename
file_path_label.pack(side=tk.LEFT, padx=10)
internal_name_label = tk.Label(bottom_frame, text="Internal Name: Not Loaded", anchor=tk.E, font=('Helvetica', 10))
internal_name_label.pack(side=tk.RIGHT, padx=0)


# --- Styling ---
root.style = ttk.Style()
root.style.configure('TButton', font=('Helvetica', 10), padding=3)
root.style.configure('Large.TButton', font=('Helvetica', 12), padding=5) # For main action buttons

left_arrow_button.configure(style='TButton')
right_arrow_button.configure(style='TButton')
toggle_bg_button.configure(style='TButton')
composite_view_button.configure(style='TButton')
import_button.configure(style='Large.TButton')
export_button.configure(style='Large.TButton')
save_button_main.configure(style='Large.TButton')


# --- Initial State and Main Loop ---
def on_map_event(event): # Ensures canvas dimensions are known for first draw
    if file_path and not current_image and not composite_mode_active:
        # If a file was loaded (e.g., via command line arg in future) before UI fully mapped
        extract_and_display_texture()

root.bind("<Map>", on_map_event, "+") # Call on_map_event when window is first drawn

clear_editor_widgets() # Ensure clean state
undo_manager.update_menu_states() # Initialize menu states

# Check if offsets_data was successfully loaded earlier. If not, exit.
if not offsets_data:
    # Message already shown, just log and ensure exit.
    logging.critical("offsets_data is not loaded. Application cannot continue.")
    # root might not be fully initialized for destroy here, so direct exit.
    exit()

root.mainloop()