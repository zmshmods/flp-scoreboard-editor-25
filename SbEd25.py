import tkinter as tk
from tkinter import filedialog, messagebox, ttk, colorchooser
import struct
import webbrowser
# import struct # Duplicate import removed
import os
import tempfile
from PIL import Image, ImageTk
import json
import logging
from dataclasses import dataclass
from enum import Enum
from typing import List

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Load offsets from JSON file
try:
    with open('offsets.json', 'r') as f:
        offsets_data = json.load(f)
except FileNotFoundError:
    logging.error("offsets.json not found. Please ensure the file exists in the same directory.")
    messagebox.showerror("Error", "offsets.json not found. The application cannot start.")
    exit() # Exit if critical config is missing
except json.JSONDecodeError:
    logging.error("Error decoding offsets.json. Please check its format.")
    messagebox.showerror("Error", "Error decoding offsets.json. The application cannot start.")
    exit()


file_path = None
offsets = {} # Loaded from json based on internal name
colors = {}  # Loaded from json based on internal name
current_image = None  # Store original PIL Image object for zooming/panning
# New global variables to store the previous file path and values
previous_file_path = None
previous_offsets_values = {} # Stores {offset_tuple_key: value_str}
previous_color_values = {}   # Stores {offset_tuple_key: color_hex_str}
preview_bg_color_is_white = True # True for white (default), False for black

class Compression(Enum):
    NONE = "None"
    EAHD = "EAHD"

@dataclass
class FileEntry:
    offset: int         # Offset of the raw data in the BIG file
    size: int           # Decompressed size of the data
    name: str
    file_type: str      # e.g., DDS, APT, DAT
    compression: Compression
    data: bytes         # Decompressed data
    raw_size: int       # Size of the raw (possibly compressed) data in the BIG file

class BinaryReader:
    def __init__(self, data: bytearray):
        self.data = data
        self.pos = 0

    def read_byte(self) -> int:
        if self.pos >= len(self.data):
            raise ValueError("End of stream reached")
        value = self.data[self.pos]
        self.pos += 1
        return value

    def read_int(self, bytes_count: int = 4, big_endian: bool = False) -> int:
        if self.pos + bytes_count > len(self.data):
            raise ValueError(f"Not enough data to read {bytes_count} bytes for int.")
        chunk = self.data[self.pos:self.pos + bytes_count]
        self.pos += bytes_count
        return int.from_bytes(chunk, "big" if big_endian else "little")

    def read_string(self, encoding: str) -> str:
        start = self.pos
        while self.pos < len(self.data) and self.data[self.pos] != 0:
            self.pos += 1
        if self.pos >= len(self.data) and (self.pos == start or self.data[self.pos-1] != 0) : # check if null terminator was even found
             # Handle case where string is not null-terminated or end of data is reached
             result = self.data[start:self.pos].decode(encoding, errors="ignore")
             # No self.pos += 1 because no null terminator to skip
        else:
            result = self.data[start:self.pos].decode(encoding, errors="ignore")
            self.pos += 1  # Skip null terminator
        return result

    def skip(self, count: int):
        if self.pos + count > len(self.data):
            # logging.warning(f"Attempted to skip {count} bytes beyond data length.")
            self.pos = len(self.data) # Go to end
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
                offset_val = 0 # Renamed from 'offset' to avoid conflict

                if ctrl < 0x80:  # Short copy
                    a = reader.read_byte()
                    to_read = ctrl & 0x03
                    to_copy = ((ctrl & 0x1C) >> 2) + 3
                    offset_val = ((ctrl & 0x60) << 3) + a + 1
                elif ctrl < 0xC0:  # Medium copy
                    a, b = reader.read_byte(), reader.read_byte()
                    to_read = (a >> 6) & 0x03
                    to_copy = (ctrl & 0x3F) + 4
                    offset_val = ((a & 0x3F) << 8) + b + 1
                elif ctrl < 0xE0:  # Long copy
                    a, b, c = reader.read_byte(), reader.read_byte(), reader.read_byte()
                    to_read = ctrl & 0x03
                    to_copy = ((ctrl & 0x0C) << 6) + c + 5
                    offset_val = ((ctrl & 0x10) << 12) + (a << 8) + b + 1
                elif ctrl < 0xFC:  # Large read
                    to_read = ((ctrl & 0x1F) << 2) + 4
                else:  # Small read
                    to_read = ctrl & 0x03
                
                if pos + to_read > total_size: # Boundary check
                    to_read = total_size - pos
                for _ in range(to_read):
                    output[pos] = reader.read_byte()
                    pos += 1
                
                if to_copy > 0:
                    copy_start = pos - offset_val
                    if copy_start < 0: # Invalid offset
                        logging.error("EAHD Decompression: Invalid copy offset.")
                        return data # Error condition
                    
                    if pos + to_copy > total_size: # Boundary check
                        to_copy = total_size - pos
                    for _ in range(to_copy):
                        if copy_start >= pos: # Should not happen with valid EAHD
                            logging.error("EAHD Decompression: copy_start >= pos.")
                            return data
                        output[pos] = output[copy_start]
                        pos += 1
                        copy_start += 1
            
            return bytes(output[:pos]) # Return only the written part
        except ValueError as e: # Catch BinaryReader EoS errors
            logging.error(f"ERROR: EAHD decompression failed (ValueError) - {e}")
            return data # Return original on error
        except Exception as e:
            logging.error(f"ERROR: EAHD decompression failed (General Exception) - {e}")
            return data

class Compressor:
    @staticmethod
    def compress_eahd(data: bytes) -> bytes:
        """
        Compress data using EAHD algorithm.
        Placeholder: This function should implement EAHD compression.
        Currently, it returns the data uncompressed with a warning.
        """
        logging.warning("EAHD COMPRESSION IS NOT IMPLEMENTED. Returning uncompressed data.")
        # A real implementation would go here.
        # For now, we simulate by returning original data.
        # If you had a real compressor, it might also return None or raise on error.
        
        # To make it slightly more realistic for testing import logic,
        # let's pretend it compresses and adds the header if it were successful.
        # This is NOT real compression.
        # header = b"\xfb\x10" # EAHD magic
        # size_bytes = len(data).to_bytes(3, 'big')
        # return header + size_bytes + data # This is a FAKE compressed structure for testing size logic
        return data # Keep it simple: return uncompressed until real one is available

class FifaBigFile:
    def __init__(self, filename):
        self.filename = filename
        self.entries: List[FileEntry] = []
        self._load()

    def _load(self):
        try:
            with open(self.filename, 'rb') as f:
                self.data_content = bytearray(f.read()) # Store raw content of the .big file
        except FileNotFoundError:
            logging.error(f"BIG file not found: {self.filename}")
            raise
        
        reader = BinaryReader(self.data_content)
        try:
            magic = bytes(self.data_content[:4])
            if magic not in (b'BIGF', b'BIG4'):
                raise ValueError(f"Invalid BIG file magic: {magic}")
            reader.skip(4)  # Skip magic

            total_data_size_in_header = reader.read_int(4, False) # Little Endian
            num_entries = reader.read_int(4, True) # Big Endian
            header_block_size = reader.read_int(4, True) # Big Endian (often the offset of the first file)
        except ValueError as e:
            logging.error(f"Error reading BIG file header: {e}")
            raise

        current_type_tag = "DAT" # Default type tag
        for _ in range(num_entries):
            try:
                entry_offset = reader.read_int(4, True) # Big Endian
                entry_raw_size = reader.read_int(4, True) # Big Endian
                entry_name = reader.read_string('utf-8')
            except ValueError as e:
                logging.error(f"Error reading entry in BIG file: {e}")
                continue # Skip malformed entry

            if entry_raw_size == 0 and entry_name in {"sg1", "sg2"}:
                current_type_tag = {"sg1": "DDS", "sg2": "APT"}[entry_name]
                self.entries.append(FileEntry(entry_offset, 0, entry_name, current_type_tag, Compression.NONE, b"", 0))
                continue

            # Boundary check for raw_data read
            if entry_offset + entry_raw_size > len(self.data_content):
                logging.warning(f"Entry '{entry_name}' raw data extends beyond EOF. Clamping size.")
                clamped_raw_size = len(self.data_content) - entry_offset
                if clamped_raw_size < 0: clamped_raw_size = 0 # Should not happen if offset is valid
                raw_data = bytes(self.data_content[entry_offset : entry_offset + clamped_raw_size])
            else:
                raw_data = bytes(self.data_content[entry_offset : entry_offset + entry_raw_size])

            compression_type = Decompressor.detect_compression(raw_data)
            decompressed_data = Decompressor.decompress_eahd(raw_data) if compression_type == Compression.EAHD else raw_data
            
            # file_type determination could be more sophisticated here if needed
            # For now, it's based on current_type_tag or could inspect decompressed_data magic
            determined_file_type = current_type_tag 
            if decompressed_data[:4] == b'DDS ':
                determined_file_type = "DDS"
            # Add more type detections if necessary

            self.entries.append(FileEntry(offset=entry_offset, 
                                           size=len(decompressed_data), 
                                           name=entry_name, 
                                           file_type=determined_file_type, 
                                           compression=compression_type, 
                                           data=decompressed_data,
                                           raw_size=entry_raw_size)) # Store raw_size

    def list_files(self) -> List[str]: # Type hint for return
        return [entry.name for entry in self.entries if entry.size > 0]

    # detect_file_type and export_file methods are not used by the main GUI flow,
    # export_selected_file handles exports. These could be removed if truly unused.
    # For now, keeping them as they might be utility.

def read_internal_name(file_path_to_read: str) -> str | None: # Python 3.10+ union type
    if not file_path_to_read or not os.path.exists(file_path_to_read):
        return None
    try:
        with open(file_path_to_read, 'rb') as file:
            file_content = file.read()
            # Optimization: Search for numbers directly in bytes if possible,
            # or decode smaller chunks if file is huge.
            # For typical BIG files, full decode is okay.
            decoded_text = file_content.decode('utf-8', errors='ignore')
            
            possible_internal_names = ["15002", "2002", "3002", "4002", "5002", "6002", "8002"]

            for internal_name_str in possible_internal_names:
                if internal_name_str in decoded_text:
                    return internal_name_str
            return None
    except Exception as e:
        messagebox.showerror("Error", f"Failed to read internal name: {e}")
        logging.error(f"Failed to read internal name from {file_path_to_read}: {e}")
        return None

def open_file():
    global file_path, current_image, current_image_index
    file_path_temp = filedialog.askopenfilename(filetypes=[("FIFA Big Files", "*.big")])
    
    if file_path_temp:
        file_path = file_path_temp
        current_image_index = 0
        update_status(f"File Loaded: {os.path.basename(file_path)}", "blue")
        add_internal_name() # This handles UI updates and first texture display

        if not internal_name_label.cget("text").startswith("Internal Name: Not Loaded"):
            # Preview reset is largely handled by extract_and_display_texture
            # but ensure a clean state if internal name processing was successful.
            preview_canvas.delete("all")
            current_image = None # Reset PIL image store
            texture_label.config(text="")
            image_dimensions_label.config(text="")
            extract_and_display_texture() # Display first texture of the new file
        else:
            # If internal name failed, clear preview as well
            preview_canvas.delete("all")
            current_image = None
            texture_label.config(text="Load a .big file")
            image_dimensions_label.config(text="")


current_image_index = 0
image_files = [str(i) for i in range(1, 81)] # Texture names "1" through "80"

def extract_and_display_texture() -> bool: # Return bool for success/failure
    global file_path, preview_canvas, current_image, current_image_index, image_dimensions_label, preview_bg_color_is_white

    if not file_path:
        preview_canvas.delete("all") # Clear canvas if no file
        texture_label.config(text="No file loaded")
        image_dimensions_label.config(text="")
        current_image = None
        return False

    try:
        # Re-read the BIG file content for the texture
        # This is somewhat inefficient if FifaBigFile instance could be cached,
        # but ensures fresh data if file was externally modified (unlikely during app use)
        # or if import modified it.
        big_file_obj = FifaBigFile(file_path) # This re-parses the whole BIG file

        if not image_files or not (0 <= current_image_index < len(image_files)):
            logging.warning("Invalid image index or image_files list empty.")
            return False
            
        image_file_to_find = image_files[current_image_index]
        
        found_entry = None
        for entry in big_file_obj.entries:
            if entry.name == image_file_to_find:
                found_entry = entry
                break
        
        if not found_entry:
            preview_canvas.delete("all")
            texture_label.config(text=f"{image_file_to_find}.dds (Not Found)")
            image_dimensions_label.config(text="")
            current_image = None
            return False

        if found_entry.size == 0 or not found_entry.data: # No data to display
            preview_canvas.delete("all")
            texture_label.config(text=f"{image_file_to_find}.dds (No Data)")
            image_dimensions_label.config(text="")
            current_image = None
            return False

        dds_data = found_entry.data
        
        if len(dds_data) < 128 or dds_data[:4] != b'DDS ': # Basic DDS validation
            preview_canvas.delete("all")
            texture_label.config(text=f"{image_file_to_find}.dds (Invalid DDS)")
            image_dimensions_label.config(text="")
            current_image = None
            return False

        with tempfile.NamedTemporaryFile(delete=False, suffix=".dds") as temp_dds_file:
            temp_dds_path = temp_dds_file.name
            temp_dds_file.write(dds_data)

        try:
            pil_image = Image.open(temp_dds_path)
            original_width, original_height = pil_image.width, pil_image.height
            
            bg_color_tuple = (255, 255, 255, 255) if preview_bg_color_is_white else (0, 0, 0, 255)

            pil_image_rgba = pil_image.convert('RGBA') if pil_image.mode != 'RGBA' else pil_image
            
            background = Image.new('RGBA', pil_image_rgba.size, bg_color_tuple)
            combined_pil_image = Image.alpha_composite(background, pil_image_rgba)
            
            current_image = combined_pil_image.copy() # Store this for zoom/pan (already composited)

            # Scale image to fit canvas while maintaining aspect ratio
            canvas_width = preview_canvas.winfo_width()
            canvas_height = preview_canvas.winfo_height()
            if canvas_width <= 1 or canvas_height <= 1: # Canvas not ready
                canvas_width, canvas_height = 580, 150 # Fallback to default if not drawn

            img_display_width, img_display_height = combined_pil_image.width, combined_pil_image.height
            
            ratio = min(canvas_width / img_display_width, canvas_height / img_display_height)
            if ratio < 1.0: # Only downscale, don't upscale
                display_width_final = int(img_display_width * ratio)
                display_height_final = int(img_display_height * ratio)
                display_image_tk = combined_pil_image.resize((display_width_final, display_height_final), Image.LANCZOS)
            else:
                display_image_tk = combined_pil_image # Use as is if it fits or is smaller
            
            img_tk = ImageTk.PhotoImage(display_image_tk)

            preview_canvas.delete("all")
            # Draw image centered on canvas
            preview_canvas.create_image(canvas_width // 2, canvas_height // 2, anchor=tk.CENTER, image=img_tk, tags="image_on_canvas")
            preview_canvas.image_ref = img_tk # Keep reference
            
            texture_label.config(text=f"{image_file_to_find}.dds")
            image_dimensions_label.config(text=f"{original_width}x{original_height}")
            global zoom_level
            zoom_level = 1.0 # Reset zoom for new image

            return True
        except Exception as e:
            logging.error(f"Failed to process/display DDS image '{image_file_to_find}': {e}")
            preview_canvas.delete("all")
            texture_label.config(text=f"{image_file_to_find}.dds (Display Error)")
            current_image = None
            return False
        finally:
            if 'temp_dds_path' in locals() and os.path.exists(temp_dds_path):
                os.remove(temp_dds_path)
    except FileNotFoundError:
        # This case should ideally be handled by the initial file_path check
        logging.warning(f"extract_and_display_texture: File not found {file_path}")
        return False
    except ValueError as e: # Handles issues from FifaBigFile parsing
        logging.error(f"ValueError during texture extraction (likely BIG file format issue): {e}")
        messagebox.showerror("File Error", f"Could not parse BIG file: {e}")
        preview_canvas.delete("all")
        texture_label.config(text="Error parsing BIG file")
        current_image = None
        return False
    except Exception as e:
        logging.error(f"An error occurred while extracting texture: {e}", exc_info=True)
        preview_canvas.delete("all")
        texture_label.config(text="Error loading texture")
        current_image = None
        return False


zoom_level = 1.0
drag_data = {"x": 0, "y": 0, "item": None}

def zoom_image(event):
    global zoom_level, current_image, preview_canvas

    if current_image is None: return # No base image to zoom

    factor = 1.1 if event.delta > 0 else (1 / 1.1)
    new_zoom_level = zoom_level * factor
    new_zoom_level = max(0.1, min(new_zoom_level, 5.0)) # Clamp zoom

    if abs(new_zoom_level - zoom_level) < 0.001 and new_zoom_level != 1.0 : # Avoid tiny changes if already at limit
        if (new_zoom_level == 0.1 and factor < 1) or \
           (new_zoom_level == 5.0 and factor > 1) :
            return

    zoom_level = new_zoom_level
    
    new_width = int(current_image.width * zoom_level)
    new_height = int(current_image.height * zoom_level)
    
    if new_width <= 0 or new_height <= 0: return

    try:
        # current_image is the PIL Image after alpha compositing with background
        resized_image_pil = current_image.resize((new_width, new_height), Image.LANCZOS)
        img_tk_zoomed = ImageTk.PhotoImage(resized_image_pil)

        preview_canvas.delete("all") # Clear previous
        # Center the zoomed image on the canvas
        canvas_width = preview_canvas.winfo_width()
        canvas_height = preview_canvas.winfo_height()
        preview_canvas.create_image(canvas_width // 2, canvas_height // 2, anchor=tk.CENTER, image=img_tk_zoomed, tags="image_on_canvas")
        preview_canvas.image_ref = img_tk_zoomed
    except Exception as e:
        logging.error(f"Error during zoom: {e}")


def start_drag(event):
    global drag_data
    # Find the image item on the canvas using its tag
    items = preview_canvas.find_withtag("image_on_canvas")
    if items:
        drag_data["item"] = items[0]
        drag_data["x"] = event.x
        drag_data["y"] = event.y
    else:
        drag_data["item"] = None

def on_drag(event):
    global drag_data
    if drag_data["item"] is not None:
        dx = event.x - drag_data["x"]
        dy = event.y - drag_data["y"]
        preview_canvas.move(drag_data["item"], dx, dy)
        drag_data["x"] = event.x
        drag_data["y"] = event.y

def load_current_values():
    global file_path, previous_file_path, previous_offsets_values, previous_color_values
    if not file_path: return
    if not hasattr(root, 'offsets_vars') or not hasattr(root, 'color_vars'): return

    try:
        with open(file_path, 'rb') as file:
            for offset_tuple, var_obj in root.offsets_vars.items():
                if offset_tuple: # Should always be true if keys are valid
                    try:
                        file.seek(offset_tuple[0]) # Read from the first offset in list for display
                        data_bytes = file.read(4)
                        value_float = struct.unpack('<f', data_bytes)[0]
                        var_obj.set(f"{value_float:.2f}") # Display with precision
                        previous_offsets_values[offset_tuple] = var_obj.get() # Store the string representation
                    except struct.error:
                        logging.warning(f"Struct error reading float at offset {offset_tuple[0]}. Data: {data_bytes.hex()}")
                        var_obj.set("ERR")
                    except Exception as e:
                        logging.error(f"Error reading offset {offset_tuple}: {e}")
                        var_obj.set("ERR")
            
            for offset_tuple, var_obj in root.color_vars.items():
                if offset_tuple:
                    try:
                        file.seek(offset_tuple[0])
                        data_bytes = file.read(4) # Expect BGRA
                        # Convert BGR to #RRGGBB hex for display
                        color_code_hex = f'#{data_bytes[2]:02X}{data_bytes[1]:02X}{data_bytes[0]:02X}'
                        var_obj.set(color_code_hex)
                        if offset_tuple in root.color_previews:
                             root.color_previews[offset_tuple].config(bg=color_code_hex)
                        previous_color_values[offset_tuple] = color_code_hex
                    except struct.error:
                        logging.warning(f"Struct error reading color at offset {offset_tuple[0]}. Data: {data_bytes.hex()}")
                        var_obj.set("#ERR")
                    except Exception as e:
                        logging.error(f"Error reading color offset {offset_tuple}: {e}")
                        var_obj.set("#ERR")
    except FileNotFoundError:
        messagebox.showerror("Error", f"File not found: {file_path}")
        logging.error(f"File not found during load_current_values: {file_path}")
    except Exception as e:
        messagebox.showerror("Error", f"Failed to read values from file: {e}")
        logging.error(f"Failed to read values from {file_path}: {e}")


def add_internal_name():
    global file_path, previous_file_path, previous_offsets_values, previous_color_values, offsets, colors
    if not file_path:
        internal_name_label.config(text="Internal Name: Not Loaded")
        clear_editor_widgets()
        return

    internal_name_str = read_internal_name(file_path)
    if internal_name_str:
        internal_name_label.config(text=f"Internal Name: {internal_name_str}")
        
        if internal_name_str in offsets_data:
            offsets_config = offsets_data[internal_name_str].get("offsets", {})
            colors_config = offsets_data[internal_name_str].get("colors", {})
            
            # Preserve JSON order for offsets and colors by directly using items()
            offsets = {k: [int(v_hex, 16) for v_hex in (v_list if isinstance(v_list, list) else [v_list])] 
                       for k, v_list in offsets_config.items()}
            colors = {k: [int(v_hex, 16) for v_hex in (v_list if isinstance(v_list, list) else [v_list])] 
                      for k, v_list in colors_config.items()}
            
            recreate_widgets() # Defines root.offsets_vars, root.color_vars etc.
            load_current_values()

            previous_file_path = file_path
            previous_offsets_values = {k: v.get() for k, v in root.offsets_vars.items()}
            previous_color_values = {k: v.get() for k, v in root.color_vars.items()}
            # extract_and_display_texture() # Called after open_file finishes this chain

        else:
            messagebox.showerror("Config Error", f"Offsets for internal name '{internal_name_str}' not found in offsets.json.")
            internal_name_label.config(text=f"Internal Name: {internal_name_str} (No Config)")
            clear_editor_widgets()
            # extract_and_display_texture() # Still try to show texture even if no offsets
    else:
        messagebox.showerror("Detection Error", "No internal name detected. Try another file or check offsets.json.")
        if previous_file_path:
            # Attempt to revert to the last valid state
            file_path = previous_file_path # Revert file_path global
            add_internal_name() # Recursively call to reload previous config
            update_status(f"Reverted to: {os.path.basename(file_path)}", "orange")
        else:
            update_status("No valid file to revert to.", "red")
            internal_name_label.config(text="Internal Name: Detection Failed")
            clear_editor_widgets()
            preview_canvas.delete("all")
            current_image = None
            texture_label.config(text="")
            image_dimensions_label.config(text="")

def clear_editor_widgets():
    for frame in [positions_frame, sizes_frame, colors_frame]:
        for widget in frame.winfo_children():
            widget.destroy()
    # Clear root-level stores for these widgets
    for attr_name in ['offsets_vars', 'offsets_values', 'color_vars', 'color_values', 'color_previews']:
        if hasattr(root, attr_name):
            getattr(root, attr_name).clear() # Clear the dictionaries

def recreate_widgets():
    clear_editor_widgets() # Clear existing before recreating

    global offsets, colors # These module globals are set by add_internal_name

    # Initialize dictionaries on root for widget variables and their values
    # Use tuple(original_list_from_json) as key to preserve order from JSON for lookups
    root.offsets_vars = {tuple(v_list): tk.StringVar() for v_list in offsets.values()}
    root.offsets_values = {tuple(v_list): "0.0" for v_list in offsets.values()}
    root.color_vars = {tuple(v_list): tk.StringVar(value='#000000') for v_list in colors.values()}
    root.color_values = {tuple(v_list): "#000000" for v_list in colors.values()}
    root.color_previews = {}

    row_p = 0
    # Iterate directly on offsets.items() to preserve JSON order
    for label_text, offset_val_list in offsets.items():
        key_tuple = tuple(offset_val_list) # Key used for var/value dicts

        if "Size" not in label_text: # Heuristic for position vs size
            col = 0 if "X" in label_text or "Width" in label_text else 4
            tk.Label(positions_frame, text=label_text).grid(row=row_p, column=col, padx=10, pady=5, sticky="w")
            entry = tk.Entry(positions_frame, textvariable=root.offsets_vars[key_tuple], width=10)
            entry.grid(row=row_p, column=col+1, padx=10, pady=5)
            entry.bind("<KeyRelease>", lambda e, kt=key_tuple, var=root.offsets_vars[key_tuple]: update_value(kt, var))
            entry.bind('<KeyPress-Up>', lambda e, var=root.offsets_vars[key_tuple]: increment_value(e, var))
            entry.bind('<KeyPress-Down>', lambda e, var=root.offsets_vars[key_tuple]: increment_value(e, var))
            if col == 4 or "Y" in label_text or "Height" in label_text :
                 row_p += 1
    row_s = 0
    for label_text, offset_val_list in offsets.items():
        key_tuple = tuple(offset_val_list)
        if "Size" in label_text:
            tk.Label(sizes_frame, text=label_text).grid(row=row_s, column=0, padx=10, pady=5, sticky="w")
            entry = tk.Entry(sizes_frame, textvariable=root.offsets_vars[key_tuple], width=10)
            entry.grid(row=row_s, column=1, padx=10, pady=5)
            entry.bind("<KeyRelease>", lambda e, kt=key_tuple, var=root.offsets_vars[key_tuple]: update_value(kt, var))
            entry.bind('<KeyPress-Up>', lambda e, var=root.offsets_vars[key_tuple]: increment_value(e, var))
            entry.bind('<KeyPress-Down>', lambda e, var=root.offsets_vars[key_tuple]: increment_value(e, var))
            row_s += 1

    row_c = 0
    for label_text, offset_val_list in colors.items():
        key_tuple = tuple(offset_val_list)
        tk.Label(colors_frame, text=label_text).grid(row=row_c, column=0, padx=10, pady=5, sticky="w")
        entry = tk.Entry(colors_frame, textvariable=root.color_vars[key_tuple], width=10)
        entry.grid(row=row_c, column=1, padx=10, pady=5)
        entry.bind('<KeyPress>', lambda e, var=root.color_vars[key_tuple]: restrict_color_entry(e, var))
        entry.bind('<KeyRelease>', lambda e, kt=key_tuple, var=root.color_vars[key_tuple]: update_color_preview_from_entry(kt, var))
        
        color_preview_label = tk.Label(colors_frame, bg=root.color_values[key_tuple], width=3, height=1, relief="sunken")
        color_preview_label.grid(row=row_c, column=2, padx=10, pady=5)
        color_preview_label.bind("<Button-1>", lambda e, kt=key_tuple, var=root.color_vars[key_tuple]: choose_color(kt, var))
        root.color_previews[key_tuple] = color_preview_label
        row_c += 1

def format_filesize(size_bytes: int) -> str:
    """Converts a size in bytes to a human-readable string (KB or MB)."""
    if size_bytes < 1024:
        return f"{size_bytes} bytes"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.2f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.2f} MB"

def save_file():
    global file_path
    if not file_path:
        messagebox.showerror("Error", "No file loaded.")
        return
    if not hasattr(root, 'offsets_vars') or not hasattr(root, 'color_vars'):
        messagebox.showerror("Error", "Editor data not initialized.")
        return

    try:
        with open(file_path, 'r+b') as file: # Open in read-write binary
            for offset_tuple_key, var_obj in root.offsets_vars.items():
                value_str = var_obj.get()
                try:
                    value_float = float(value_str)
                    packed_value = struct.pack('<f', value_float)
                    for single_offset_addr in offset_tuple_key:
                        file.seek(single_offset_addr)
                        file.write(packed_value)
                except ValueError:
                    messagebox.showerror("Save Error", f"Invalid float value '{value_str}' for {offset_tuple_key}.")
                    return
                except Exception as e_write:
                    messagebox.showerror("Save Error", f"Failed writing to offset {single_offset_addr} in {offset_tuple_key}: {e_write}")
                    return

            for offset_tuple_key, var_obj in root.color_vars.items():
                color_code_hex = var_obj.get()
                if not (len(color_code_hex) == 7 and color_code_hex.startswith('#')):
                    messagebox.showerror("Save Error", f"Invalid color format '{color_code_hex}' for {offset_tuple_key}. Expected #RRGGBB.")
                    return
                try:
                    r_val = int(color_code_hex[1:3], 16)
                    g_val = int(color_code_hex[3:5], 16)
                    b_val = int(color_code_hex[5:7], 16)
                    # Assuming BGRA format for writing, with fixed Alpha FF
                    color_bytes_bgra = bytes([b_val, g_val, r_val, 0xFF])
                    for single_offset_addr in offset_tuple_key:
                        file.seek(single_offset_addr)
                        file.write(color_bytes_bgra)
                except ValueError:
                    messagebox.showerror("Save Error", f"Invalid color hex in '{color_code_hex}' for {offset_tuple_key}.")
                    return
                except Exception as e_write_color:
                    messagebox.showerror("Save Error", f"Failed writing color to offset {single_offset_addr} in {offset_tuple_key}: {e_write_color}")
                    return
        update_status("File saved successfully.", "green")
    except Exception as e_file_open:
        messagebox.showerror("Save Error", f"Failed to open/save file: {e_file_open}")

def update_value(offset_key_tuple, string_var):
    try:
        # Validate if it's a float, but keep as string in offsets_values for consistency with get()
        float(string_var.get()) 
        if hasattr(root, 'offsets_values') and offset_key_tuple in root.offsets_values:
            root.offsets_values[offset_key_tuple] = string_var.get()
            update_status("Value Updated!", "blue") # Less alarming color
    except ValueError:
        update_status("Invalid float value entered", "red")

def increment_value(event, string_var):
    try:
        current_val_str = string_var.get()
        if not current_val_str or current_val_str == "ERR": current_val_str = "0.0"
        value_float = float(current_val_str)
        
        increment_amt = 0.1 if event.state & 0x0001 else 1.0 # Shift for smaller, Ctrl for larger? Finer control
        if event.state & 0x0004: # Ctrl key
            increment_amt = 0.01

        if event.keysym == 'Up':
            value_float += increment_amt
        elif event.keysym == 'Down':
            value_float -= increment_amt
        
        # Format to a reasonable number of decimal places
        string_var.set(f"{value_float:.4f}") 
        if hasattr(root, 'offsets_vars'): # Find key and update internal store
            for key, s_var_lookup in root.offsets_vars.items():
                if s_var_lookup == string_var:
                    update_value(key, string_var)
                    break
    except ValueError:
        update_status("Invalid value for increment", "red")

def update_color_preview_from_entry(offset_key_tuple, string_var):
    color_code = string_var.get()
    if len(color_code) == 7 and color_code.startswith("#"):
        try:
            int(color_code[1:], 16) # Validate hex
            if hasattr(root, 'color_previews') and offset_key_tuple in root.color_previews:
                root.color_previews[offset_key_tuple].config(bg=color_code)
            if hasattr(root, 'color_values'):
                root.color_values[offset_key_tuple] = color_code
            update_status("Color Preview Updated", "blue")
        except ValueError:
            update_status("Invalid hex color", "red")
    elif len(color_code) > 0 and not color_code.startswith("#"): # Auto-prepend # if missing and started typing
        if all(c in "0123456789abcdefABCDEF" for c in color_code) and len(color_code) <= 6:
            string_var.set("#" + color_code)
            update_color_preview_from_entry(offset_key_tuple, string_var) # Recurse once
        else:
             update_status("Color must be hex, start with #", "orange")


def update_color_preview(offset_key_tuple, color_code):
    if hasattr(root, 'color_previews') and offset_key_tuple in root.color_previews:
        try:
            root.color_previews[offset_key_tuple].config(bg=color_code)
        except tk.TclError:
            update_status(f"Invalid color code for preview: {color_code}", "red")


def choose_color(offset_key_tuple, string_var):
    current_color_hex = string_var.get()
    if not (current_color_hex.startswith("#") and len(current_color_hex) == 7) :
         current_color_hex = "#000000"
    
    new_color_info = colorchooser.askcolor(initialcolor=current_color_hex)
    if new_color_info and new_color_info[1]:  # [1] is the hex string
        chosen_hex_color = new_color_info[1]
        string_var.set(chosen_hex_color)
        update_color_preview(offset_key_tuple, chosen_hex_color)
        if hasattr(root, 'color_values'):
            root.color_values[offset_key_tuple] = chosen_hex_color
        update_status("Color Chosen", "green")

def update_status(message, color_fg):
    status_label.config(text=message, fg=color_fg)

def about():
    about_window = tk.Toplevel(root)
    about_window.title("About")
    about_window.geometry("420x270")
    about_window.resizable(False, False)
    bold_font = ("Helvetica", 12, "bold")
    tk.Label(about_window, text="FLP Scoreboard Editor 25 By FIFA Legacy Project.", pady=10, font=bold_font).pack()
    tk.Label(about_window, text="Version 1.0 [Build 09 May 2025]", pady=10).pack() # Date Updated
    tk.Label(about_window, text="© 2025 FIFA Legacy Project. All Rights Reserved.", pady=10).pack()
    tk.Label(about_window, text="Designed & Developed By Emran_Ahm3d.", pady=10).pack()
    tk.Label(about_window, text="Special Thanks to Riesscar, KO, MCK and Marconis for the Research.", pady=10).pack()
    tk.Label(about_window, text="Discord: @emran_ahm3d", pady=10).pack()

def show_documentation():
    webbrowser.open("https://soccergaming.com/")

def restrict_color_entry(event, string_var):
    allowed_keys = ['Left', 'Right', 'BackSpace', 'Delete', 'Tab', 'Home', 'End']
    if event.keysym in allowed_keys:
        if event.keysym == 'BackSpace' and string_var.get() == '#':
             if len(string_var.get()) <= 1 : return 'break' # Prevent deleting the initial '#'
        return # Allow navigation/deletion

    current_text = string_var.get()
    char_typed = event.char

    if not current_text and char_typed != '#':
        string_var.set('#' + char_typed) # Auto-prepend '#'
        return 'break' 
    if current_text == '#' and char_typed == '#': # Prevent '##'
        return 'break'

    if len(current_text) >= 7 and not entry_has_selection(event.widget):
        return 'break' # Limit length

    if current_text.startswith('#'): # Only allow hex chars after #
        if not char_typed.lower() in '0123456789abcdef':
            return 'break'
            
def entry_has_selection(entry_widget) -> bool:
    try:
        return entry_widget.selection_present()
    except tk.TclError:
        return False

def exit_app():
    if messagebox.askyesno("Exit", "Are you sure you want to exit?"):
        root.destroy()

def import_texture():
    global file_path, current_image_index, image_files, current_image, preview_bg_color_is_white

    if not file_path:
        messagebox.showerror("Error", "No file loaded.")
        return

    try:
        big_file_obj = FifaBigFile(file_path) # Parse once for this operation
    except Exception as e:
        messagebox.showerror("Error", f"Failed to read BIG file: {e}")
        return

    if not image_files or not (0 <= current_image_index < len(image_files)):
        messagebox.showerror("Error", "No valid texture selected for import.")
        return
    
    file_name_to_replace = image_files[current_image_index]
    
    new_texture_path = filedialog.askopenfilename(
        title=f"Import texture for {file_name_to_replace}.dds",
        filetypes=[("DDS Files", "*.dds"), ("PNG Files", "*.png")]
    )
    if not new_texture_path: return

    original_entry_obj = next((entry for entry in big_file_obj.entries if entry.name == file_name_to_replace), None)
    
    if original_entry_obj is None:
        messagebox.showerror("Error", f"File '{file_name_to_replace}' not found in the BIG archive structure.")
        return
    
    # original_entry_obj.raw_size is the size of (possibly compressed) data in BIG file
    # original_entry_obj.offset is where it starts
    # original_entry_obj.compression tells if it was EAHD

    new_data_uncompressed = None
    temp_dds_for_import_path = None

    try:
        if new_texture_path.lower().endswith(".png"):
            with Image.open(new_texture_path) as pil_img:
                pil_img_rgba = pil_img.convert("RGBA")
            with tempfile.NamedTemporaryFile(delete=False, suffix=".dds") as temp_dds_f:
                temp_dds_for_import_path = temp_dds_f.name
                pil_img_rgba.save(temp_dds_for_import_path, "DDS") # Default DDS format (often DXT5 with alpha)
            with open(temp_dds_for_import_path, 'rb') as f_dds_read:
                new_data_uncompressed = f_dds_read.read()
        elif new_texture_path.lower().endswith(".dds"):
            with open(new_texture_path, 'rb') as new_f:
                new_data_uncompressed = new_f.read()
        else:
            messagebox.showerror("Error", "Unsupported file type. Select DDS or PNG.")
            return

        if not new_data_uncompressed:
            messagebox.showerror("Error", "Failed to read new texture data.")
            return

        data_to_write_in_big = new_data_uncompressed
        compression_applied_msg = ""

        if original_entry_obj.compression == Compression.EAHD:
            logging.info(f"Original texture '{file_name_to_replace}' was EAHD. Attempting to compress new texture.")
            # data_to_write_in_big = Decompressor.compress_eahd(new_data_uncompressed) # This should be Compressor
            data_to_write_in_big = Compressor.compress_eahd(new_data_uncompressed) # Use placeholder
            if data_to_write_in_big is new_data_uncompressed: # Check if compression was real or placeholder
                 compression_applied_msg = "(EAHD compression placeholder used; data uncompressed)"
            else:
                 compression_applied_msg = "(EAHD compression attempted)"


        # Size check using the data that will actually be written
        if original_entry_obj.raw_size > 0 and len(data_to_write_in_big) > original_entry_obj.raw_size:
            msg = (f"New file ({format_filesize(len(data_to_write_in_big))}) is larger than the "
                   f"original allocated space ({format_filesize(original_entry_obj.raw_size)}) "
                   f"for '{file_name_to_replace}'. Import aborted. {compression_applied_msg}")
            messagebox.showerror("Size Error", msg)
            return
        
        # Write to the BIG file
        with open(file_path, 'r+b') as f_big_write:
            f_big_write.seek(original_entry_obj.offset)
            f_big_write.write(data_to_write_in_big)
            # If new data is smaller, pad with nulls up to original raw_size
            if original_entry_obj.raw_size > 0 and len(data_to_write_in_big) < original_entry_obj.raw_size:
                padding_size = original_entry_obj.raw_size - len(data_to_write_in_big)
                f_big_write.write(b'\x00' * padding_size)
        
        success_msg = (f"Imported '{os.path.basename(new_texture_path)}' as '{file_name_to_replace}.dds'.\n"
                       f"Original raw slot: {format_filesize(original_entry_obj.raw_size)}, "
                       f"New data size: {format_filesize(len(data_to_write_in_big))}. {compression_applied_msg}")
        messagebox.showinfo("Success", success_msg)

        # Refresh preview with the newly imported (uncompressed version for display)
        # The `new_data_uncompressed` is what we want to display.
        display_data_for_preview = new_data_uncompressed # Always show the uncompressed form
        temp_preview_dds_path = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".dds") as temp_prev_f:
                temp_preview_dds_path = temp_prev_f.name
                temp_prev_f.write(display_data_for_preview)

            with Image.open(temp_preview_dds_path) as pil_img_prev:
                original_width, original_height = pil_img_prev.width, pil_img_prev.height
                bg_tuple = (255,255,255,255) if preview_bg_color_is_white else (0,0,0,255)
                pil_img_prev_rgba = pil_img_prev.convert('RGBA') if pil_img_prev.mode != 'RGBA' else pil_img_prev
                
                bg_img = Image.new('RGBA', pil_img_prev_rgba.size, bg_tuple)
                combined_img = Image.alpha_composite(bg_img, pil_img_prev_rgba)
                current_image = combined_img.copy()

                # Scale for display
                canvas_w = preview_canvas.winfo_width()
                canvas_h = preview_canvas.winfo_height()
                ratio_prev = min(canvas_w / combined_img.width, canvas_h / combined_img.height)
                disp_w, disp_h = combined_img.width, combined_img.height
                if ratio_prev < 1.0:
                    disp_w = int(disp_w * ratio_prev)
                    disp_h = int(disp_h * ratio_prev)
                
                tk_disp_img = ImageTk.PhotoImage(combined_img.resize((disp_w, disp_h), Image.LANCZOS))
                preview_canvas.delete("all")
                preview_canvas.create_image(canvas_w//2, canvas_h//2, anchor=tk.CENTER, image=tk_disp_img, tags="image_on_canvas")
                preview_canvas.image_ref = tk_disp_img
            
            texture_label.config(text=f"{file_name_to_replace}.dds (Imported)")
            image_dimensions_label.config(text=f"{original_width}x{original_height}")
            global zoom_level
            zoom_level = 1.0
        except Exception as e_prev:
            messagebox.showerror("Preview Error", f"Failed to update preview after import: {e_prev}")
        finally:
            if temp_preview_dds_path and os.path.exists(temp_preview_dds_path):
                os.remove(temp_preview_dds_path)
    except Exception as e_import:
        messagebox.showerror("Import Error", f"Failed to import texture: {e_import}")
        logging.error(f"Import texture error: {e_import}", exc_info=True)
    finally:
        if temp_dds_for_import_path and os.path.exists(temp_dds_for_import_path):
            os.remove(temp_dds_for_import_path)


def export_selected_file():
    global file_path, current_image_index, image_files
    if not file_path: messagebox.showerror("Error", "No file loaded."); return
    if not image_files or not (0 <= current_image_index < len(image_files)):
        messagebox.showerror("Error", "No texture selected."); return

    file_name_to_export = image_files[current_image_index]
    
    try:
        big_file_obj = FifaBigFile(file_path)
    except Exception as e:
        messagebox.showerror("Error", f"Could not read BIG file for export: {e}"); return

    entry_obj_to_export = next((e for e in big_file_obj.entries if e.name == file_name_to_export), None)
    
    if not entry_obj_to_export or entry_obj_to_export.size == 0 or not entry_obj_to_export.data:
        messagebox.showerror("Error", f"File '{file_name_to_export}' not found or has no data."); return

    data_for_export = entry_obj_to_export.data # Decompressed data
    
    export_target_path = filedialog.asksaveasfilename(
        defaultextension=".png",
        filetypes=[("PNG Files", "*.png"), ("DDS Files", "*.dds")],
        initialfile=os.path.basename(file_name_to_export)
    )
    if not export_target_path: return

    try:
        if export_target_path.lower().endswith(".png"):
            with tempfile.NamedTemporaryFile(delete=False, suffix=".dds") as temp_dds_f:
                temp_dds_f.write(data_for_export)
                temp_dds_path_export = temp_dds_f.name
            try:
                with Image.open(temp_dds_path_export) as pil_img_export:
                    pil_img_export.save(export_target_path, "PNG")
                messagebox.showinfo("Success", f"Exported '{file_name_to_export}.dds' as PNG to '{export_target_path}'")
            finally:
                if os.path.exists(temp_dds_path_export): os.remove(temp_dds_path_export)
        elif export_target_path.lower().endswith(".dds"):
            with open(export_target_path, 'wb') as out_f_dds:
                out_f_dds.write(data_for_export)
            messagebox.showinfo("Success", f"Exported '{file_name_to_export}.dds' as DDS to '{export_target_path}'")
        else:
            messagebox.showerror("Error", "Unsupported export format. Choose .png or .dds.")
    except Exception as e_export:
        messagebox.showerror("Export Error", f"Failed to export file: {e_export}")


def previous_image():
    global current_image_index
    if not file_path or not image_files: return
    
    original_idx = current_image_index
    num_files = len(image_files)
    for _ in range(num_files): # Try each file at most once
        current_image_index = (current_image_index - 1 + num_files) % num_files
        if extract_and_display_texture(): return
        if current_image_index == original_idx: break # Cycled through all
    # logging.info("No other displayable textures found (previous).")


def next_image():
    global current_image_index
    if not file_path or not image_files: return

    original_idx = current_image_index
    num_files = len(image_files)
    for _ in range(num_files):
        current_image_index = (current_image_index + 1) % num_files
        if extract_and_display_texture(): return
        if current_image_index == original_idx: break
    # logging.info("No other displayable textures found (next).")

def toggle_preview_background():
    global preview_bg_color_is_white, toggle_bg_button
    preview_bg_color_is_white = not preview_bg_color_is_white
    
    # Button text is static "Toggle Alpha" as per latest script from user
    # toggle_bg_button.config(text="Set BG: Black" if preview_bg_color_is_white else "Set BG: White")
        
    if file_path: # Only refresh if a file is loaded
        extract_and_display_texture()


# --- UI Setup ---
root = tk.Tk()
root.title("FLP Scoreboard Editor 25 (v1.0)")
root.geometry("930x710")
root.resizable(False, False)

menubar = tk.Menu(root)
filemenu = tk.Menu(menubar, tearoff=0)
filemenu.add_command(label="Open", command=open_file        , accelerator="Ctrl+O")
filemenu.add_command(label="Save", command=save_file        , accelerator="Ctrl+S")
filemenu.add_separator()
filemenu.add_command(label="Exit", command=exit_app)
menubar.add_cascade(label="File", menu=filemenu)
root.bind_all("<Control-o>", lambda event: open_file())
root.bind_all("<Control-s>", lambda event: save_file())

helpmenu = tk.Menu(menubar, tearoff=0)
helpmenu.add_command(label="About", command=about)
helpmenu.add_separator()
helpmenu.add_command(label="Documentation", command=show_documentation)
menubar.add_cascade(label="Help", menu=helpmenu)
root.config(menu=menubar)

notebook = ttk.Notebook(root)
positions_frame = ttk.Frame(notebook)
sizes_frame = ttk.Frame(notebook)
colors_frame = ttk.Frame(notebook)
notebook.add(positions_frame, text="Positions")
notebook.add(sizes_frame, text="Sizes")
notebook.add(colors_frame, text="Colors")
notebook.pack(expand=1, fill="both", padx=10, pady=5)

preview_controls_frame = tk.Frame(root)
preview_controls_frame.pack(fill=tk.X, padx=10, pady=5)

left_arrow_button = ttk.Button(preview_controls_frame, text="◀", command=previous_image, width=2)
left_arrow_button.pack(side=tk.LEFT, padx=(0,5), pady=5, anchor='center')

preview_canvas = tk.Canvas(preview_controls_frame, width=580, height=150, bg="#CCCCCC", relief="solid", bd=1)
preview_canvas.pack(side=tk.LEFT, padx=5, pady=5, anchor='center')
preview_canvas.bind("<MouseWheel>", zoom_image)
preview_canvas.bind("<ButtonPress-1>", start_drag)
preview_canvas.bind("<B1-Motion>", on_drag)

right_arrow_button = ttk.Button(preview_controls_frame, text="▶", command=next_image, width=2)
right_arrow_button.pack(side=tk.LEFT, padx=5, pady=5, anchor='center')

toggle_bg_button = ttk.Button(preview_controls_frame, text="Toggle Alpha", command=toggle_preview_background, width=12)
toggle_bg_button.pack(side=tk.LEFT, padx=(10,0), pady=5, anchor='center')

texture_info_frame = tk.Frame(root)
texture_info_frame.pack(fill=tk.X, padx=10, pady=(0,5))
texture_label = tk.Label(texture_info_frame, text="No texture loaded", font=('Helvetica', 9), anchor='w')
texture_label.pack(side=tk.LEFT, padx=5)
image_dimensions_label = tk.Label(texture_info_frame, text=" ", font=('Helvetica', 10), anchor='e')
image_dimensions_label.pack(side=tk.RIGHT, padx=10)

buttons_frame = tk.Frame(root)
buttons_frame.place(relx=1.0, rely=1.0, anchor='se', x=-10, y=-85)
import_button = ttk.Button(buttons_frame, text="IMPORT", command=import_texture, width=10)
import_button.pack(pady=2)
export_button = ttk.Button(buttons_frame, text="EXPORT", command=export_selected_file, width=10)
export_button.pack(pady=2)
save_button_main = ttk.Button(buttons_frame, text="SAVE", command=save_file, width=10)
save_button_main.pack(pady=(2,0))

bottom_frame = tk.Frame(root)
bottom_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=(0,5))
status_label = tk.Label(bottom_frame, text="Ready", anchor=tk.W, fg="blue", font=('Helvetica', 10))
status_label.pack(side=tk.LEFT, padx=0)
internal_name_label = tk.Label(bottom_frame, text="Internal Name: Not Loaded", anchor=tk.E, font=('Helvetica', 10))
internal_name_label.pack(side=tk.RIGHT, padx=0)

root.style = ttk.Style()
root.style.configure('TButton', font=('Helvetica', 10), padding=3) # General TButton
root.style.configure('Large.TButton', font=('Helvetica', 12), padding=5) # For main action buttons if needed elsewhere
# Apply 'TButton' style to arrow and toggle buttons, 'Large.TButton' to Import/Export/Save
left_arrow_button.configure(style='TButton')
right_arrow_button.configure(style='TButton')
toggle_bg_button.configure(style='TButton')
import_button.configure(style='Large.TButton')
export_button.configure(style='Large.TButton')
save_button_main.configure(style='Large.TButton')


def on_map_event(event):
    # This ensures canvas dimensions are known before first draw attempt if file is preloaded
    # or immediately after open_file.
    # If file_path is set, it means open_file likely completed or is in progress.
    if file_path and not current_image: # Only if no image yet, but file is loaded
        extract_and_display_texture()

root.bind("<Map>", on_map_event, "+")

# Initialize with empty editor state
clear_editor_widgets()

root.mainloop()