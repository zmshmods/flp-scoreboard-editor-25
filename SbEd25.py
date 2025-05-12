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
    _temp_root_for_dialog = tk.Tk()
    _temp_root_for_dialog.withdraw() # Hide the temporary root window
    file_path_json = filedialog.askopenfilename(
        title="Select offsets.json file", filetypes=[("JSON files", "*.json")])
    _temp_root_for_dialog.destroy()

    if not file_path_json:
        messagebox.showerror(
            "Error", "No offsets.json selected. Application will exit.")
        exit()
    try:
        with open(file_path_json, 'r') as f:
            offsets_data = json.load(f)
    except json.JSONDecodeError:
        logging.error("Error decoding selected offsets.json.")
        messagebox.showerror(
            "Error", "Error reading selected offsets.json file. The application will be terminated.")
        exit()
    except FileNotFoundError:
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
original_loaded_colors = {} # Will store hex for regular, "WHITE"/"BLACK" for special

preview_bg_color_is_white = True
current_image_index = 0
image_files = [str(i) for i in range(1, 81)]

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

# (tag, text, gui_x, gui_y, design_font_size, font_size_offset_label, color_label_or_special_key, is_fixed, x_offset_label, base_game_x, y_offset_label, base_game_y)
initial_text_elements_config = [
    ("text_hom", "HOM", 188, 22, 24, "Home Team Name Size", "Home Team Name Color",
     False, "Home Team Name X", 241, "Home Team Name Y", 17),
    ("text_awa", "AWA", 370, 22, 24, "Away Team Name Size", "Away Team Name Color",
     False, "Away Team Name X", 425, "Away Team Name Y", 17),
    ("text_score1", "1", 280, 22, 24, "Home Score Size", "Home Score Color",
     False, "Home Score X", 352, "Home Score Y", 17),
    ("text_score2", "2", 325, 22, 24, "Away Score Size", "Away Score Color",
     False, "Away Score X", 395, "Away Score Y", 17),
    ("text_time_min1",  "1", 70, 23, 20, "Time Text Size", "Time Text Color",
     False, "1st Digit of Time (0--:--) X", -330, "1st Digit of Time (0--:--) Y", 2),
    ("text_time_min2",  "0", 85, 23, 20, "Time Text Size", "Time Text Color",
     False, "2nd Digit of Time (-0-:--) X", -315, "2nd Digit of Time (-0-:--) Y", 2),
    ("text_time_min3",  "5", 100, 23, 20, "Time Text Size", "Time Text Color",
     False, "3rd Digit of Time (--0:--) X", -300, "3rd Digit of Time (--0:--) Y", 2),
    ("text_time_colon", ":", 116, 20, 20, "Time Text Size", "Time Text Color",
     False, "Colon Seperator of Time (---:--) X", -290, "Colon Seperator of Time (---:--) Y", -2),
    ("text_time_sec1",  "3", 125, 23, 20, "Time Text Size", "Time Text Color",
     False, "4th Digit of Time (---:0-) X", -280, "4th Digit of Time (---:0-) Y", 2),
    ("text_time_sec2",  "8", 140, 23, 20, "Time Text Size", "Time Text Color",
     False, "5th Digit of Time (---:-0) X", -265, "5th Digit of Time (---:-0) Y", 2),
    ("text_added_time", "+9", 120, 67, 22, "PlaceHolder", "Added Time Text Color", # Linked to the special text color
     False, "Added Time X", 130, "Added Time Y", 83),
]

SPECIAL_TEXT_COLOR_LABELS = ["Added Time Text Color"] # Labels that are text-based, not hex

predefined_image_coords: Dict[str, tuple[float, float, Optional[str], Optional[float], Optional[str], Optional[float]]] = {
    "img_10":       (5.0, 5.0, None, None, None, None),
    "img_14":       (104, 51, None, None, None, None),
    "img_30_orig":  (135, 8, "Home Color Bar X", 212, "Home Color Bar Y", 103.5),
    "img_30_dup":   (426, 8, "Away Color Bar X", 502, "Away Color Bar Y", 103.5)
}

highlighted_offset_entries = []


class EditAction:
    def __init__(self, string_var, old_value, new_value, key_tuple, entry_widget_ref, description="value change"):
        self.string_var = string_var
        self.old_value = old_value
        self.new_value = new_value
        self.key_tuple = key_tuple
        self.entry_widget_ref = entry_widget_ref
        self.description = description

    def undo(self): self.string_var.set(self.old_value)
    def redo(self): self.string_var.set(self.new_value)
    def __str__(self): return f"EditAction({self.description}: {self.old_value} -> {self.new_value})"

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

    def can_undo(self): return bool(self.undo_stack)
    def can_redo(self): return bool(self.redo_stack)

    def _apply_action_and_update_ui(self, action_to_apply: EditAction, is_undo: bool):
        logging.debug(f"Applying {'undo' if is_undo else 'redo'} for: {action_to_apply}")
        if is_undo:
            action_to_apply.undo()
        else:
            action_to_apply.redo()
        is_offset_var = False
        if hasattr(root, 'offsets_vars'):
            for key, var in root.offsets_vars.items():
                if var == action_to_apply.string_var:
                    update_value(key, action_to_apply.string_var, from_undo_redo=True)
                    is_offset_var = True
                    break
        if not is_offset_var and hasattr(root, 'color_vars'):
            # Find the JSON label for this color var to determine if it's special
            color_json_label = None
            for lbl, c_key_tuple in colors.items(): # colors maps JSON label to address tuple
                if tuple(c_key_tuple) == action_to_apply.key_tuple:
                    color_json_label = lbl
                    break
            
            if color_json_label in SPECIAL_TEXT_COLOR_LABELS:
                 # This var is for a Combobox (WHITE/BLACK)
                 handle_special_text_color_change(action_to_apply.key_tuple, action_to_apply.string_var, from_undo_redo=True)
            else:
                # This var is for a hex color Entry
                update_color_preview_from_entry(action_to_apply.key_tuple, action_to_apply.string_var, from_undo_redo=True)

        if action_to_apply.entry_widget_ref and isinstance(action_to_apply.entry_widget_ref, tk.Entry): # Or ttk.Combobox
            try:
                action_to_apply.entry_widget_ref.focus_set()
                if isinstance(action_to_apply.entry_widget_ref, tk.Entry):
                    action_to_apply.entry_widget_ref.selection_range(0, tk.END)
            except tk.TclError:
                logging.debug("TclError focusing widget during undo/redo.")
        self.update_menu_states()

    def undo(self):
        if not self.can_undo(): return
        action = self.undo_stack.pop()
        self._apply_action_and_update_ui(action, is_undo=True)
        self.redo_stack.append(action)
        self.update_menu_states()
        logging.info(f"Undone: {action}")

    def redo(self):
        if not self.can_redo(): return
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
        if hasattr(root, 'editmenu'):
            root.editmenu.entryconfig("Undo", state=tk.NORMAL if self.can_undo() else tk.DISABLED)
            root.editmenu.entryconfig("Redo", state=tk.NORMAL if self.can_redo() else tk.DISABLED)

undo_manager = UndoManager()

class Compression(Enum): NONE = "None"; EAHD = "EAHD"

@dataclass
class FileEntry:
    offset: int; size: int; name: str; file_type: str
    compression: Compression; data: bytes; raw_size: int

class BinaryReader:
    def __init__(self, data: bytearray): self.data = data; self.pos = 0
    def read_byte(self) -> int:
        if self.pos >= len(self.data): raise ValueError("EOS byte")
        v = self.data[self.pos]; self.pos += 1; return v
    def read_int(self, c: int = 4, be: bool = False) -> int:
        if self.pos + c > len(self.data): raise ValueError(f"EOS int{c}")
        chunk = self.data[self.pos:self.pos+c]; self.pos += c
        return int.from_bytes(chunk, "big" if be else "little")
    def read_string(self, enc: str, length: Optional[int] = None) -> str: # Added length param
        if length is not None:
            if self.pos + length > len(self.data):
                raise ValueError(f"Not enough data to read string of length {length}")
            b = self.data[self.pos : self.pos + length]
            self.pos += length
            return b.decode(enc, errors="ignore").rstrip('\x00') #rstrip for potential nulls if fixed length
        else: # Null-terminated
            s = self.pos
            while self.pos < len(self.data) and self.data[self.pos] != 0: self.pos += 1
            b = self.data[s:self.pos]
            if self.pos < len(self.data) and self.data[self.pos] == 0: self.pos += 1
            return b.decode(enc, errors="ignore")
    def skip(self, c: int): self.pos = min(len(self.data), self.pos + c)

class Decompressor:
    @staticmethod
    def detect_compression(data: bytes) -> Compression:
        return Compression.EAHD if len(data) >= 2 and data[:2] == b"\xfb\x10" else Compression.NONE
    @staticmethod
    def decompress_eahd(data: bytes) -> bytes:
        try:
            r = BinaryReader(bytearray(data))
            if r.read_int(2, True) != 0xFB10: return data
            total_size = r.read_int(3, True); out = bytearray(total_size); pos = 0
            while r.pos < len(r.data) and pos < total_size:
                ctrl = r.read_byte(); to_read = 0; to_copy = 0; off_val = 0
                if ctrl < 0x80:
                    a = r.read_byte(); to_read = ctrl & 0x03
                    to_copy = ((ctrl & 0x1C) >> 2)+3; off_val = ((ctrl & 0x60) << 3)+a+1
                elif ctrl < 0xC0:
                    a,b = r.read_byte(),r.read_byte(); to_read = (a >> 6)&0x03
                    to_copy = (ctrl&0x3F)+4; off_val = ((a&0x3F)<<8)+b+1
                elif ctrl < 0xE0:
                    a,b,c = r.read_byte(),r.read_byte(),r.read_byte(); to_read = ctrl&0x03
                    to_copy = ((ctrl&0x0C)<<6)+c+5; off_val = ((ctrl&0x10)<<12)+(a<<8)+b+1
                elif ctrl < 0xFC: to_read = ((ctrl&0x1F)<<2)+4
                else: to_read = ctrl&0x03
                if pos+to_read > total_size: to_read = total_size-pos
                for _ in range(to_read):
                    if r.pos>=len(r.data): break
                    out[pos]=r.read_byte(); pos+=1
                if to_copy > 0:
                    c_start = pos-off_val
                    if c_start < 0: logging.error("EAHD: Invalid copy offset."); return data
                    if pos+to_copy > total_size: to_copy = total_size-pos
                    for _ in range(to_copy):
                        if c_start >= pos: logging.error("EAHD: copy_start >= pos."); return data
                        out[pos]=out[c_start]; pos+=1; c_start+=1
            return bytes(out[:pos])
        except ValueError as e: logging.error(f"EAHD Decomp ValueError: {e}"); return data
        except Exception as e: logging.error(f"EAHD Decomp Exception: {e}", exc_info=True); return data

class Compressor:
    @staticmethod
    def compress_eahd(data: bytes) -> bytes:
        logging.warning("EAHD COMPRESSION IS NOT IMPLEMENTED. Ret uncompressed.")
        return data

class FifaBigFile:
    def __init__(self, filename):
        self.filename = filename; self.entries: List[FileEntry] = []; self._load()
    def _load(self):
        try:
            with open(self.filename, 'rb') as f: self.data_content = bytearray(f.read())
        except FileNotFoundError: logging.error(f"BIG file not found: {self.filename}"); raise
        r = BinaryReader(self.data_content)
        try:
            magic = bytes(self.data_content[:4])
            if magic not in (b'BIGF',b'BIG4'): raise ValueError(f"Invalid BIG magic: {magic}")
            r.skip(4); r.read_int(4,False); num_entries = r.read_int(4,True); r.read_int(4,True)
        except ValueError as e: logging.error(f"BIG header error: {e}"); raise
        c_type_tag = "DAT"
        for i in range(num_entries):
            try:
                entry_offset = r.read_int(4,True); entry_raw_size = r.read_int(4,True)
                entry_name = r.read_string('utf-8')
            except ValueError as e: logging.error(f"Entry read error {i}: {e}"); continue
            if entry_raw_size == 0 and entry_name in {"sg1","sg2"}:
                c_type_tag = {"sg1":"DDS","sg2":"APT"}[entry_name]
                self.entries.append(FileEntry(entry_offset,0,entry_name,c_type_tag,Compression.NONE,b"",0))
                continue
            actual_raw_size = entry_raw_size
            if entry_offset+entry_raw_size > len(self.data_content):
                actual_raw_size = len(self.data_content)-entry_offset
                if actual_raw_size < 0: actual_raw_size = 0
            raw_data = bytes(self.data_content[entry_offset : entry_offset+actual_raw_size])
            comp_type = Decompressor.detect_compression(raw_data)
            decomp_data = Decompressor.decompress_eahd(raw_data) if comp_type == Compression.EAHD else raw_data
            det_file_type = c_type_tag
            if decomp_data[:4] == b'DDS ': det_file_type = "DDS"
            self.entries.append(FileEntry(entry_offset,len(decomp_data),entry_name,det_file_type,comp_type,decomp_data,entry_raw_size))
    def list_files(self) -> List[str]: return [e.name for e in self.entries if e.size > 0]

def format_filesize(b: int) -> str:
    if b < 1024: return f"{b} bytes"
    return f"{b/1024:.2f} KB" if b < 1024*1024 else f"{b/(1024*1024):.2f} MB"

def read_internal_name(fp: str) -> Optional[str]:
    if not fp or not os.path.exists(fp): return None
    try:
        with open(fp, 'rb') as f: content = f.read(200*1024)
        text = content.decode('utf-8', errors='ignore')
        names = ["15002", "2002", "3002", "4002", "5002", "6002", "8002"]
        for n in names:
            if n in text: return n
        return None
    except Exception as e: logging.error(f"Read internal name fail: {e}"); return None

def open_file():
    global file_path, current_image_index, composite_mode_active, undo_manager
    global original_loaded_offsets, original_loaded_colors
    fp_temp = filedialog.askopenfilename(filetypes=[("FIFA Big Files", "*.big")])
    if fp_temp:
        file_path = fp_temp; current_image_index = 0
        undo_manager.clear_history(); original_loaded_offsets.clear(); original_loaded_colors.clear()
        if hasattr(root, 'asterisk_labels'):
            for al in root.asterisk_labels.values(): al.config(text="")
        file_path_label.config(text=f"File: {os.path.basename(file_path)}")
        add_internal_name()
        is_ok = internal_name_label.cget("text").startswith("Internal Name: ") and \
                not internal_name_label.cget("text").endswith("(No Config)") and \
                not internal_name_label.cget("text").endswith("(Detection Failed)")
        if composite_mode_active:
            is_comp_elig = (file_path and 0<=current_image_index<len(image_files) and image_files[current_image_index]=="10")
            if not is_comp_elig or not is_ok: toggle_composite_mode()
            else: display_composite_view()
        else:
            if is_ok: extract_and_display_texture()
            else:
                preview_canvas.delete("all"); current_image = None
                texture_label.config(text="Load .big / Invalid internal name"); image_dimensions_label.config(text="")
    elif not file_path: file_path_label.config(text="File: None")

def redraw_single_view_image():
    global current_image, preview_canvas, single_view_zoom_level, single_view_pan_offset_x, single_view_pan_offset_y
    if current_image is None: preview_canvas.delete("all"); return
    canvas_w=preview_canvas.winfo_width(); canvas_h=preview_canvas.winfo_height()
    if canvas_w<=1:canvas_w=580;canvas_h=150
    img_to_display = current_image
    zoomed_w=int(img_to_display.width*single_view_zoom_level); zoomed_h=int(img_to_display.height*single_view_zoom_level)
    if zoomed_w<=0 or zoomed_h<=0: return
    try:
        resized_img=img_to_display.resize((zoomed_w,zoomed_h),Image.LANCZOS)
        img_tk=ImageTk.PhotoImage(resized_img); preview_canvas.delete("all")
        draw_x=canvas_w/2+single_view_pan_offset_x; draw_y=canvas_h/2+single_view_pan_offset_y
        preview_canvas.create_image(draw_x,draw_y,anchor=tk.CENTER,image=img_tk,tags="image_on_canvas")
        preview_canvas.image_ref = img_tk
    except Exception as e: logging.error(f"Error redrawing single view: {e}")

def extract_and_display_texture() -> bool:
    global file_path,current_image,current_image_index,preview_bg_color_is_white,composite_mode_active
    global single_view_zoom_level,single_view_pan_offset_x,single_view_pan_offset_y
    if composite_mode_active: return False
    if not file_path:
        preview_canvas.delete("all");texture_label.config(text="No file");current_image=None;return False
    try:
        big_file=FifaBigFile(file_path)
        if not(0<=current_image_index<len(image_files)): return False
        img_name=image_files[current_image_index]
        entry=next((e for e in big_file.entries if e.name==img_name),None)
        if not entry or entry.size==0 or not entry.data or entry.file_type!="DDS" or entry.data[:4]!=b'DDS ':
            logging.info(f"Texture '{img_name}' invalid/not found."); return False
        temp_dds_path=None
        try:
            with tempfile.NamedTemporaryFile(delete=False,suffix=".dds") as tmp_f:
                tmp_f.write(entry.data);temp_dds_path=tmp_f.name
            pil_img=Image.open(temp_dds_path);w_orig,h_orig=pil_img.width,pil_img.height
            bg_color=(255,255,255,255) if preview_bg_color_is_white else (0,0,0,255)
            pil_rgba=pil_img.convert('RGBA') if pil_img.mode!='RGBA' else pil_img
            background=Image.new('RGBA',pil_rgba.size,bg_color)
            current_image=Image.alpha_composite(background,pil_rgba)
            single_view_zoom_level=1.0;single_view_pan_offset_x=0.0;single_view_pan_offset_y=0.0
            redraw_single_view_image()
            texture_label.config(text=f"{img_name}.dds");image_dimensions_label.config(text=f"{w_orig}x{h_orig}")
            return True
        except Exception as e_disp: logging.warning(f"Display DDS '{img_name}' failed: {e_disp}"); return False
        finally:
            if temp_dds_path and os.path.exists(temp_dds_path): os.remove(temp_dds_path)
    except Exception as e_outer: logging.error(f"Outer error in extract: {e_outer}",exc_info=True); return False

def zoom_image_handler(event):
    if composite_mode_active: zoom_composite_view(event)
    else: zoom_single_view(event)

def zoom_single_view(event):
    global single_view_zoom_level
    if current_image is None: return
    factor=1.1 if event.delta>0 else (1/1.1)
    new_zoom=max(0.05,min(single_view_zoom_level*factor,10.0))
    single_view_zoom_level=new_zoom; redraw_single_view_image()

def start_drag_handler(event):
    if composite_mode_active: start_drag_composite(event)
    else: start_drag_single(event)

def on_drag_handler(event):
    if composite_mode_active: on_drag_composite(event)
    else: on_drag_single(event)

def on_drag_release_handler(event):
    global drag_data,composite_mode_active
    drag_data["is_panning"]=False;drag_data["is_panning_rmb"]=False
    if composite_mode_active: clear_all_highlights()

def start_drag_single(event):
    global drag_data; drag_data["is_panning"]=True; drag_data["x"]=event.x; drag_data["y"]=event.y

def on_drag_single(event):
    global drag_data,single_view_pan_offset_x,single_view_pan_offset_y
    if not drag_data["is_panning"] or current_image is None: return
    dx=event.x-drag_data["x"]; dy=event.y-drag_data["y"]
    single_view_pan_offset_x+=dx; single_view_pan_offset_y+=dy
    drag_data["x"]=event.x; drag_data["y"]=event.y; redraw_single_view_image()

def load_current_values():
    global file_path,original_loaded_offsets,original_loaded_colors, colors # Added colors global
    if not file_path or not hasattr(root,'offsets_vars') or not hasattr(root,'color_vars'): return
    original_loaded_offsets.clear(); original_loaded_colors.clear()
    try:
        with open(file_path,'rb') as file:
            for off_tuple,var_obj in root.offsets_vars.items():
                if not off_tuple: continue
                try:
                    file.seek(off_tuple[0]);data=file.read(4);val=struct.unpack('<f',data)[0]
                    val_str=f"{val:.2f}";var_obj.set(val_str);original_loaded_offsets[off_tuple]=val_str
                    if off_tuple in root.asterisk_labels: root.asterisk_labels[off_tuple].config(text="")
                except Exception: var_obj.set("ERR")
            
            # Find the JSON label for each color offset tuple to check if it's special
            for color_label, off_tuple_list in colors.items(): # Iterate through loaded color config
                off_tuple = tuple(off_tuple_list)
                if off_tuple not in root.color_vars: continue # Should not happen if setup is correct

                var_obj = root.color_vars[off_tuple]
                try:
                    file.seek(off_tuple[0])
                    if color_label in SPECIAL_TEXT_COLOR_LABELS:
                        data_bytes = file.read(5) # Read 5 bytes for text color
                        text_color_val = data_bytes.decode('ascii', errors='ignore').strip()
                        if text_color_val in ["WHITE", "BLACK"]:
                            var_obj.set(text_color_val)
                            original_loaded_colors[off_tuple] = text_color_val
                        else:
                            var_obj.set("ERR_TXT") # Error for special text color
                            original_loaded_colors[off_tuple] = "ERR_TXT"
                        # No color swatch for combobox, but ensure asterisk is cleared
                    else: # Regular hex color
                        data_bytes = file.read(4) # BGRA
                        hex_col=f'#{data_bytes[2]:02X}{data_bytes[1]:02X}{data_bytes[0]:02X}'
                        var_obj.set(hex_col);original_loaded_colors[off_tuple]=hex_col
                        if off_tuple in root.color_previews: root.color_previews[off_tuple].config(bg=hex_col)
                    
                    if off_tuple in root.asterisk_labels: root.asterisk_labels[off_tuple].config(text="")

                except Exception as e:
                     var_obj.set("#ERR_LOAD" if color_label not in SPECIAL_TEXT_COLOR_LABELS else "ERR_LOAD_TXT")
                     logging.error(f"Error loading color/text for {color_label} at {off_tuple}: {e}")

    except Exception as e: messagebox.showerror("Error",f"Failed to read values: {e}")


def add_internal_name():
    global file_path,previous_file_path,offsets,colors,current_reference_width,current_reference_height,composite_mode_active
    if not file_path:
        internal_name_label.config(text="Internal Name: Not Loaded");clear_editor_widgets()
        current_reference_width=None;current_reference_height=None
        if composite_mode_active: toggle_composite_mode(); return
    internal_name_str = read_internal_name(file_path)
    if internal_name_str:
        internal_name_label.config(text=f"Internal Name: {internal_name_str}")
        if internal_name_str in offsets_data:
            config=offsets_data[internal_name_str]
            current_reference_width=config.get("reference_width");current_reference_height=config.get("reference_height")
            offsets={k:[int(str(v),16) for v in (vl if isinstance(vl,list) else [vl])] for k,vl in config.get("offsets",{}).items()}
            colors={k:[int(str(v),16) for v in (vl if isinstance(vl,list) else [vl])] for k,vl in config.get("colors",{}).items()}
            recreate_widgets();load_current_values();previous_file_path=file_path
        else:
            messagebox.showerror("Config Error",f"Config for '{internal_name_str}' not found.")
            internal_name_label.config(text=f"Internal Name: {internal_name_str} (No Config)")
            clear_editor_widgets();current_reference_width=None;current_reference_height=None
            if composite_mode_active: toggle_composite_mode()
    else:
        messagebox.showerror("Detection Error","No internal name detected.")
        current_reference_width=None;current_reference_height=None
        if previous_file_path and previous_file_path!=file_path:
            file_path=previous_file_path;add_internal_name()
            update_status(f"Reverted to: {os.path.basename(file_path)}","orange")
        else:
            internal_name_label.config(text="Internal Name: Detection Failed");clear_editor_widgets()
            preview_canvas.delete("all");current_image=None;texture_label.config(text="")
            image_dimensions_label.config(text="")
            if composite_mode_active: toggle_composite_mode()

def clear_editor_widgets():
    for frame in [positions_frame,sizes_frame,colors_frame]:
        for widget in frame.winfo_children(): widget.destroy()
    for attr in ['offsets_vars','color_vars','color_previews','offset_entry_widgets','asterisk_labels', 'color_comboboxes']:
        if hasattr(root,attr): getattr(root,attr).clear()

def recreate_widgets():
    clear_editor_widgets()
    global offsets,colors, SPECIAL_TEXT_COLOR_LABELS
    root.offsets_vars={tuple(v):tk.StringVar() for v in offsets.values()}
    root.color_vars={ # StringVars for all color types
        tuple(v_list): tk.StringVar(value='#000000' if lbl not in SPECIAL_TEXT_COLOR_LABELS else "WHITE") 
        for lbl, v_list in colors.items()
    }
    root.color_previews={}; root.offset_entry_widgets={}; root.asterisk_labels={}
    root.color_comboboxes = {} # To store references to comboboxes if needed

    def make_offset_update_lambda(key_tuple,var,entry_widget):
        def on_offset_update(event=None):
            old_value=original_loaded_offsets.get(key_tuple,"")
            new_value=var.get()
            is_focus_out_after_key_release=(event and event.type==tk.EventType.FocusOut and
                                          hasattr(entry_widget,'_undo_recorded_for_this_change') and
                                          entry_widget._undo_recorded_for_this_change)
            if old_value!=new_value and not is_focus_out_after_key_release:
                if not (event and event.type==tk.EventType.FocusOut):
                    action=EditAction(var,old_value,new_value,key_tuple,entry_widget,f"Offset change for {key_tuple}")
                    undo_manager.record_action(action)
                if event and event.type==tk.EventType.KeyRelease:
                    entry_widget._undo_recorded_for_this_change=True
            update_value(key_tuple,var)
            if event and event.type==tk.EventType.FocusOut:
                if hasattr(entry_widget,'_undo_recorded_for_this_change'):
                    delattr(entry_widget,'_undo_recorded_for_this_change')
        return on_offset_update

    def make_increment_lambda(key_tuple,var,entry_widget,direction):
        def on_increment(event=None):
            old_value=var.get(); entry_widget.unbind("<KeyRelease>")
            increment_value(event,var,direction); new_value=var.get()
            if old_value!=new_value:
                action=EditAction(var,old_value,new_value,key_tuple,entry_widget,f"Increment {direction}")
                undo_manager.record_action(action)
            update_value(key_tuple,var)
            entry_widget.bind("<KeyRelease>",make_offset_update_lambda(key_tuple,var,entry_widget))
        return on_increment

    row_p=0; row_s=0 
    for lbl,off_list in offsets.items():
        key_tuple=tuple(off_list)
        is_font_related_size = "Size" in lbl and ("Font" in lbl or "Text" in lbl or "Team Name" in lbl or "Score" in lbl or "Added Time" in lbl)

        target_frame = None; current_row_ref = None 
        base_col_for_entry = 1; col_for_asterisk = 2   

        if is_font_related_size: 
            target_frame = sizes_frame; current_row_ref = row_s
            tk.Label(target_frame,text=lbl).grid(row=row_s,column=0,padx=5,pady=5,sticky="w")
            entry=tk.Entry(target_frame,textvariable=root.offsets_vars[key_tuple],width=10)
            entry.grid(row=row_s,column=1,padx=0,pady=5); row_s +=1
        elif "Size" in lbl : 
            target_frame = sizes_frame; current_row_ref = row_s
            tk.Label(target_frame,text=lbl).grid(row=row_s,column=0,padx=5,pady=5,sticky="w")
            entry=tk.Entry(target_frame,textvariable=root.offsets_vars[key_tuple],width=10)
            entry.grid(row=row_s,column=1,padx=0,pady=5); row_s +=1
        elif not lbl.startswith("Image_"): 
            target_frame = positions_frame; current_row_ref = row_p
            col=0 if "X" in lbl or "Width" in lbl else 4 
            tk.Label(target_frame,text=lbl).grid(row=row_p,column=col,padx=5,pady=5,sticky="w")
            entry=tk.Entry(target_frame,textvariable=root.offsets_vars[key_tuple],width=10)
            entry.grid(row=row_p,column=col+1,padx=0,pady=5)
            base_col_for_entry = col + 1; col_for_asterisk = col+2
            if col==4 or "Y" in lbl or "Height" in lbl: row_p+=1
        else: continue 
        
        if target_frame: 
            update_lambda=make_offset_update_lambda(key_tuple,root.offsets_vars[key_tuple],entry)
            entry.bind("<KeyRelease>",update_lambda); entry.bind("<FocusOut>",update_lambda)
            entry.bind('<KeyPress-Up>',make_increment_lambda(key_tuple,root.offsets_vars[key_tuple],entry,"Up"))
            entry.bind('<KeyPress-Down>',make_increment_lambda(key_tuple,root.offsets_vars[key_tuple],entry,"Down"))
            asterisk_lbl=tk.Label(target_frame,text="",fg="red",width=1)
            asterisk_lbl.grid(row=current_row_ref,column=col_for_asterisk,padx=(0,5),pady=5,sticky="w")
            root.asterisk_labels[key_tuple]=asterisk_lbl
            root.offset_entry_widgets[key_tuple]=entry
            
    row_c=0
    for lbl,off_list in colors.items(): # colors is {"Label": [addr1, addr2]}
        key_tuple=tuple(off_list)
        tk.Label(colors_frame,text=lbl).grid(row=row_c,column=0,padx=5,pady=5,sticky="w")
        
        current_var = root.color_vars[key_tuple]

        if lbl in SPECIAL_TEXT_COLOR_LABELS:
            combo = ttk.Combobox(colors_frame, textvariable=current_var, values=["WHITE", "BLACK"], width=8, state="readonly")
            combo.grid(row=row_c, column=1, padx=0, pady=5)
            root.color_comboboxes[key_tuple] = combo # Store ref to combobox
            # No color swatch for combobox, so place asterisk directly after
            asterisk_col_idx = 2 
            
            def make_combo_change_lambda(k_t, var_obj, combo_ref):
                def on_combo_change(event=None):
                    old_val = original_loaded_colors.get(k_t, "WHITE") # Default if not found
                    new_val = var_obj.get()
                    if old_val != new_val:
                        action = EditAction(var_obj, old_val, new_val, k_t, combo_ref, f"Text color change for {lbl}")
                        undo_manager.record_action(action)
                    handle_special_text_color_change(k_t, var_obj)
                return on_combo_change
            combo.bind("<<ComboboxSelected>>", make_combo_change_lambda(key_tuple, current_var, combo))

        else: # Regular hex color entry
            entry=tk.Entry(colors_frame,textvariable=current_var,width=10)
            entry.grid(row=row_c,column=1,padx=0,pady=5)
            def make_color_update_lambda(k_t,var,entry_w): # For hex entry
                def on_color_update(event=None):
                    old_val=original_loaded_colors.get(k_t,"")
                    new_val=var.get()
                    is_focus_out_after_key=(event and event.type==tk.EventType.FocusOut and hasattr(entry_w,'_undo_recorded_for_this_change') and entry_w._undo_recorded_for_this_change)
                    if old_val!=new_val and not is_focus_out_after_key:
                        if not (event and event.type==tk.EventType.FocusOut):
                            action=EditAction(var,old_val,new_val,k_t,entry_w,f"Hex color change for {lbl}")
                            undo_manager.record_action(action)
                        if event and event.type==tk.EventType.KeyRelease: entry_w._undo_recorded_for_this_change=True
                    update_color_preview_from_entry(k_t,var)
                    if event and event.type==tk.EventType.FocusOut:
                        if hasattr(entry_w,'_undo_recorded_for_this_change'): delattr(entry_w,'_undo_recorded_for_this_change')
                return on_color_update
            color_update_lambda=make_color_update_lambda(key_tuple,current_var,entry)
            entry.bind('<KeyPress>',lambda e,v=current_var:restrict_color_entry(e,v))
            entry.bind('<KeyRelease>',color_update_lambda); entry.bind("<FocusOut>",color_update_lambda)
            
            preview_lbl=tk.Label(colors_frame,bg=current_var.get(),width=3,height=1,relief="sunken")
            preview_lbl.grid(row=row_c,column=2,padx=5,pady=5)
            def make_choose_color_lambda(k_t,var_obj,preview_widget,entry_ref):
                def on_choose_color(event=None):
                    old_color=var_obj.get(); choose_color(k_t,var_obj,preview_widget); new_color=var_obj.get()
                    if old_color!=new_color:
                        action=EditAction(var_obj,old_color,new_color,k_t,entry_ref,f"Choose color for {lbl}")
                        undo_manager.record_action(action)
                return on_choose_color
            preview_lbl.bind("<Button-1>",make_choose_color_lambda(key_tuple,current_var,preview_lbl,entry))
            root.color_previews[key_tuple]=preview_lbl
            asterisk_col_idx = 3 # Asterisk after swatch

        asterisk_lbl_color=tk.Label(colors_frame,text="",fg="red",width=1)
        asterisk_lbl_color.grid(row=row_c,column=asterisk_col_idx,padx=(0,5),pady=5,sticky="w")
        root.asterisk_labels[key_tuple]=asterisk_lbl_color; row_c+=1

def save_file():
    global file_path,original_loaded_offsets,original_loaded_colors, colors, SPECIAL_TEXT_COLOR_LABELS
    if not file_path: messagebox.showerror("Error","No file."); return
    if not hasattr(root,'offsets_vars') or not hasattr(root,'color_vars'): messagebox.showerror("Error","Data not init."); return
    try:
        with open(file_path,'r+b') as f:
            for off_key,var_obj in root.offsets_vars.items():
                val_str=var_obj.get()
                try: val_f=float(val_str); packed=struct.pack('<f',val_f)
                except ValueError: messagebox.showerror("Save Err",f"Bad float '{val_str}' for {off_key}"); return
                for addr in off_key: f.seek(addr); f.write(packed)
                original_loaded_offsets[off_key]=val_str
                if off_key in root.asterisk_labels: root.asterisk_labels[off_key].config(text="")
            
            for color_label, off_tuple_list in colors.items(): # Iterate using label to check against SPECIAL_TEXT_COLOR_LABELS
                off_key = tuple(off_tuple_list)
                if off_key not in root.color_vars: continue
                var_obj = root.color_vars[off_key]
                
                if color_label in SPECIAL_TEXT_COLOR_LABELS:
                    text_val = var_obj.get() # Should be "WHITE" or "BLACK"
                    if text_val in ["WHITE", "BLACK"]:
                        bytes_to_write = text_val.encode('ascii').ljust(5, b'\x00')[:5] # Ensure 5 bytes
                        for addr in off_key: f.seek(addr); f.write(bytes_to_write)
                        original_loaded_colors[off_key]=text_val
                    else: messagebox.showerror("Save Err",f"Invalid text color '{text_val}' for {color_label}"); return
                else: # Regular hex color
                    hex_str=var_obj.get()
                    if not (len(hex_str)==7 and hex_str.startswith('#')):
                        messagebox.showerror("Save Err",f"Bad color '{hex_str}' for {color_label}"); return
                    try:
                        r_val,g_val,b_val=int(hex_str[1:3],16),int(hex_str[3:5],16),int(hex_str[5:7],16)
                        bgra=bytes([b_val,g_val,r_val,0xFF]) 
                    except ValueError: messagebox.showerror("Save Err",f"Bad hex '{hex_str}' for {color_label}"); return
                    for addr in off_key: f.seek(addr); f.write(bgra)
                    original_loaded_colors[off_key]=hex_str
                
                if off_key in root.asterisk_labels: root.asterisk_labels[off_key].config(text="")
        update_status("File saved successfully.","green"); undo_manager.clear_history()
    except Exception as e: messagebox.showerror("Save Err",f"Open/Save fail: {e}")


def update_value(offset_key_tuple, string_var, from_undo_redo=False): # For numerical offsets
    global composite_mode_active, composite_elements, offsets
    global original_loaded_offsets
    
    val_str = string_var.get()
    if not from_undo_redo: logging.debug(f"update_value for {offset_key_tuple} with '{val_str}'")
    
    try:
        new_game_offset_val = float(val_str) 
    except ValueError:
        if not from_undo_redo: update_status(f"Invalid float '{val_str}'", "red")
        if offset_key_tuple in root.asterisk_labels: root.asterisk_labels[offset_key_tuple].config(text="!")
        return

    if offset_key_tuple in root.asterisk_labels:
        original_val = original_loaded_offsets.get(offset_key_tuple)
        is_changed = True
        if original_val is not None:
            try:
                if abs(float(original_val) - new_game_offset_val) < 0.0001: is_changed = False
            except ValueError: pass
        root.asterisk_labels[offset_key_tuple].config(text="*" if is_changed else "")
    
    if not from_undo_redo: update_status(f"Game offset for {offset_key_tuple} now {new_game_offset_val:.2f}", "blue")

    if composite_mode_active:
        visual_updated_overall = False 
        current_offset_json_label = None
        for label, off_list in offsets.items():
            if tuple(off_list) == offset_key_tuple:
                current_offset_json_label = label
                break
        if not current_offset_json_label: return

        is_this_a_font_size_update = " Size" in current_offset_json_label and \
                                   any(keyword in current_offset_json_label for keyword in ["Font", "Text", "Name", "Score"])

        for el_data in composite_elements:
            element_was_modified = False
            is_x_offset = (el_data.get('x_offset_label_linked') == current_offset_json_label)
            is_y_offset = (el_data.get('y_offset_label_linked') == current_offset_json_label)

            if is_x_offset or is_y_offset:
                gui_ref_x, gui_ref_y = el_data.get('gui_ref_x'), el_data.get('gui_ref_y')
                base_game_x, base_game_y = el_data.get('base_game_x'), el_data.get('base_game_y')
                if gui_ref_x is not None and gui_ref_y is not None:
                    if is_x_offset and base_game_x is not None:
                        el_data['original_x'] = float(gui_ref_x) + (new_game_offset_val - base_game_x)
                        element_was_modified = True
                    if is_y_offset and base_game_y is not None:
                        el_data['original_y'] = float(gui_ref_y) + (new_game_offset_val - base_game_y)
                        element_was_modified = True
                if element_was_modified:
                    logging.info(f"Comp: Pos for '{el_data.get('display_tag')}' updated.")
                    leader_tag = el_data.get('display_tag')
                    if leader_tag:
                        for follower_elem in composite_elements:
                            if follower_elem.get('conjoined_to_tag') == leader_tag:
                                follower_elem['original_x'] = el_data['original_x'] + follower_elem.get('relative_offset_x',0)
                                follower_elem['original_y'] = el_data['original_y'] + follower_elem.get('relative_offset_y',0)
            
            if is_this_a_font_size_update and el_data.get('type') == "text" and \
               el_data.get('font_size_offset_label_linked') == current_offset_json_label:
                gui_render_font_size = new_game_offset_val / 1.5 
                el_data['base_font_size'] = gui_render_font_size 
                element_was_modified = True
                logging.info(f"Comp: Font for {el_data.get('display_tag')} (link: '{current_offset_json_label}') "
                             f"updated. Game val: {new_game_offset_val} -> GUI render: {gui_render_font_size:.2f}")
            if element_was_modified: visual_updated_overall = True
        if visual_updated_overall: redraw_composite_view()

def increment_value(event, str_var, direction):
    try:
        current_val_str=str_var.get();
        if not current_val_str or current_val_str=="ERR": current_val_str="0.0"
        value_float=float(current_val_str)
        increment_amt=1.0
        if event.state&0x0001: increment_amt=0.1 
        if event.state&0x0004: increment_amt=0.01 
        if event.state&0x0001 and event.state&0x0004: increment_amt=0.001 
            
        if direction=='Up': value_float+=increment_amt
        elif direction=='Down': value_float-=increment_amt
        str_var.set(f"{value_float:.4f}") # update_value will be called by the KeyRelease binding
    except ValueError: update_status("Invalid value for increment","red")


# This function handles updates from regular hex color entries
def update_color_preview_from_entry(off_key_tuple, str_var, from_undo_redo=False):
    global original_loaded_colors, composite_mode_active
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
            if composite_mode_active: 
                redraw_composite_view() # Redraw if a hex color linked to a text element changes
        except ValueError: 
            if not from_undo_redo:
                update_status("Invalid hex color code.", "red")
    elif not from_undo_redo and len(hex_color_str) > 0 and not hex_color_str.startswith('#') and \
         all(c in "0123456789abcdefABCDEF" for c in hex_color_str) and len(hex_color_str) <= 6:
        str_var.set("#" + hex_color_str.upper()) 
        update_color_preview_from_entry(off_key_tuple, str_var, from_undo_redo) 
        return 

    if off_key_tuple in root.asterisk_labels:
        original_color_val = original_loaded_colors.get(off_key_tuple)
        is_changed = True 
        if is_valid_hex and original_color_val:
            is_changed = (original_color_val.lower() != hex_color_str.lower())
        elif not is_valid_hex and original_color_val == "ERR_LOAD": # If it was error and still error, not changed
             is_changed = False
        root.asterisk_labels[off_key_tuple].config(text="*" if is_changed else "")

# This new function handles updates from the "WHITE"/"BLACK" combobox
def handle_special_text_color_change(off_key_tuple, str_var, from_undo_redo=False):
    global original_loaded_colors, composite_mode_active
    text_color_value = str_var.get() # "WHITE" or "BLACK"

    if not from_undo_redo:
        update_status(f"Text color set to {text_color_value}.", "blue")
    
    if composite_mode_active:
        redraw_composite_view() # Redraw if this special text color changes

    if off_key_tuple in root.asterisk_labels:
        original_val = original_loaded_colors.get(off_key_tuple)
        is_changed = (original_val != text_color_value) if original_val else True
        root.asterisk_labels[off_key_tuple].config(text="*" if is_changed else "")


def choose_color(off_key_tuple, str_var, preview_widget_ref): # For hex colors
    old_color_hex = str_var.get()
    current_color_for_dialog = old_color_hex
    if not (current_color_for_dialog.startswith("#") and len(current_color_for_dialog) == 7):
        current_color_for_dialog = "#000000" 
    
    new_color_tuple_result = colorchooser.askcolor(initialcolor=current_color_for_dialog, title="Choose Color")
    
    if new_color_tuple_result and new_color_tuple_result[1]: 
        chosen_hex_color = new_color_tuple_result[1].lower() 
        # Undo is handled by the calling lambda (make_choose_color_lambda)
        str_var.set(chosen_hex_color)
        update_color_preview_from_entry(off_key_tuple, str_var)


def update_status(msg,fg_col): status_label.config(text=msg,fg=fg_col)

def about():
    win=tk.Toplevel(root); win.title("About FLP Scoreboard Editor 25"); win.geometry("450x300")
    win.resizable(False,False); win.transient(root); win.grab_set()
    tk.Label(win,text="FLP Scoreboard Editor 25",pady=10,font=("Helvetica",12,"bold")).pack()
    tk.Label(win,text="Version 1.13 [Build 12 May 2025]",pady=5).pack()
    tk.Label(win,text="© 2025 FIFA Legacy Project. All Rights Reserved.",pady=5).pack()
    tk.Label(win,text="Designed & Developed By: Emran_Ahm3d",pady=5).pack()
    tk.Label(win,text="Special Thanks: Riesscar, KO, MCK, Marconis (Research)",pady=5,wraplength=400).pack()
    tk.Label(win,text="Discord: @emran_ahm3d",pady=5).pack()
    ttk.Button(win,text="OK",command=win.destroy,width=10).pack(pady=10); win.wait_window()

def show_documentation(): webbrowser.open("https://soccergaming.com/")

def restrict_color_entry(event, str_var):
    allowed_keysyms=['Left','Right','BackSpace','Delete','Tab','Home','End','Shift_L','Shift_R','Control_L','Control_R']
    if event.keysym in allowed_keysyms: return
    if event.state&0x4 and event.keysym.lower() in ('c','v','x'): return
    current_text=str_var.get(); char_typed=event.char
    if not char_typed or not char_typed.isprintable(): return
    if not current_text and char_typed!='#':
        str_var.set('#'+char_typed.upper())
        event.widget.after_idle(lambda:event.widget.icursor(tk.END)); return 'break'
    if current_text=='#' and char_typed=='#': return 'break'
    has_selection=False
    try:
        if event.widget.selection_present(): has_selection=True
    except tk.TclError: pass
    if len(current_text)>=7 and not has_selection: return 'break'
    if current_text.startswith('#'):
        if not char_typed.lower() in '0123456789abcdef': return 'break'

def exit_app():
    if messagebox.askyesno("Exit Application","Are you sure you want to exit?"): root.destroy()

def import_texture():
    global file_path,current_image_index,image_files
    if not file_path: messagebox.showerror("Error","No .big file loaded."); return
    if composite_mode_active: messagebox.showinfo("Info","Import/Export is disabled in Composite View mode."); return
    try: big_file_obj=FifaBigFile(file_path)
    except Exception as e: messagebox.showerror("Error",f"Failed to read BIG file for import: {e}"); logging.error(f"BIG read error import: {e}",exc_info=True); return
    if not image_files or not (0<=current_image_index<len(image_files)): messagebox.showerror("Error","No valid texture selected for import."); return
    file_name_to_replace=image_files[current_image_index]
    original_entry_obj=next((entry for entry in big_file_obj.entries if entry.name==file_name_to_replace),None)
    if original_entry_obj is None: messagebox.showerror("Error",f"File '{file_name_to_replace}' not found in BIG archive."); return
    new_texture_path=filedialog.askopenfilename(title=f"Import texture for {file_name_to_replace}.dds",filetypes=[("DDS Files","*.dds"),("PNG Files","*.png")])
    if not new_texture_path: return
    new_data_uncompressed=None; temp_dds_for_import_path=None
    try:
        if new_texture_path.lower().endswith(".png"):
            try:
                with Image.open(new_texture_path) as pil_img: pil_img_rgba=pil_img.convert("RGBA")
                with tempfile.NamedTemporaryFile(delete=False,suffix=".dds") as temp_dds_f:
                    temp_dds_for_import_path=temp_dds_f.name; pil_img_rgba.save(temp_dds_for_import_path,"DDS")
                with open(temp_dds_for_import_path,'rb') as f_dds_read: new_data_uncompressed=f_dds_read.read()
                logging.info(f"Converted {new_texture_path} to temp DDS.")
            except Exception as e_png_conv: messagebox.showerror("PNG Conversion Error",f"Failed to convert PNG to DDS: {e_png_conv}"); logging.error(f"PNG to DDS error: {e_png_conv}",exc_info=True); return
        elif new_texture_path.lower().endswith(".dds"):
            with open(new_texture_path,'rb') as new_f: new_data_uncompressed=new_f.read()
            logging.info(f"Read DDS {new_texture_path} for import.")
        else: messagebox.showerror("Error","Unsupported file type. Select DDS or PNG."); return
        if not new_data_uncompressed: messagebox.showerror("Error","Failed to read new texture data."); return
        data_to_write_in_big=new_data_uncompressed; compression_applied_msg=""
        if original_entry_obj.compression==Compression.EAHD:
            logging.info(f"Original '{file_name_to_replace}' was EAHD. Compressing new texture.")
            data_to_write_in_big=Compressor.compress_eahd(new_data_uncompressed)
            if data_to_write_in_big is new_data_uncompressed: compression_applied_msg="(EAHD compression placeholder; data uncompressed)"
            else: compression_applied_msg="(EAHD compression attempted)"
            logging.info(f"Compression: {compression_applied_msg}")
        if original_entry_obj.raw_size>0 and len(data_to_write_in_big)>original_entry_obj.raw_size:
            msg=(f"New data ({format_filesize(len(data_to_write_in_big))}) > original slot ({format_filesize(original_entry_obj.raw_size)}) for '{file_name_to_replace}'. Import aborted. {compression_applied_msg}")
            messagebox.showerror("Size Error",msg); logging.warning(msg); return
        with open(file_path,'r+b') as f_big_write:
            f_big_write.seek(original_entry_obj.offset); f_big_write.write(data_to_write_in_big)
            if original_entry_obj.raw_size>0 and len(data_to_write_in_big)<original_entry_obj.raw_size:
                padding_size=original_entry_obj.raw_size-len(data_to_write_in_big)
                f_big_write.write(b'\x00'*padding_size); logging.info(f"Padded import with {padding_size} bytes.")
        success_msg=(f"Imported '{os.path.basename(new_texture_path)}' as '{file_name_to_replace}.dds'.\n"
                       f"Original slot: {format_filesize(original_entry_obj.raw_size)}, New data: {format_filesize(len(data_to_write_in_big))}. {compression_applied_msg}")
        messagebox.showinfo("Import Successful",success_msg); logging.info(success_msg)
        if not extract_and_display_texture(): messagebox.showwarning("Preview Warning","Could not refresh preview.")
        else: update_status(f"Texture {file_name_to_replace}.dds imported.","green")
    except Exception as e_import: messagebox.showerror("Import Error",f"Unexpected import error: {e_import}"); logging.error(f"General import error: {e_import}",exc_info=True)
    finally:
        if temp_dds_for_import_path and os.path.exists(temp_dds_for_import_path):
            try: os.remove(temp_dds_for_import_path)
            except Exception as e_clean: logging.warning(f"Could not remove temp import file: {e_clean}")

def export_selected_file():
    global file_path,current_image_index,image_files
    if not file_path: messagebox.showerror("Error","No .big file loaded."); return
    if composite_mode_active: messagebox.showinfo("Info","Import/Export is disabled in Composite View mode."); return
    if not image_files or not (0<=current_image_index<len(image_files)): messagebox.showerror("Error","No texture selected."); return
    file_name_to_export=image_files[current_image_index]
    try: big_file_obj=FifaBigFile(file_path)
    except Exception as e: messagebox.showerror("Error",f"Could not read BIG for export: {e}"); logging.error(f"BIG read error export: {e}",exc_info=True); return
    entry_obj_to_export=next((e for e in big_file_obj.entries if e.name==file_name_to_export),None)
    if not entry_obj_to_export or entry_obj_to_export.size==0 or not entry_obj_to_export.data:
        messagebox.showerror("Error",f"File '{file_name_to_export}' not found or empty."); return
    data_for_export=entry_obj_to_export.data
    export_target_path=filedialog.asksaveasfilename(defaultextension=".png",filetypes=[("PNG Files","*.png"),("DDS Files","*.dds")],initialfile=f"{file_name_to_export}")
    if not export_target_path: return
    temp_dds_path_for_export=None
    try:
        if export_target_path.lower().endswith(".png"):
            with tempfile.NamedTemporaryFile(delete=False,suffix=".dds") as temp_dds_f:
                temp_dds_f.write(data_for_export);temp_dds_path_for_export=temp_dds_f.name
            with Image.open(temp_dds_path_for_export) as pil_img_export: pil_img_export.save(export_target_path,"PNG")
            messagebox.showinfo("Export Successful",f"Exported '{file_name_to_export}.dds' as PNG to:\n'{export_target_path}'")
            logging.info(f"Exported {file_name_to_export}.dds as PNG to {export_target_path}")
        elif export_target_path.lower().endswith(".dds"):
            with open(export_target_path,'wb') as out_f_dds: out_f_dds.write(data_for_export)
            messagebox.showinfo("Export Successful",f"Exported '{file_name_to_export}.dds' as DDS to:\n'{export_target_path}'")
            logging.info(f"Exported {file_name_to_export}.dds as DDS to {export_target_path}")
        else: messagebox.showerror("Error","Unsupported export format. Choose .png or .dds.")
    except Exception as e_export: messagebox.showerror("Export Error",f"Failed to export file: {e_export}"); logging.error(f"Export fail: {e_export}",exc_info=True)
    finally:
        if temp_dds_path_for_export and os.path.exists(temp_dds_path_for_export):
            try: os.remove(temp_dds_path_for_export)
            except Exception as e_clean_export: logging.warning(f"Could not remove temp export file: {e_clean_export}")

def previous_image():
    global current_image_index,composite_mode_active
    if composite_mode_active or not file_path or not image_files: return
    original_idx=current_image_index; num_files=len(image_files)
    if num_files==0: return
    for i in range(num_files):
        current_image_index=(original_idx-1-i+num_files*2)%num_files
        if extract_and_display_texture(): return
    current_image_index=original_idx
    if not extract_and_display_texture():
        preview_canvas.delete("all");texture_label.config(text="No displayable textures");current_image=None

def next_image():
    global current_image_index,composite_mode_active
    if composite_mode_active or not file_path or not image_files: return
    original_idx=current_image_index; num_files=len(image_files)
    if num_files==0: return
    for i in range(num_files):
        current_image_index=(original_idx+1+i)%num_files
        if extract_and_display_texture(): return
    current_image_index=original_idx
    if not extract_and_display_texture():
        preview_canvas.delete("all");texture_label.config(text="No displayable textures");current_image=None

def toggle_preview_background():
    global preview_bg_color_is_white,composite_mode_active
    if composite_mode_active: return
    preview_bg_color_is_white = not preview_bg_color_is_white
    if file_path and current_image: extract_and_display_texture()

def toggle_composite_mode():
    global composite_mode_active,current_image_index,image_files,current_image,composite_zoom_level,composite_pan_offset_x,composite_pan_offset_y
    global import_button,export_button,highlighted_offset_entries,toggle_bg_button
    logging.info(f"Toggling composite. Current: {composite_mode_active}")
    if not composite_mode_active:
        is_ok=internal_name_label.cget("text").startswith("Internal Name: ") and \
              not internal_name_label.cget("text").endswith("(No Config)") and \
              not internal_name_label.cget("text").endswith("(Detection Failed)")
        if not file_path or not is_ok:
            messagebox.showinfo("Info","Load .big with valid config first."); logging.warning("Composite prereqs not met."); return
        target_img_name="10"
        if not (0<=current_image_index<len(image_files) and image_files[current_image_index]==target_img_name):
            logging.info(f"Not on {target_img_name}. Switching.")
            try:
                idx_10=image_files.index(target_img_name); current_image_index=idx_10
                _temp_comp_active=composite_mode_active; composite_mode_active=False
                success_load_10=extract_and_display_texture(); composite_mode_active=_temp_comp_active
                if not success_load_10:
                    messagebox.showerror("Error",f"Could not load {target_img_name}.dds. Cannot enter composite."); logging.error(f"Failed load {target_img_name}.dds."); return
                root.update_idletasks()
            except ValueError: messagebox.showerror("Error",f"'{target_img_name}' not in image_files. Cannot enter composite."); return
        preview_canvas.delete("all");current_image=None;texture_label.config(text="");image_dimensions_label.config(text="")
        composite_mode_active=True;composite_zoom_level=1.0;composite_pan_offset_x=250.0;composite_pan_offset_y=50.0
        display_composite_view()
        if not composite_mode_active: logging.warning("display_composite_view failed."); return
        composite_view_button.config(text="Single View");left_arrow_button.pack_forget();right_arrow_button.pack_forget()
        import_button.config(state=tk.DISABLED);export_button.config(state=tk.DISABLED);toggle_bg_button.config(state=tk.DISABLED)
        logging.info("Switched TO composite successfully.")
    else:
        clear_all_highlights();logging.info("Switching FROM composite.")
        composite_mode_active=False;clear_composite_view()
        composite_view_button.config(text="Composite View")
        left_arrow_button.pack(side=tk.LEFT,padx=(0,5),pady=5,anchor='center')
        right_arrow_button.pack(side=tk.LEFT,padx=5,pady=5,anchor='center')
        import_button.config(state=tk.NORMAL);export_button.config(state=tk.NORMAL);toggle_bg_button.config(state=tk.NORMAL)
        if file_path: extract_and_display_texture()
        else: preview_canvas.delete("all");texture_label.config(text="No file");image_dimensions_label.config(text="")
        logging.info("Switched FROM composite.")

def clear_all_highlights():
    global highlighted_offset_entries
    for entry_widget,original_bg in highlighted_offset_entries:
        try:
            if entry_widget.winfo_exists(): entry_widget.config(bg=original_bg)
        except tk.TclError: pass
    highlighted_offset_entries.clear()

def clear_composite_view():
    global composite_elements,preview_canvas
    preview_canvas.delete("composite_item")
    for el in composite_elements:
        if 'tk_image_ref' in el and el['tk_image_ref']: del el['tk_image_ref']
    composite_elements.clear(); preview_canvas.config(bg="#CCCCCC")

def redraw_composite_view():
    global composite_elements,preview_canvas,composite_zoom_level,composite_pan_offset_x,composite_pan_offset_y,colors,root, SPECIAL_TEXT_COLOR_LABELS
    preview_canvas.delete("composite_item"); canvas_w=preview_canvas.winfo_width(); canvas_h=preview_canvas.winfo_height()
    if canvas_w<=1: canvas_w=580
    if canvas_h<=1: canvas_h=150
    view_orig_x_canvas=canvas_w/2.0; view_orig_y_canvas=canvas_h/2.0
    eff_pan_x=composite_pan_offset_x*composite_zoom_level; eff_pan_y=composite_pan_offset_y*composite_zoom_level
    for el_data in composite_elements:
        screen_x=view_orig_x_canvas-eff_pan_x+(el_data['original_x']*composite_zoom_level)
        screen_y=view_orig_y_canvas-eff_pan_y+(el_data['original_y']*composite_zoom_level)
        el_data['current_x_on_canvas']=screen_x; el_data['current_y_on_canvas']=screen_y
        if el_data.get('type')=="text":
            base_font_sz=el_data.get('base_font_size',DEFAULT_TEXT_BASE_FONT_SIZE) 
            zoomed_font_sz=max(1,int(base_font_sz*composite_zoom_level))
            font_fam=el_data.get('font_family',DEFAULT_TEXT_FONT_FAMILY); text_col=DEFAULT_TEXT_COLOR_FALLBACK
            
            color_label_key=el_data.get('color_offset_label') # This is the JSON key, e.g., "Added Time Text Color"
            if color_label_key and color_label_key in colors and hasattr(root,'color_vars'):
                color_json_key_tuple=tuple(colors[color_label_key]) # This is the address tuple
                if color_json_key_tuple in root.color_vars:
                    current_color_val_from_var = root.color_vars[color_json_key_tuple].get()
                    if color_label_key in SPECIAL_TEXT_COLOR_LABELS:
                        text_col = current_color_val_from_var.lower() # "white" or "black"
                    elif current_color_val_from_var and current_color_val_from_var.startswith("#") and len(current_color_val_from_var)==7:
                        text_col=current_color_val_from_var
                    else: logging.warning(f"Invalid hex '{current_color_val_from_var}' for '{color_label_key}'.")
                else: logging.warning(f"Var for key {color_json_key_tuple} ({color_label_key}) not in root.color_vars.")
            elif color_label_key: logging.warning(f"Color label '{color_label_key}' not in 'colors' dict.")
            
            item_id=preview_canvas.create_text(int(screen_x),int(screen_y),anchor=tk.NW,text=el_data['text_content'],
                                                 font=(font_fam,zoomed_font_sz,"bold"),fill=text_col,
                                                 tags=("composite_item",el_data['display_tag']))
            el_data['canvas_id']=item_id
        elif el_data.get('type')=="image":
            pil_img_obj=el_data['pil_image']
            zoomed_w_img=int(pil_img_obj.width*composite_zoom_level); zoomed_h_img=int(pil_img_obj.height*composite_zoom_level)
            if zoomed_w_img<=0 or zoomed_h_img<=0: continue
            try:
                resized_pil=pil_img_obj.resize((zoomed_w_img,zoomed_h_img),Image.LANCZOS)
                el_data['tk_image_ref']=ImageTk.PhotoImage(resized_pil)
                item_id=preview_canvas.create_image(int(screen_x),int(screen_y),anchor=tk.NW,
                                                      image=el_data['tk_image_ref'],tags=("composite_item",el_data['display_tag']))
                el_data['canvas_id']=item_id
            except Exception as e_redraw_img: logging.error(f"Redraw img {el_data.get('display_tag')}: {e_redraw_img}")
        else: logging.warning(f"Unknown element type: {el_data.get('type')}")

def display_composite_view():
    global composite_elements,preview_canvas,file_path,composite_mode_active,initial_text_elements_config,predefined_image_coords,offsets,root,current_reference_width,current_reference_height, SPECIAL_TEXT_COLOR_LABELS
    logging.info("Attempting display_composite_view.")
    if not file_path: composite_mode_active=False; return
    preview_canvas.config(bg="gray70")
    try:
        big_file=FifaBigFile(file_path)
        if current_reference_width is None or current_reference_height is None: logging.warning("Ref dims not set.")
        canvas_w=preview_canvas.winfo_width(); canvas_h=preview_canvas.winfo_height()
        if canvas_w<=1: canvas_w=580
        if canvas_h<=1: canvas_h=150
        images_to_load_cfg=[("10","10"),("14","14"),("30","30_orig"),("30","30_dup")]
        source_dds_entries={e.name:e for e in big_file.entries if e.name in [c[0] for c in images_to_load_cfg] and e.file_type=="DDS" and e.data}
        temp_composite_elements_map:Dict[str,Dict[str,Any]]={}
        for big_name,disp_tag_suffix in images_to_load_cfg:
            if big_name not in source_dds_entries: logging.warning(f"Img '{big_name}' not found."); continue
            source_entry=source_dds_entries[big_name]; current_img_tag=f"img_{disp_tag_suffix}"
            img_cfg=predefined_image_coords.get(current_img_tag)
            if not img_cfg: logging.error(f"No predefined_image_coords for {current_img_tag}."); continue
            gui_ref_x,gui_ref_y,x_off_lbl,base_gx,y_off_lbl,base_gy = img_cfg
            temp_dds_path=None
            try:
                with tempfile.NamedTemporaryFile(delete=False,suffix=".dds") as tmp_f: tmp_f.write(source_entry.data);temp_dds_path=tmp_f.name
                pil_img=Image.open(temp_dds_path).convert("RGBA")
                vis_x=float(gui_ref_x);vis_y=float(gui_ref_y);link_x_var=None;link_y_var=None
                if x_off_lbl and y_off_lbl and base_gx is not None and base_gy is not None and hasattr(root,'offsets_vars') and offsets:
                    if x_off_lbl in offsets and y_off_lbl in offsets:
                        x_key=tuple(offsets[x_off_lbl]);y_key=tuple(offsets[y_off_lbl])
                        if x_key in root.offsets_vars and y_key in root.offsets_vars:
                            link_x_var=root.offsets_vars[x_key];link_y_var=root.offsets_vars[y_key]
                            try:
                                cur_gx=float(link_x_var.get());cur_gy=float(link_y_var.get())
                                dev_x=cur_gx-base_gx;dev_y=cur_gy-base_gy
                                vis_x=float(gui_ref_x)+dev_x;vis_y=float(gui_ref_y)+dev_y
                            except ValueError: link_x_var=None;link_y_var=None 
                is_fixed=(current_img_tag=="img_10")
                img_el_data={'type':"image",'pil_image':pil_img,'original_x':vis_x,'original_y':vis_y,
                             'image_name_in_big':source_entry.name,'display_tag':current_img_tag,
                             'tk_image_ref':None,'canvas_id':None,'is_fixed':is_fixed,
                             'x_offset_label_linked':x_off_lbl,'y_offset_label_linked':y_off_lbl,
                             'x_var_linked':link_x_var,'y_var_linked':link_y_var,
                             'base_game_x':base_gx,'base_game_y':base_gy,'gui_ref_x':gui_ref_x,'gui_ref_y':gui_ref_y}
                temp_composite_elements_map[current_img_tag]=img_el_data
            except Exception as e_img_prep: logging.error(f"Error prep img {current_img_tag}: {e_img_prep}",exc_info=True)
            finally:
                if temp_dds_path and os.path.exists(temp_dds_path): os.remove(temp_dds_path)
        
        for config_tuple in initial_text_elements_config:
            tag_cfg,txt_cfg,gui_x,gui_y,design_font_size_cfg,font_size_label_cfg, \
            color_label_cfg,is_fixed_cfg,x_off_lbl,base_gx,y_off_lbl,base_gy = config_tuple

            vis_x=float(gui_x);vis_y=float(gui_y);link_x_var=None;link_y_var=None
            current_gui_render_font_size = float(design_font_size_cfg) 

            if x_off_lbl and y_off_lbl and base_gx is not None and base_gy is not None and hasattr(root,'offsets_vars') and offsets:
                if x_off_lbl in offsets and y_off_lbl in offsets:
                    x_key=tuple(offsets[x_off_lbl]);y_key=tuple(offsets[y_off_lbl])
                    if x_key in root.offsets_vars and y_key in root.offsets_vars:
                        link_x_var=root.offsets_vars[x_key];link_y_var=root.offsets_vars[y_key]
                        try:
                            cur_gx=float(link_x_var.get());cur_gy=float(link_y_var.get())
                            dev_x=cur_gx-base_gx;dev_y=cur_gy-base_gy
                            vis_x=float(gui_x)+dev_x;vis_y=float(gui_y)+dev_y
                        except ValueError: link_x_var=None;link_y_var=None
            
            font_size_var_linked = None 
            if font_size_label_cfg and font_size_label_cfg != "PlaceHolder" and font_size_label_cfg in offsets and hasattr(root, 'offsets_vars'):
                font_size_key_tuple = tuple(offsets[font_size_label_cfg])
                if font_size_key_tuple in root.offsets_vars:
                    font_size_var_linked = root.offsets_vars[font_size_key_tuple]
                    try:
                        game_font_size_val = float(font_size_var_linked.get())
                        current_gui_render_font_size = game_font_size_val / 1.5 
                        logging.info(f"Comp: Initial font for '{tag_cfg}' (linked to '{font_size_label_cfg}') "
                                     f"game_val: {game_font_size_val} -> GUI render size: {current_gui_render_font_size:.2f}")
                    except ValueError:
                        logging.warning(f"Non-float value for font size offset '{font_size_label_cfg}' for text element '{tag_cfg}'. "
                                        f"Using design size {design_font_size_cfg}.")
            elif font_size_label_cfg == "PlaceHolder":
                 logging.info(f"Comp: Font size for '{tag_cfg}' uses design size {design_font_size_cfg} due to 'PlaceHolder' link.")
            
            txt_el_data={'type':"text",'text_content':txt_cfg,'original_x':vis_x,'original_y':vis_y,
                         'base_font_size':current_gui_render_font_size, 
                         'font_size_offset_label_linked': font_size_label_cfg, 
                         'font_size_var_linked': font_size_var_linked, 
                         'font_family':DEFAULT_TEXT_FONT_FAMILY,'color_offset_label':color_label_cfg,
                         'display_tag':tag_cfg,'canvas_id':None,'is_fixed':is_fixed_cfg,
                         'x_offset_label_linked':x_off_lbl,'y_offset_label_linked':y_off_lbl,
                         'x_var_linked':link_x_var,'y_var_linked':link_y_var,
                         'base_game_x':base_gx,'base_game_y':base_gy,'gui_ref_x':gui_x,'gui_ref_y':gui_y}
            temp_composite_elements_map[tag_cfg]=txt_el_data
        
        leader_tag="text_added_time";follower_tag="img_14"
        if leader_tag in temp_composite_elements_map and follower_tag in temp_composite_elements_map:
            leader_el=temp_composite_elements_map[leader_tag];follower_el=temp_composite_elements_map[follower_tag]
            img14_gui_x_abs=predefined_image_coords[follower_tag][0];img14_gui_y_abs=predefined_image_coords[follower_tag][1]
            txt_add_time_cfg=next(item for item in initial_text_elements_config if item[0]==leader_tag)
            txt_add_time_gui_x_abs=txt_add_time_cfg[2];txt_add_time_gui_y_abs=txt_add_time_cfg[3]
            rel_off_x=img14_gui_x_abs-txt_add_time_gui_x_abs;rel_off_y=img14_gui_y_abs-txt_add_time_gui_y_abs
            follower_el['original_x']=leader_el['original_x']+rel_off_x;follower_el['original_y']=leader_el['original_y']+rel_off_y
            follower_el['conjoined_to_tag']=leader_tag;follower_el['relative_offset_x']=rel_off_x
            follower_el['relative_offset_y']=rel_off_y;follower_el['is_fixed']=True
        composite_elements=list(temp_composite_elements_map.values());redraw_composite_view()
        texture_label.config(text="Composite Mode Active")
        image_dimensions_label.config(text=f"Canvas: {canvas_w}x{canvas_h} | Ref: {current_reference_width or 'N/A'}x{current_reference_height or 'N/A'}")
    except Exception as e_comp_disp:
        messagebox.showerror("Composite Err",f"Display fail: {e_comp_disp}");logging.error(f"CRITICAL Comp display error: {e_comp_disp}",exc_info=True)
        composite_mode_active=False;toggle_composite_mode()

def zoom_composite_view(event):
    global composite_zoom_level,composite_pan_offset_x,composite_pan_offset_y,preview_canvas
    if not composite_elements: return
    factor=1.1 if event.delta>0 else (1/1.1); new_zoom=max(0.05,min(composite_zoom_level*factor,10.0))
    canvas_w=preview_canvas.winfo_width(); canvas_h=preview_canvas.winfo_height()
    mouse_x_center=event.x-(canvas_w/2.0); mouse_y_center=event.y-(canvas_h/2.0)
    if abs(composite_zoom_level)>1e-6 and abs(new_zoom)>1e-6:
        pan_adj_x=mouse_x_center*((1.0/composite_zoom_level)-(1.0/new_zoom))
        pan_adj_y=mouse_y_center*((1.0/composite_zoom_level)-(1.0/new_zoom))
        composite_pan_offset_x+=pan_adj_x; composite_pan_offset_y+=pan_adj_y
    composite_zoom_level=new_zoom; redraw_composite_view()

def start_pan_composite(event):
    global drag_data; drag_data["is_panning_rmb"]=True; drag_data["x"]=event.x; drag_data["y"]=event.y
    logging.debug(f"Comp RMB Pan start ({event.x},{event.y})")

def on_pan_composite(event):
    global drag_data,composite_pan_offset_x,composite_pan_offset_y,composite_zoom_level
    if not drag_data.get("is_panning_rmb"): return
    dx_canvas=event.x-drag_data["x"]; dy_canvas=event.y-drag_data["y"]
    if abs(composite_zoom_level)>1e-6:
        delta_orig_x=dx_canvas/composite_zoom_level; delta_orig_y=dy_canvas/composite_zoom_level
        composite_pan_offset_x-=delta_orig_x; composite_pan_offset_y-=delta_orig_y
    drag_data["x"]=event.x; drag_data["y"]=event.y; redraw_composite_view()

def start_drag_composite(event):
    global composite_drag_data,composite_elements,drag_data,highlighted_offset_entries,offsets,root
    clear_all_highlights()
    if event.num==3: start_pan_composite(event); return
    drag_data["is_panning"]=False; drag_data["is_panning_rmb"]=False
    item_tuple=event.widget.find_closest(event.x,event.y)
    if not item_tuple: composite_drag_data['item']=None; return
    item_id=item_tuple[0]
    if "composite_item" not in preview_canvas.gettags(item_id): composite_drag_data['item']=None; return
    for el_data in composite_elements:
        if el_data.get('canvas_id')==item_id:
            if el_data.get('is_fixed',False):
                logging.info(f"Attempt drag fixed: {el_data.get('display_tag')}"); composite_drag_data['item']=None; return
            initial_gx,initial_gy=0.0,0.0
            x_var=el_data.get('x_var_linked'); y_var=el_data.get('y_var_linked')
            if x_var and y_var:
                try: initial_gx=float(x_var.get()); initial_gy=float(y_var.get())
                except ValueError: logging.warning(f"Could not parse initial game offsets for {el_data.get('display_tag')}.")
            composite_drag_data.update({'item':item_id,'x':event.x,'y':event.y,'element_data':el_data,
                                        'start_original_x':el_data['original_x'],'start_original_y':el_data['original_y'],
                                        'initial_game_offset_x_at_drag_start':initial_gx,
                                        'initial_game_offset_y_at_drag_start':initial_gy})
            preview_canvas.tag_raise(item_id)
            x_label=el_data.get('x_offset_label_linked'); y_label=el_data.get('y_offset_label_linked')
            font_size_label = el_data.get('font_size_offset_label_linked')

            if x_label and x_label in offsets and hasattr(root,'offset_entry_widgets'):
                x_key=tuple(offsets[x_label])
                if x_key in root.offset_entry_widgets:
                    entry_w=root.offset_entry_widgets[x_key]
                    highlighted_offset_entries.append((entry_w,entry_w.cget("background"))); entry_w.config(bg="lightyellow")
            if y_label and y_label in offsets and hasattr(root,'offset_entry_widgets'):
                y_key=tuple(offsets[y_label])
                if y_key in root.offset_entry_widgets:
                    entry_w=root.offset_entry_widgets[y_key]
                    if not any(he[0]==entry_w for he in highlighted_offset_entries):
                        highlighted_offset_entries.append((entry_w,entry_w.cget("background"))); entry_w.config(bg="lightyellow")
            if font_size_label and font_size_label != "PlaceHolder" and font_size_label in offsets and el_data.get('type') == "text" and not el_data.get('is_fixed'):
                 font_size_key = tuple(offsets[font_size_label])
                 if font_size_key in root.offset_entry_widgets:
                    entry_w_font = root.offset_entry_widgets[font_size_key]
                    if not any(he[0] == entry_w_font for he in highlighted_offset_entries):
                        highlighted_offset_entries.append((entry_w_font, entry_w_font.cget("background")))
                        entry_w_font.config(bg="lightcyan") 
            return
    composite_drag_data['item']=None

def on_drag_composite(event):
    global composite_drag_data,composite_zoom_level,drag_data,composite_elements,offsets,root
    if event.num==3 or drag_data.get("is_panning_rmb"): on_pan_composite(event); return
    if composite_drag_data.get('item') is None or drag_data.get("is_panning"): return
    dragged_elem_data=composite_drag_data.get('element_data')
    if not dragged_elem_data: return
    mouse_dx_canvas=event.x-composite_drag_data['x']; mouse_dy_canvas=event.y-composite_drag_data['y']
    if abs(composite_zoom_level)<1e-6: return
    delta_visual_original_x=mouse_dx_canvas/composite_zoom_level; delta_visual_original_y=mouse_dy_canvas/composite_zoom_level
    new_visual_original_x=composite_drag_data['start_original_x']+delta_visual_original_x
    new_visual_original_y=composite_drag_data['start_original_y']+delta_visual_original_y
    dragged_elem_data['original_x']=new_visual_original_x; dragged_elem_data['original_y']=new_visual_original_y
    x_var_linked=dragged_elem_data.get('x_var_linked'); y_var_linked=dragged_elem_data.get('y_var_linked')
    if x_var_linked and y_var_linked: 
        initial_game_x=composite_drag_data['initial_game_offset_x_at_drag_start']
        initial_game_y=composite_drag_data['initial_game_offset_y_at_drag_start']
        new_game_offset_x=initial_game_x+delta_visual_original_x
        new_game_offset_y=initial_game_y+delta_visual_original_y
        old_x_str=x_var_linked.get(); old_y_str=y_var_linked.get()
        new_x_str_val=f"{new_game_offset_x:.2f}"; new_y_str_val=f"{new_game_offset_y:.2f}"
        x_var_linked.set(new_x_str_val); y_var_linked.set(new_y_str_val)
        logging.info(f"Drag: Elem '{dragged_elem_data.get('display_tag')}' game offsets -> X={new_x_str_val}, Y={new_y_str_val}")
        x_offset_label=dragged_elem_data.get('x_offset_label_linked'); y_offset_label=dragged_elem_data.get('y_offset_label_linked')
        if x_offset_label and x_offset_label in offsets:
            x_key_tuple=tuple(offsets[x_offset_label])
            if old_x_str!=new_x_str_val:
                action_x=EditAction(x_var_linked,old_x_str,new_x_str_val,x_key_tuple,root.offset_entry_widgets.get(x_key_tuple),f"Drag {dragged_elem_data.get('display_tag')} X")
                undo_manager.record_action(action_x)
            update_value(x_key_tuple,x_var_linked,from_undo_redo=True)
        if y_offset_label and y_offset_label in offsets:
            y_key_tuple=tuple(offsets[y_offset_label])
            if old_y_str!=new_y_str_val:
                action_y=EditAction(y_var_linked,old_y_str,new_y_str_val,y_key_tuple,root.offset_entry_widgets.get(y_key_tuple),f"Drag {dragged_elem_data.get('display_tag')} Y")
                undo_manager.record_action(action_y)
            update_value(y_key_tuple,y_var_linked,from_undo_redo=True)
    dragged_tag=dragged_elem_data.get('display_tag')
    if dragged_tag:
        for follower_elem in composite_elements:
            if follower_elem.get('conjoined_to_tag')==dragged_tag:
                follower_elem['original_x']=dragged_elem_data['original_x']+follower_elem.get('relative_offset_x',0)
                follower_elem['original_y']=dragged_elem_data['original_y']+follower_elem.get('relative_offset_y',0)
    redraw_composite_view()

def on_drag_release_composite(event):
    global drag_data
    if event.num==3: drag_data["is_panning_rmb"]=False; logging.debug("RMB Pan released")

root=tk.Tk(); root.title("FLP Scoreboard Editor 25 (v1.13)"); root.geometry("930x710"); root.resizable(False,False)
menubar=tk.Menu(root)
filemenu=tk.Menu(menubar,tearoff=0)
filemenu.add_command(label="Open",command=open_file,accelerator="Ctrl+O")
filemenu.add_command(label="Save",command=save_file,accelerator="Ctrl+S")
filemenu.add_separator(); filemenu.add_command(label="Exit",command=exit_app)
menubar.add_cascade(label="File",menu=filemenu)
editmenu=tk.Menu(menubar,tearoff=0)
editmenu.add_command(label="Undo",command=lambda:undo_manager.undo(),accelerator="Ctrl+Z",state=tk.DISABLED)
editmenu.add_command(label="Redo",command=lambda:undo_manager.redo(),accelerator="Ctrl+Y",state=tk.DISABLED)
menubar.add_cascade(label="Edit",menu=editmenu); root.editmenu=editmenu
helpmenu=tk.Menu(menubar,tearoff=0)
helpmenu.add_command(label="About",command=about); helpmenu.add_separator()
helpmenu.add_command(label="Documentation",command=show_documentation)
menubar.add_cascade(label="Help",menu=helpmenu); root.config(menu=menubar)
root.bind_all("<Control-o>",lambda event:open_file()); root.bind_all("<Control-s>",lambda event:save_file())
root.bind_all("<Control-z>",lambda event:undo_manager.undo()); root.bind_all("<Control-y>",lambda event:undo_manager.redo())
notebook=ttk.Notebook(root)
positions_frame_container=ttk.Frame(notebook)
positions_canvas=tk.Canvas(positions_frame_container,highlightthickness=0)
positions_scrollbar=ttk.Scrollbar(positions_frame_container,orient="vertical",command=positions_canvas.yview)
positions_frame=ttk.Frame(positions_canvas)
positions_frame.bind("<Configure>",lambda e:positions_canvas.configure(scrollregion=positions_canvas.bbox("all")))
positions_canvas.create_window((0,0),window=positions_frame,anchor="nw")
positions_canvas.configure(yscrollcommand=positions_scrollbar.set)
positions_canvas.pack(side="left",fill="both",expand=True); positions_scrollbar.pack(side="right",fill="y")
notebook.add(positions_frame_container,text="Positions")
sizes_frame=ttk.Frame(notebook); notebook.add(sizes_frame,text="Sizes")
colors_frame=ttk.Frame(notebook); notebook.add(colors_frame,text="Colors")
notebook.pack(expand=1,fill="both",padx=10,pady=5)
preview_controls_frame=tk.Frame(root); preview_controls_frame.pack(fill=tk.X,padx=10,pady=5)
left_arrow_button=ttk.Button(preview_controls_frame,text="◀",command=previous_image,width=2)
left_arrow_button.pack(side=tk.LEFT,padx=(0,5),pady=5,anchor='center')
preview_canvas=tk.Canvas(preview_controls_frame,width=580,height=150,bg="#CCCCCC",relief="solid",bd=1)
preview_canvas.pack(side=tk.LEFT,padx=5,pady=5,anchor='center')
preview_canvas.bind("<MouseWheel>",zoom_image_handler); preview_canvas.bind("<ButtonPress-1>",start_drag_handler)
preview_canvas.bind("<B1-Motion>",on_drag_handler); preview_canvas.bind("<ButtonRelease-1>",on_drag_release_handler)
preview_canvas.bind("<ButtonPress-3>",start_pan_composite); preview_canvas.bind("<B3-Motion>",on_pan_composite)
preview_canvas.bind("<ButtonRelease-3>",on_drag_release_composite)
right_arrow_button=ttk.Button(preview_controls_frame,text="▶",command=next_image,width=2)
right_arrow_button.pack(side=tk.LEFT,padx=5,pady=5,anchor='center')
vertical_buttons_frame=tk.Frame(preview_controls_frame)
vertical_buttons_frame.pack(side=tk.LEFT,padx=(10,0),pady=0,anchor='n')
toggle_bg_button=ttk.Button(vertical_buttons_frame,text="Toggle Alpha",command=toggle_preview_background,width=15)
toggle_bg_button.pack(side=tk.TOP,pady=(5,2))
composite_view_button=ttk.Button(vertical_buttons_frame,text="Composite View",command=toggle_composite_mode,width=15)
composite_view_button.pack(side=tk.TOP,pady=(2,5))
texture_info_frame=tk.Frame(root); texture_info_frame.pack(fill=tk.X,padx=10,pady=(0,5))
texture_label=tk.Label(texture_info_frame,text="No texture loaded",font=('Helvetica',9),anchor='w')
texture_label.pack(side=tk.LEFT,padx=5)
image_dimensions_label=tk.Label(texture_info_frame,text=" ",font=('Helvetica',10),anchor='e')
image_dimensions_label.pack(side=tk.RIGHT,padx=10)
buttons_frame=tk.Frame(root); buttons_frame.place(relx=1.0,rely=1.0,anchor='se',x=-10,y=-85)
import_button=ttk.Button(buttons_frame,text="IMPORT",command=import_texture,width=10)
import_button.pack(pady=2)
export_button=ttk.Button(buttons_frame,text="EXPORT",command=export_selected_file,width=10)
export_button.pack(pady=2)
save_button_main=ttk.Button(buttons_frame,text="SAVE",command=save_file,width=10)
save_button_main.pack(pady=(2,0))
bottom_frame=tk.Frame(root); bottom_frame.pack(side=tk.BOTTOM,fill=tk.X,padx=10,pady=(0,5))
status_label=tk.Label(bottom_frame,text="Ready",anchor=tk.W,fg="blue",font=('Helvetica',10))
status_label.pack(side=tk.LEFT,padx=0)
file_path_label=tk.Label(bottom_frame,text="File: None",anchor=tk.W,font=('Helvetica',9))
file_path_label.pack(side=tk.LEFT,padx=10)
internal_name_label=tk.Label(bottom_frame,text="Internal Name: Not Loaded",anchor=tk.E,font=('Helvetica',10))
internal_name_label.pack(side=tk.RIGHT,padx=0)
root.style=ttk.Style(); root.style.configure('TButton',font=('Helvetica',10),padding=3)
root.style.configure('Large.TButton',font=('Helvetica',12),padding=5)
left_arrow_button.configure(style='TButton');right_arrow_button.configure(style='TButton')
toggle_bg_button.configure(style='TButton');composite_view_button.configure(style='TButton')
import_button.configure(style='Large.TButton');export_button.configure(style='Large.TButton');save_button_main.configure(style='Large.TButton')
def on_map_event(event):
    if file_path and not current_image and not composite_mode_active: extract_and_display_texture()
root.bind("<Map>",on_map_event,"+")
clear_editor_widgets();undo_manager.update_menu_states()
if not offsets_data: logging.critical("offsets_data not loaded. App exit."); exit()
root.mainloop()