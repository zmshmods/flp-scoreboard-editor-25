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
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s')

# Load offsets from JSON file
try:
    with open('offsets.json', 'r') as f:
        offsets_data = json.load(f)
except FileNotFoundError:
    logging.error("offsets.json not found."); messagebox.showerror("Error", "offsets.json not found."); exit()
except json.JSONDecodeError:
    logging.error("Error decoding offsets.json."); messagebox.showerror("Error", "Error decoding offsets.json."); exit()

file_path: Optional[str] = None
offsets = {} 
colors = {}  
current_image: Optional[Image.Image] = None

original_loaded_offsets = {} 
original_loaded_colors = {}  

preview_bg_color_is_white = True
current_image_index = 0
image_files = [str(i) for i in range(1, 81)]

single_view_zoom_level = 1.0
single_view_pan_offset_x = 0.0
single_view_pan_offset_y = 0.0
drag_data = {"x": 0, "y": 0, "item": None, "is_panning": False, "is_panning_rmb": False}

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
composite_pan_offset_x = 0.0 # Will be adjusted for initial view
composite_pan_offset_y = 0.0 # Will be adjusted for initial view

DEFAULT_TEXT_FONT_FAMILY = "Arial"
DEFAULT_TEXT_BASE_FONT_SIZE = 14 
DEFAULT_TEXT_COLOR_FALLBACK = "white"

initial_text_elements_config = [
    ("text_hom", "HOM", 185, 22, 22, "Home Team Name Color", False, "Home Team Name X", 241, "Home Team Name Y", 17),
    ("text_awa", "AWA", 375, 22, 22, "Away Team Name Color", False, "Away Team Name X", 425, "Away Team Name Y", 17),
    ("text_score1", "1", 280, 22, 22, "Home Score Color", False, "Home Score X", 352, "Home Score Y", 17),
    ("text_score2", "2", 325, 22, 22, "Away Score Color", False, "Away Score X", 395, "Away Score Y", 17),
    ("text_time_min1",  "2", 63, 23, 22, "Time Text Color", False, "1st Digit of Time (0--:--) X", -330, "1st Digit of Time (0--:--) Y", 2),
    ("text_time_min2",  "3", 80, 23, 22, "Time Text Color", False, "2nd Digit of Time (-0-:--) X", -315, "2nd Digit of Time (-0-:--) Y", 2),
    ("text_time_min3",  "4", 98, 23, 22, "Time Text Color", False, "3rd Digit of Time (--0:--) X", -300, "3rd Digit of Time (--0:--) Y", 2), 
    ("text_time_colon", ":", 113, 20, 22, "Time Text Color", False, "Colon Seperator of Time (---:--) X", -290, "Colon Seperator of Time (---:--) Y", -2), 
    ("text_time_sec1",  "5", 123, 23, 22, "Time Text Color", False, "4th Digit of Time (---:0-) X", -280, "4th Digit of Time (---:0-) Y", 2),
    ("text_time_sec2",  "6", 138, 23, 22, "Time Text Color", False, "5th Digit of Time (---:-0) X", -265, "5th Digit of Time (---:-0) Y", 2),
    ("text_added_time", "+9", 120, 67, 22, None, False, "Added Time X", 130, "Added Time Y", 83),
]

predefined_image_coords: Dict[str, tuple[float, float, Optional[str], Optional[float], Optional[str], Optional[float]]] = { 
    "img_10":       (5.0, 5.0, None, None, None, None), 
    "img_14":       (104, 51, None, None, None, None), 
    "img_30_orig":  (135, 8, "Home Color Bar X", 212, "Home Color Bar Y", 103.5),
    "img_30_dup":   (436, 8, "Away Color Bar X", 502, "Away Color Bar Y", 103.5) 
}

highlighted_offset_entries = [] 

class EditAction: # (Same)
    def __init__(self, string_var, old_value, new_value, key_tuple, entry_widget_ref, description="value change"):
        self.string_var = string_var
        self.old_value = old_value
        self.new_value = new_value
        self.key_tuple = key_tuple 
        self.entry_widget_ref = entry_widget_ref 
        self.description = description
    def undo(self): self.string_var.set(self.old_value)
    def redo(self): self.string_var.set(self.new_value)

class UndoManager: # (Same)
    def __init__(self, max_history=50):
        self.undo_stack: List[EditAction] = []
        self.redo_stack: List[EditAction] = []
        self.max_history = max_history
    def record_action(self, action: EditAction):
        self.redo_stack.clear()
        self.undo_stack.append(action)
        if len(self.undo_stack) > self.max_history: self.undo_stack.pop(0)
        self.update_menu_states()
    def can_undo(self): return bool(self.undo_stack)
    def can_redo(self): return bool(self.redo_stack)
    def _apply_action_and_update_ui(self, action_to_apply: EditAction, is_undo: bool):
        if is_undo: action_to_apply.undo()
        else: action_to_apply.redo()
        is_offset_var = False
        if hasattr(root, 'offsets_vars'):
            for key, var in root.offsets_vars.items():
                if var == action_to_apply.string_var:
                    update_value(key, action_to_apply.string_var, from_undo_redo=True)
                    is_offset_var = True; break
        if not is_offset_var and hasattr(root, 'color_vars'):
            for key, var in root.color_vars.items():
                if var == action_to_apply.string_var:
                    update_color_preview_from_entry(key, action_to_apply.string_var, from_undo_redo=True)
                    break
        self.update_menu_states()
    def undo(self):
        if not self.can_undo(): return
        action = self.undo_stack.pop()
        self._apply_action_and_update_ui(action, is_undo=True)
        self.redo_stack.append(action); self.update_menu_states()
    def redo(self):
        if not self.can_redo(): return
        action = self.redo_stack.pop()
        self._apply_action_and_update_ui(action, is_undo=False)
        self.undo_stack.append(action); self.update_menu_states()
    def clear_history(self):
        self.undo_stack.clear(); self.redo_stack.clear(); self.update_menu_states()
    def update_menu_states(self):
        if hasattr(root, 'editmenu'):
            root.editmenu.entryconfig("Undo", state=tk.NORMAL if self.can_undo() else tk.DISABLED)
            root.editmenu.entryconfig("Redo", state=tk.NORMAL if self.can_redo() else tk.DISABLED)

undo_manager = UndoManager()

class Compression(Enum): NONE = "None"; EAHD = "EAHD"
# ... (FileEntry, BinaryReader, Decompressor, Compressor, FifaBigFile - classes are the same as before) ...
@dataclass
class FileEntry:
    offset: int; size: int; name: str; file_type: str
    compression: Compression; data: bytes; raw_size: int

class BinaryReader: # (Same)
    def __init__(self, data: bytearray): self.data = data; self.pos = 0
    def read_byte(self) -> int:
        if self.pos >= len(self.data): raise ValueError("EOS")
        v = self.data[self.pos]; self.pos += 1; return v
    def read_int(self, c: int = 4, be: bool = False) -> int:
        if self.pos + c > len(self.data): raise ValueError(f"Not enough for int{c}")
        chunk = self.data[self.pos:self.pos+c]; self.pos += c
        return int.from_bytes(chunk, "big" if be else "little")
    def read_string(self, enc: str) -> str:
        s = self.pos
        while self.pos < len(self.data) and self.data[self.pos]!=0: self.pos+=1
        b = self.data[s:self.pos]
        if self.pos < len(self.data) and self.data[self.pos]==0: self.pos+=1
        return b.decode(enc, errors="ignore")
    def skip(self, c: int): self.pos = min(len(self.data), self.pos + c)

class Decompressor: # (Same)
    @staticmethod
    def detect_compression(data: bytes) -> Compression:
        return Compression.EAHD if len(data) >= 2 and data[:2] == b"\xfb\x10" else Compression.NONE
    @staticmethod
    def decompress_eahd(data: bytes) -> bytes:
        try:
            reader = BinaryReader(bytearray(data))
            if reader.read_int(2, True) != 0xFB10: return data
            total_size = reader.read_int(3, True); output = bytearray(total_size); pos = 0
            while reader.pos < len(reader.data) and pos < total_size:
                ctrl = reader.read_byte(); to_read = 0; to_copy = 0; offset_val = 0
                if ctrl < 0x80: a = reader.read_byte(); to_read = ctrl&0x03; to_copy = ((ctrl&0x1C)>>2)+3; offset_val = ((ctrl&0x60)<<3)+a+1
                elif ctrl < 0xC0: a,b=reader.read_byte(),reader.read_byte(); to_read=(a>>6)&0x03; to_copy=(ctrl&0x3F)+4; offset_val=((a&0x3F)<<8)+b+1
                elif ctrl < 0xE0: a,b,c=reader.read_byte(),reader.read_byte(),reader.read_byte(); to_read=ctrl&0x03; to_copy=((ctrl&0x0C)<<6)+c+5; offset_val=((ctrl&0x10)<<12)+(a<<8)+b+1
                elif ctrl < 0xFC: to_read = ((ctrl&0x1F)<<2)+4
                else: to_read = ctrl&0x03
                if pos+to_read > total_size: to_read=total_size-pos
                for _ in range(to_read): 
                    if reader.pos >= len(reader.data): break 
                    output[pos]=reader.read_byte(); pos+=1
                if to_copy > 0:
                    copy_start=pos-offset_val
                    if copy_start < 0: logging.error("EAHD: Invalid copy offset."); return data 
                    if pos+to_copy > total_size: to_copy=total_size-pos 
                    for _ in range(to_copy):
                        if copy_start >= pos : logging.error("EAHD: copy_start >= pos."); return data 
                        output[pos]=output[copy_start]; pos+=1; copy_start+=1
            return bytes(output[:pos])
        except ValueError as e: logging.error(f"EAHD Decomp ValueError: {e}"); return data
        except Exception as e: logging.error(f"EAHD Decomp Exception: {e}", exc_info=True); return data

class Compressor: # (Same)
    @staticmethod
    def compress_eahd(data: bytes) -> bytes:
        logging.warning("EAHD COMPRESSION IS NOT IMPLEMENTED. Ret uncompressed."); return data

class FifaBigFile: # (Same)
    def __init__(self, filename):
        self.filename = filename; self.entries: List[FileEntry] = []; self._load()
    def _load(self):
        try:
            with open(self.filename, 'rb') as f: self.data_content = bytearray(f.read())
        except FileNotFoundError: logging.error(f"BIG file not found: {self.filename}"); raise
        reader = BinaryReader(self.data_content)
        try:
            magic=bytes(self.data_content[:4])
            if magic not in (b'BIGF', b'BIG4'): raise ValueError(f"Invalid BIG magic: {magic}")
            reader.skip(4); reader.read_int(4, False) 
            num_entries=reader.read_int(4,True); reader.read_int(4,True) 
        except ValueError as e: logging.error(f"BIG header error: {e}"); raise
        current_type_tag = "DAT"
        for i in range(num_entries):
            try:
                entry_offset=reader.read_int(4,True); entry_raw_size=reader.read_int(4,True)
                entry_name=reader.read_string('utf-8')
            except ValueError as e: logging.error(f"Entry read error at index {i}: {e}"); continue
            if entry_raw_size==0 and entry_name in {"sg1","sg2"}:
                current_type_tag = {"sg1":"DDS","sg2":"APT"}[entry_name]
                self.entries.append(FileEntry(entry_offset,0,entry_name,current_type_tag,Compression.NONE,b"",0)); continue
            actual_raw_size = entry_raw_size
            if entry_offset + entry_raw_size > len(self.data_content):
                actual_raw_size = len(self.data_content) - entry_offset
                if actual_raw_size < 0: actual_raw_size = 0
            raw_data = bytes(self.data_content[entry_offset : entry_offset + actual_raw_size])
            comp_type = Decompressor.detect_compression(raw_data)
            decomp_data = Decompressor.decompress_eahd(raw_data) if comp_type==Compression.EAHD else raw_data
            det_file_type = current_type_tag
            if decomp_data[:4] == b'DDS ': det_file_type = "DDS"
            self.entries.append(FileEntry(entry_offset,len(decomp_data),entry_name,det_file_type,comp_type,decomp_data,entry_raw_size))
    def list_files(self) -> List[str]: return [e.name for e in self.entries if e.size > 0]

def read_internal_name(fp: str) -> Optional[str]: # (Same)
    if not fp or not os.path.exists(fp): return None
    try:
        with open(fp, 'rb') as f: content = f.read(200*1024) 
        text = content.decode('utf-8', errors='ignore')
        names = ["15002","2002","3002","4002","5002","6002","8002"]
        for n in names:
            if n in text: return n
        return None
    except Exception as e: logging.error(f"Read internal name fail: {e}"); return None

def open_file(): # MODIFIED: No "Loaded" status, file_path_label updated
    global file_path, current_image_index, composite_mode_active, undo_manager
    global original_loaded_offsets, original_loaded_colors

    fp_temp = filedialog.askopenfilename(filetypes=[("FIFA Big Files", "*.big")])
    if fp_temp:
        file_path = fp_temp; current_image_index = 0
        undo_manager.clear_history() 
        original_loaded_offsets.clear(); original_loaded_colors.clear()
        if hasattr(root, 'asterisk_labels'):
            for asterisk_label in root.asterisk_labels.values(): asterisk_label.config(text="")
        
        file_path_label.config(text=f"File: {file_path}") # Update persistent file path display
        add_internal_name() 
        
        is_internal_name_ok = internal_name_label.cget("text").startswith("Internal Name: ") and \
                              not internal_name_label.cget("text").endswith("(No Config)") and \
                              not internal_name_label.cget("text").endswith("(Detection Failed)")
        if composite_mode_active: 
            is_comp_eligible = (file_path and 0 <= current_image_index < len(image_files) and image_files[current_image_index] == "10")
            if not is_comp_eligible or not is_internal_name_ok:
                toggle_composite_mode() 
            else: display_composite_view() 
        else: 
            if is_internal_name_ok: extract_and_display_texture() 
            else:
                preview_canvas.delete("all"); current_image = None
                texture_label.config(text="Load .big / No internal name"); image_dimensions_label.config(text="")
    else: 
        if not file_path: file_path_label.config(text="File: None")

def redraw_single_view_image(): # (Same)
    global current_image, preview_canvas, single_view_zoom_level, single_view_pan_offset_x, single_view_pan_offset_y
    if current_image is None: preview_canvas.delete("all"); return
    canvas_w = preview_canvas.winfo_width(); canvas_h = preview_canvas.winfo_height()
    if canvas_w <= 1: canvas_w = 580; canvas_h = 150 
    img_to_display = current_image 
    zoomed_w = int(img_to_display.width * single_view_zoom_level)
    zoomed_h = int(img_to_display.height * single_view_zoom_level)
    if zoomed_w <= 0 or zoomed_h <= 0: return
    try:
        resized_img = img_to_display.resize((zoomed_w, zoomed_h), Image.LANCZOS)
        img_tk = ImageTk.PhotoImage(resized_img)
        preview_canvas.delete("all")
        draw_x = canvas_w / 2 + single_view_pan_offset_x
        draw_y = canvas_h / 2 + single_view_pan_offset_y
        preview_canvas.create_image(draw_x, draw_y, anchor=tk.CENTER, image=img_tk, tags="image_on_canvas")
        preview_canvas.image_ref = img_tk
    except Exception as e: logging.error(f"Error redrawing single view image: {e}")
def extract_and_display_texture() -> bool: # (Same)
    global file_path, current_image, current_image_index, preview_bg_color_is_white, composite_mode_active
    global single_view_zoom_level, single_view_pan_offset_x, single_view_pan_offset_y
    if composite_mode_active: return False
    if not file_path: 
        preview_canvas.delete("all"); texture_label.config(text="No file"); current_image = None; return False
    try:
        big_file = FifaBigFile(file_path)
        if not (0 <= current_image_index < len(image_files)): return False
        img_name = image_files[current_image_index]
        entry = next((e for e in big_file.entries if e.name == img_name), None)
        if not entry or entry.size == 0 or not entry.data or entry.file_type != "DDS" or entry.data[:4] != b'DDS ':
            logging.info(f"Texture '{img_name}' invalid/not found/no data."); return False
        temp_dds_path = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".dds") as tmp_f:
                tmp_f.write(entry.data); temp_dds_path = tmp_f.name
            pil_img = Image.open(temp_dds_path)
            w_orig, h_orig = pil_img.width, pil_img.height
            bg_color = (255,255,255,255) if preview_bg_color_is_white else (0,0,0,255)
            pil_rgba = pil_img.convert('RGBA') if pil_img.mode != 'RGBA' else pil_img
            background = Image.new('RGBA', pil_rgba.size, bg_color)
            current_image = Image.alpha_composite(background, pil_rgba)
            single_view_zoom_level = 1.0; single_view_pan_offset_x = 0.0; single_view_pan_offset_y = 0.0
            redraw_single_view_image()
            texture_label.config(text=f"{img_name}.dds")
            image_dimensions_label.config(text=f"{w_orig}x{h_orig}")
            return True
        except Exception as e_display: logging.warning(f"Display DDS '{img_name}' failed: {e_display}"); return False
        finally:
            if temp_dds_path and os.path.exists(temp_dds_path): os.remove(temp_dds_path)
    except Exception as e_outer: logging.error(f"Outer error in extract: {e_outer}", exc_info=True); return False

def zoom_image_handler(event): # (Same)
    if composite_mode_active: zoom_composite_view(event)
    else: zoom_single_view(event)
def zoom_single_view(event): # (Same)
    global single_view_zoom_level
    if current_image is None: return
    factor = 1.1 if event.delta > 0 else (1/1.1)
    new_zoom = max(0.05, min(single_view_zoom_level * factor, 10.0)) 
    single_view_zoom_level = new_zoom
    redraw_single_view_image()
def start_drag_handler(event): # (Same)
    if composite_mode_active: start_drag_composite(event) 
    else: start_drag_single(event)
def on_drag_handler(event): # (Same)
    if composite_mode_active: on_drag_composite(event) 
    else: on_drag_single(event)
def on_drag_release_handler(event): # MODIFIED to clear highlights
    global drag_data, composite_mode_active
    drag_data["is_panning"] = False 
    drag_data["is_panning_rmb"] = False 
    if composite_mode_active:
        clear_all_highlights()
def start_drag_single(event): # (Same)
    global drag_data
    drag_data["is_panning"] = True; drag_data["x"] = event.x; drag_data["y"] = event.y
def on_drag_single(event): # (Same)
    global drag_data, single_view_pan_offset_x, single_view_pan_offset_y
    if not drag_data["is_panning"] or current_image is None: return
    dx = event.x - drag_data["x"]; dy = event.y - drag_data["y"]
    single_view_pan_offset_x += dx; single_view_pan_offset_y += dy
    drag_data["x"] = event.x; drag_data["y"] = event.y
    redraw_single_view_image()

def load_current_values(): # MODIFIED
    global file_path, original_loaded_offsets, original_loaded_colors
    if not file_path or not hasattr(root, 'offsets_vars') or not hasattr(root, 'color_vars'): return
    original_loaded_offsets.clear(); original_loaded_colors.clear()
    try:
        with open(file_path, 'rb') as file:
            for off_tuple, var_obj in root.offsets_vars.items():
                if not off_tuple: continue
                try:
                    file.seek(off_tuple[0]); data = file.read(4); val = struct.unpack('<f', data)[0]
                    val_str = f"{val:.2f}"; var_obj.set(val_str)
                    original_loaded_offsets[off_tuple] = val_str 
                    if off_tuple in root.asterisk_labels: root.asterisk_labels[off_tuple].config(text="")
                except Exception: var_obj.set("ERR") 
            for off_tuple, var_obj in root.color_vars.items():
                if not off_tuple: continue
                try:
                    file.seek(off_tuple[0]); data = file.read(4)
                    hex_col = f'#{data[2]:02X}{data[1]:02X}{data[0]:02X}'; var_obj.set(hex_col)
                    original_loaded_colors[off_tuple] = hex_col
                    if off_tuple in root.color_previews: root.color_previews[off_tuple].config(bg=hex_col)
                    if off_tuple in root.asterisk_labels: root.asterisk_labels[off_tuple].config(text="")
                except Exception: var_obj.set("#ERR")
    except Exception as e: messagebox.showerror("Error", f"Failed to read values: {e}")
def add_internal_name(): # (Same)
    global file_path, previous_file_path, offsets, colors, current_reference_width, current_reference_height, composite_mode_active
    if not file_path:
        internal_name_label.config(text="Internal Name: Not Loaded"); clear_editor_widgets()
        current_reference_width=None; current_reference_height=None
        if composite_mode_active: toggle_composite_mode(); return
    internal_name_str = read_internal_name(file_path)
    if internal_name_str:
        internal_name_label.config(text=f"Internal Name: {internal_name_str}")
        if internal_name_str in offsets_data:
            config = offsets_data[internal_name_str]
            current_reference_width = config.get("reference_width")
            current_reference_height = config.get("reference_height")
            offsets = {k:[int(str(v),16) for v in (vl if isinstance(vl,list) else [vl])] for k,vl in config.get("offsets",{}).items()}
            colors = {k:[int(str(v),16) for v in (vl if isinstance(vl,list) else [vl])] for k,vl in config.get("colors",{}).items()}
            recreate_widgets(); load_current_values()
            previous_file_path = file_path
        else: 
            messagebox.showerror("Config Error", f"Config for '{internal_name_str}' not found.")
            internal_name_label.config(text=f"Internal Name: {internal_name_str} (No Config)"); clear_editor_widgets()
            current_reference_width=None; current_reference_height=None
            if composite_mode_active: toggle_composite_mode()
    else: 
        messagebox.showerror("Detection Error", "No internal name detected.")
        current_reference_width=None; current_reference_height=None
        if previous_file_path: 
            file_path = previous_file_path; add_internal_name()
            update_status(f"Reverted to: {os.path.basename(file_path)}", "orange")
        else: 
            internal_name_label.config(text="Internal Name: Detection Failed"); clear_editor_widgets()
            preview_canvas.delete("all"); current_image=None; texture_label.config(text="")
            image_dimensions_label.config(text="")
            if composite_mode_active: toggle_composite_mode()
def clear_editor_widgets(): # (Same)
    for frame in [positions_frame, sizes_frame, colors_frame]:
        for widget in frame.winfo_children(): widget.destroy()
    for attr in ['offsets_vars','offsets_values','color_vars','color_values','color_previews', 'offset_entry_widgets', 'asterisk_labels']:
        if hasattr(root, attr): getattr(root, attr).clear()
def recreate_widgets(): # (Same, includes root.offset_entry_widgets, root.asterisk_labels)
    clear_editor_widgets(); global offsets, colors
    root.offsets_vars = {tuple(v): tk.StringVar() for v in offsets.values()}
    root.color_vars = {tuple(v): tk.StringVar(value='#000000') for v in colors.values()}
    root.color_previews = {} 
    root.offset_entry_widgets = {} 
    root.asterisk_labels = {}

    def make_offset_update_lambda(key_tuple, var, entry_widget):
        def on_offset_update(event=None): 
            old_value = original_loaded_offsets.get(key_tuple, "") 
            new_value = var.get()
            # Record undo only if value changed and not from FocusOut after KeyRelease already recorded it
            is_focus_out_after_key_release = (event and event.type == tk.EventType.FocusOut and 
                                              hasattr(entry_widget, '_undo_recorded_for_this_change') and 
                                              entry_widget._undo_recorded_for_this_change)
            if old_value != new_value and not is_focus_out_after_key_release:
                if not (event and event.type == tk.EventType.FocusOut): # Don't record for FocusOut if it's the same value as after KeyRelease
                    action = EditAction(var, old_value, new_value, key_tuple, entry_widget, f"Offset change for {key_tuple}")
                    undo_manager.record_action(action)
                if event and event.type == tk.EventType.KeyRelease:
                     entry_widget._undo_recorded_for_this_change = True 
            update_value(key_tuple, var) 
            if event and event.type == tk.EventType.FocusOut:
                if hasattr(entry_widget, '_undo_recorded_for_this_change'):
                    delattr(entry_widget, '_undo_recorded_for_this_change')
        return on_offset_update
    
    def make_increment_lambda(key_tuple, var, entry_widget, direction):
        def on_increment(event=None):
            old_value = var.get()
            entry_widget.unbind("<KeyRelease>") # Avoid double recording
            increment_value(event, var, direction) 
            new_value = var.get()
            if old_value != new_value:
                action = EditAction(var, old_value, new_value, key_tuple, entry_widget, f"Increment {direction}")
                undo_manager.record_action(action)
            update_value(key_tuple, var) 
            entry_widget.bind("<KeyRelease>", make_offset_update_lambda(key_tuple, var, entry_widget))
        return on_increment

    row_p = 0
    for lbl, off_list in offsets.items():
        key_tuple = tuple(off_list)
        if "Size" not in lbl and not lbl.startswith("Image_"):
            col = 0 if "X" in lbl or "Width" in lbl else 4; base_col = col
            tk.Label(positions_frame,text=lbl).grid(row=row_p,column=base_col,padx=5,pady=5,sticky="w")
            entry = tk.Entry(positions_frame,textvariable=root.offsets_vars[key_tuple],width=10)
            entry.grid(row=row_p,column=base_col+1,padx=0,pady=5)
            update_lambda = make_offset_update_lambda(key_tuple, root.offsets_vars[key_tuple], entry)
            entry.bind("<KeyRelease>", update_lambda); entry.bind("<FocusOut>", update_lambda) 
            entry.bind('<KeyPress-Up>', make_increment_lambda(key_tuple, root.offsets_vars[key_tuple], entry, "Up"))
            entry.bind('<KeyPress-Down>', make_increment_lambda(key_tuple, root.offsets_vars[key_tuple], entry, "Down"))
            asterisk_lbl = tk.Label(positions_frame, text="", fg="red", width=1); asterisk_lbl.grid(row=row_p, column=base_col+2, padx=(0,5), pady=5, sticky="w")
            root.asterisk_labels[key_tuple] = asterisk_lbl; root.offset_entry_widgets[key_tuple] = entry
            if col==4 or "Y" in lbl or "Height" in lbl: row_p+=1
    row_s=0 
    for lbl,off_list in offsets.items():
        key_tuple = tuple(off_list)
        if "Size" in lbl:
            tk.Label(sizes_frame,text=lbl).grid(row=row_s,column=0,padx=5,pady=5,sticky="w")
            entry=tk.Entry(sizes_frame,textvariable=root.offsets_vars[key_tuple],width=10)
            entry.grid(row=row_s,column=1,padx=0,pady=5) 
            update_lambda_size = make_offset_update_lambda(key_tuple, root.offsets_vars[key_tuple], entry)
            entry.bind("<KeyRelease>", update_lambda_size); entry.bind("<FocusOut>", update_lambda_size)
            entry.bind('<KeyPress-Up>', make_increment_lambda(key_tuple, root.offsets_vars[key_tuple], entry, "Up"))
            entry.bind('<KeyPress-Down>', make_increment_lambda(key_tuple, root.offsets_vars[key_tuple], entry, "Down"))
            asterisk_lbl_size = tk.Label(sizes_frame, text="", fg="red", width=1); asterisk_lbl_size.grid(row=row_s, column=2, padx=(0,5), pady=5, sticky="w")
            root.asterisk_labels[key_tuple] = asterisk_lbl_size; root.offset_entry_widgets[key_tuple] = entry
            row_s+=1
    row_c=0 
    for lbl,off_list in colors.items():
        key_tuple = tuple(off_list)
        tk.Label(colors_frame,text=lbl).grid(row=row_c,column=0,padx=5,pady=5,sticky="w")
        entry=tk.Entry(colors_frame,textvariable=root.color_vars[key_tuple],width=10)
        entry.grid(row=row_c,column=1,padx=0,pady=5) 
        def make_color_update_lambda(k_t, var, entry_w):
            def on_color_update(event=None):
                old_val = original_loaded_colors.get(k_t, "")
                new_val = var.get()
                is_focus_out_after_key = (event and event.type == tk.EventType.FocusOut and hasattr(entry_w, '_undo_recorded_for_this_change') and entry_w._undo_recorded_for_this_change)
                if old_val != new_val and not is_focus_out_after_key:
                    if not (event and event.type == tk.EventType.FocusOut):
                        action = EditAction(var, old_val, new_val, k_t, entry_w, f"Color change for {k_t}")
                        undo_manager.record_action(action)
                    if event and event.type == tk.EventType.KeyRelease: entry_w._undo_recorded_for_this_change = True
                update_color_preview_from_entry(k_t, var)
                if event and event.type == tk.EventType.FocusOut:
                    if hasattr(entry_w, '_undo_recorded_for_this_change'): delattr(entry_w, '_undo_recorded_for_this_change')
            return on_color_update
        color_update_lambda = make_color_update_lambda(key_tuple, root.color_vars[key_tuple], entry)
        entry.bind('<KeyPress>',lambda e,v=root.color_vars[key_tuple]:restrict_color_entry(e,v))
        entry.bind('<KeyRelease>', color_update_lambda); entry.bind("<FocusOut>", color_update_lambda)
        preview_lbl=tk.Label(colors_frame,bg=root.color_vars[key_tuple].get(),width=3,height=1,relief="sunken")
        preview_lbl.grid(row=row_c,column=2,padx=5,pady=5)
        def make_choose_color_lambda(k_t, var_obj, preview_widget, entry_ref):
            def on_choose_color(event=None):
                old_color = var_obj.get()
                choose_color(k_t, var_obj, preview_widget) 
                new_color = var_obj.get()
                if old_color != new_color:
                    action = EditAction(var_obj, old_color, new_color, k_t, entry_ref, f"Choose color for {k_t}")
                    undo_manager.record_action(action)
                update_color_preview_from_entry(k_t, var_obj) 
            return on_choose_color
        preview_lbl.bind("<Button-1>", make_choose_color_lambda(key_tuple, root.color_vars[key_tuple], preview_lbl, entry))
        root.color_previews[key_tuple]=preview_lbl
        asterisk_lbl_color = tk.Label(colors_frame, text="", fg="red", width=1); asterisk_lbl_color.grid(row=row_c, column=3, padx=(0,5), pady=5, sticky="w")
        root.asterisk_labels[key_tuple] = asterisk_lbl_color
        row_c+=1

def format_filesize(b: int) -> str: # (Same)
    if b<1024: return f"{b} bytes";
    return f"{b/1024:.2f} KB" if b<1024*1024 else f"{b/(1024*1024):.2f} MB"
def save_file(): # MODIFIED to update original_loaded values and clear asterisks
    global file_path, original_loaded_offsets, original_loaded_colors
    if not file_path: messagebox.showerror("Error", "No file."); return
    if not hasattr(root, 'offsets_vars') or not hasattr(root, 'color_vars'): messagebox.showerror("Error", "Data not init."); return
    try:
        with open(file_path, 'r+b') as f:
            for off_key, var_obj in root.offsets_vars.items():
                val_str = var_obj.get()
                try: val_f = float(val_str); packed = struct.pack('<f', val_f)
                except ValueError: messagebox.showerror("Save Err",f"Bad float '{val_str}' for {off_key}"); return
                for addr in off_key: f.seek(addr); f.write(packed)
                original_loaded_offsets[off_key] = val_str 
                if off_key in root.asterisk_labels: root.asterisk_labels[off_key].config(text="")
            for off_key, var_obj in root.color_vars.items():
                hex_str = var_obj.get()
                if not (len(hex_str)==7 and hex_str.startswith('#')): messagebox.showerror("Save Err",f"Bad color '{hex_str}' for {off_key}"); return
                try: r,g,b = int(hex_str[1:3],16),int(hex_str[3:5],16),int(hex_str[5:7],16); bgra = bytes([b,g,r,0xFF])
                except ValueError: messagebox.showerror("Save Err",f"Bad hex '{hex_str}' for {off_key}"); return
                for addr in off_key: f.seek(addr); f.write(bgra)
                original_loaded_colors[off_key] = hex_str 
                if off_key in root.asterisk_labels: root.asterisk_labels[off_key].config(text="")
        update_status("File saved successfully.", "green")
        undo_manager.clear_history() 
    except Exception as e: messagebox.showerror("Save Err",f"Open/Save fail: {e}")

def update_value(offset_key_tuple, string_var, from_undo_redo=False): # MODIFIED to update asterisk
    global composite_mode_active, composite_elements, offsets, initial_text_elements_config, predefined_image_coords
    global original_loaded_offsets 
    val_str = string_var.get()
    if not from_undo_redo: logging.debug(f"update_value for {offset_key_tuple} with '{val_str}'")
    try: new_game_offset_val = float(val_str)
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

    if composite_mode_active: # Logic to update composite view if this offset is linked
        visual_updated_for_element = None 
        for el_data in composite_elements:
            is_x_offset, is_y_offset = False, False
            x_label = el_data.get('x_offset_label_linked')
            if x_label and x_label in offsets and tuple(offsets[x_label]) == offset_key_tuple: is_x_offset = True
            y_label = el_data.get('y_offset_label_linked')
            if y_label and y_label in offsets and tuple(offsets[y_label]) == offset_key_tuple: is_y_offset = True

            if is_x_offset or is_y_offset:
                gui_ref_x, gui_ref_y = el_data.get('gui_ref_x'), el_data.get('gui_ref_y')
                base_game_x, base_game_y = el_data.get('base_game_x'), el_data.get('base_game_y')

                if gui_ref_x is not None and gui_ref_y is not None: 
                    if is_x_offset and base_game_x is not None:
                        el_data['original_x'] = float(gui_ref_x) + (new_game_offset_val - base_game_x)
                        visual_updated_for_element = el_data
                    if is_y_offset and base_game_y is not None:
                        el_data['original_y'] = float(gui_ref_y) + (new_game_offset_val - base_game_y)
                        visual_updated_for_element = el_data 
                
                if visual_updated_for_element:
                    logging.info(f"Comp: Visual for {el_data.get('display_tag')} updated from Entry to ({el_data['original_x']:.1f}, {el_data['original_y']:.1f})")
                    leader_tag = visual_updated_for_element.get('display_tag')
                    if leader_tag: # If this element is a leader, update its followers
                        for follower_elem in composite_elements:
                            if follower_elem.get('conjoined_to_tag') == leader_tag:
                                follower_elem['original_x'] = visual_updated_for_element['original_x'] + follower_elem.get('relative_offset_x', 0)
                                follower_elem['original_y'] = visual_updated_for_element['original_y'] + follower_elem.get('relative_offset_y', 0)
                    break 
        if visual_updated_for_element: redraw_composite_view()

def increment_value(event, str_var, direction): # (No change from previous, calls update_value)
    try:
        current_val_str = str_var.get()
        if not current_val_str or current_val_str == "ERR": current_val_str = "0.0"
        value_float = float(current_val_str)
        increment_amt = 0.1 if event.state & 0x0001 else 1.0 
        if event.state & 0x0004: increment_amt = 0.01
        if direction == 'Up': value_float += increment_amt
        elif direction == 'Down': value_float -= increment_amt
        str_var.set(f"{value_float:.4f}") 
    except ValueError:
        update_status("Invalid value for increment", "red")

def update_color_preview_from_entry(off_key, str_var, from_undo_redo=False): # Added from_undo_redo, updates asterisk
    global original_loaded_colors
    hex_str = str_var.get()
    valid_hex = False
    if len(hex_str)==7 and hex_str.startswith('#'):
        try:
            int(hex_str[1:],16); valid_hex = True
            if hasattr(root,'color_previews') and off_key in root.color_previews: 
                root.color_previews[off_key].config(bg=hex_str)
            if not from_undo_redo: update_status("Color preview updated","blue")
            if composite_mode_active: redraw_composite_view() 
        except ValueError: 
            if not from_undo_redo: update_status("Bad hex color","red")
    elif not from_undo_redo and len(hex_str)>0 and not hex_str.startswith('#') and \
         all(c in "0123456789abcdefABCDEF" for c in hex_str) and len(hex_str)<=6:
        str_var.set("#"+hex_str); update_color_preview_from_entry(off_key,str_var, from_undo_redo) 
    if off_key in root.asterisk_labels:
        original_color = original_loaded_colors.get(off_key)
        is_changed = (original_color != hex_str) if valid_hex else True
        root.asterisk_labels[off_key].config(text="*" if is_changed else "")

def choose_color(off_key, str_var, preview_widget): # (Same - already handles undo and calls update_color_preview_from_entry)
    old_color = str_var.get()
    curr_hex = old_color
    if not (curr_hex.startswith("#") and len(curr_hex)==7): curr_hex="#000000"
    new_color_tuple = colorchooser.askcolor(initialcolor=curr_hex)
    if new_color_tuple and new_color_tuple[1]:
        chosen_hex = new_color_tuple[1]
        entry_widget_for_color = None # Find associated entry if needed for EditAction
        if hasattr(root, 'offset_entry_widgets'): # Check if this key is for an offset entry (unlikely for color)
             entry_widget_for_color = root.offset_entry_widgets.get(off_key) 
        if old_color != chosen_hex:
            action = EditAction(str_var, old_color, chosen_hex, off_key, entry_widget_for_color, f"Choose color for {off_key}")
            undo_manager.record_action(action)
        str_var.set(chosen_hex) 
        preview_widget.config(bg=chosen_hex) 
        update_color_preview_from_entry(off_key, str_var) 
def update_status(msg, fg_col): status_label.config(text=msg, fg=fg_col) # (Same)
def about(): # (Same)
    win=tk.Toplevel(root);win.title("About");win.geometry("450x300");win.resizable(False,False) 
    tk.Label(win,text="FLP Scoreboard Editor 25 By FIFA Legacy Project.",pady=10,font=("Helvetica",12,"bold")).pack()
    tk.Label(win,text="Version 1.13 [Build 10 May 2025]",pady=10).pack() 
    tk.Label(win,text="© 2025 FIFA Legacy Project. All Rights Reserved.",pady=10).pack()
    tk.Label(win,text="Designed & Developed By Emran_Ahm3d.",pady=10).pack()
    tk.Label(win,text="Special Thanks to Riesscar, KO, MCK and Marconis for the Research.",pady=10, wraplength=400).pack() 
    tk.Label(win,text="Discord: @emran_ahm3d",pady=10).pack()
def show_documentation(): webbrowser.open("https://soccergaming.com/") # (Same)
def restrict_color_entry(event, str_var): # (Same)
    if event.char and event.char not in "#0123456789abcdefABCDEF" and len(str_var.get())==0 and event.char!='#': return 'break'
    if len(str_var.get())>=7 and event.char and event.widget.select_present() == 0 : return 'break'
def exit_app(): # (Same)
    if messagebox.askyesno("Exit","Are you sure?"): root.destroy()
def import_texture(): # (Same Placeholder)
    messagebox.showinfo("Placeholder", "Full import logic here.")
    if file_path: extract_and_display_texture()
def export_selected_file(): # (Same Placeholder)
    messagebox.showinfo("Placeholder", "Full export logic here.")
def previous_image(): # (Same - smarter browsing)
    global current_image_index, composite_mode_active
    if composite_mode_active or not file_path or not image_files: return
    original_idx = current_image_index; num_files = len(image_files)
    if num_files == 0: return
    for i in range(num_files):
        current_image_index = (original_idx - 1 - i + num_files*2) % num_files 
        if extract_and_display_texture(): return
    current_image_index = original_idx 
    if not extract_and_display_texture(): preview_canvas.delete("all"); texture_label.config(text="No displayable textures"); current_image=None
def next_image(): # (Same - smarter browsing)
    global current_image_index, composite_mode_active
    if composite_mode_active or not file_path or not image_files: return
    original_idx = current_image_index; num_files = len(image_files)
    if num_files == 0: return
    for i in range(num_files):
        current_image_index = (original_idx + 1 + i) % num_files
        if extract_and_display_texture(): return
    current_image_index = original_idx
    if not extract_and_display_texture(): preview_canvas.delete("all"); texture_label.config(text="No displayable textures"); current_image=None
def toggle_preview_background(): # (Same)
    global preview_bg_color_is_white, composite_mode_active
    if composite_mode_active: return
    preview_bg_color_is_white = not preview_bg_color_is_white
    if file_path and current_image : redraw_single_view_image()

# --- Composite Mode Functions ---
def toggle_composite_mode(): # MODIFIED: No "Switched to 10.dds" status message. Initial pan.
    global composite_mode_active, current_image_index, image_files, current_image
    global composite_zoom_level, composite_pan_offset_x, composite_pan_offset_y
    global import_button, export_button, highlighted_offset_entries

    logging.info(f"Toggling composite mode. Current state: {composite_mode_active}")

    if not composite_mode_active: 
        is_internal_name_ok = internal_name_label.cget("text").startswith("Internal Name: ") and \
                              not internal_name_label.cget("text").endswith("(No Config)") and \
                              not internal_name_label.cget("text").endswith("(Detection Failed)")
        if not file_path or not is_internal_name_ok:
            messagebox.showinfo("Info", "Load a .big file with a valid internal name config first.")
            logging.warning("Prerequisites for composite mode not met (file/internal name)."); return

        if not (0 <= current_image_index < len(image_files) and image_files[current_image_index] == "10"):
            logging.info("Not on 10.dds. Attempting to switch.")
            try:
                idx_10 = image_files.index("10")
                current_image_index = idx_10
                if not extract_and_display_texture(): 
                    messagebox.showerror("Error", "Could not display 10.dds. Cannot enter composite mode.")
                    logging.error("Failed to display 10.dds for composite mode entry."); return
                # update_status("Switched to 10.dds for composite mode", "blue") # Removed status
                root.update_idletasks()
            except ValueError: messagebox.showerror("Error","'10' not found in image_files. Cannot enter composite."); return
        
        preview_canvas.delete("all"); current_image = None 
        texture_label.config(text=""); image_dimensions_label.config(text="")
        
        composite_mode_active = True
        composite_zoom_level = 1.0
        # Initial pan to show more down-right. Adjust these values as needed.
        # Negative X pans left (shows right), Negative Y pans up (shows bottom)
        composite_pan_offset_x = 250.0 
        composite_pan_offset_y = 50.0  
        display_composite_view() 
        
        if not composite_mode_active: logging.warning("display_composite_view failed."); return 
        
        composite_view_button.config(text="Single View")
        left_arrow_button.pack_forget(); right_arrow_button.pack_forget()
        import_button.config(state=tk.DISABLED); export_button.config(state=tk.DISABLED)
        logging.info("Switched TO composite mode successfully.")
    else: 
        clear_all_highlights()
        logging.info("Attempting to switch FROM composite mode.")
        composite_mode_active = False; clear_composite_view()
        composite_view_button.config(text="Composite View")
        left_arrow_button.pack(side=tk.LEFT, padx=(0,5), pady=5, anchor='center')
        right_arrow_button.pack(side=tk.LEFT, padx=5, pady=5, anchor='center')
        import_button.config(state=tk.NORMAL); export_button.config(state=tk.NORMAL)
        if file_path: extract_and_display_texture() 
        else: preview_canvas.delete("all"); texture_label.config(text="No file loaded"); image_dimensions_label.config(text="")
        logging.info("Switched FROM composite mode.")

def clear_all_highlights(): # (Same)
    global highlighted_offset_entries
    for entry_widget, original_bg in highlighted_offset_entries:
        try: entry_widget.config(bg=original_bg)
        except tk.TclError: pass
    highlighted_offset_entries.clear()

def clear_composite_view(): # (Same)
    global composite_elements, preview_canvas
    preview_canvas.delete("composite_item")
    for el in composite_elements:
        if 'tk_image_ref' in el and el['tk_image_ref']: del el['tk_image_ref'] 
    composite_elements.clear(); preview_canvas.config(bg="#CCCCCC")

def redraw_composite_view(): # (Same - handles dynamic text color)
    global composite_elements, preview_canvas, composite_zoom_level, composite_pan_offset_x, composite_pan_offset_y
    global colors, root 
    preview_canvas.delete("composite_item") 
    canvas_w = preview_canvas.winfo_width(); canvas_h = preview_canvas.winfo_height()
    if canvas_w <= 1: canvas_w = 580; canvas_h = 150
    view_origin_x = canvas_w / 2 - composite_pan_offset_x * composite_zoom_level
    view_origin_y = canvas_h / 2 - composite_pan_offset_y * composite_zoom_level
    for el_data in composite_elements:
        el_data['current_x'] = view_origin_x + el_data['original_x'] * composite_zoom_level
        el_data['current_y'] = view_origin_y + el_data['original_y'] * composite_zoom_level
        draw_x = el_data['current_x']; draw_y = el_data['current_y']
        if el_data.get('type') == "text":
            base_font_size = el_data.get('base_font_size', DEFAULT_TEXT_BASE_FONT_SIZE)
            zoomed_font_size = max(1, int(base_font_size * composite_zoom_level))
            font_family = el_data.get('font_family', DEFAULT_TEXT_FONT_FAMILY)
            text_color = DEFAULT_TEXT_COLOR_FALLBACK 
            color_label = el_data.get('color_offset_label')
            if color_label and color_label in colors and hasattr(root, 'color_vars'):
                color_key_tuple = tuple(colors[color_label]) 
                if color_key_tuple in root.color_vars:
                    current_hex = root.color_vars[color_key_tuple].get()
                    if current_hex and current_hex.startswith("#") and len(current_hex) == 7:
                        text_color = current_hex
                    else: logging.warning(f"Invalid hex '{current_hex}' for '{color_label}'. Using fallback.")
                else: logging.warning(f"Var for key {color_key_tuple} (label: {color_label}) not in root.color_vars.")
            elif color_label: logging.warning(f"Color label '{color_label}' not found in global 'colors' dict.")
            item_id = preview_canvas.create_text(int(draw_x), int(draw_y), anchor=tk.NW,
                                                 text=el_data['text_content'],
                                                 font=(font_family, zoomed_font_size, "bold"),
                                                 fill=text_color,
                                                 tags=("composite_item", el_data['display_tag']))
            el_data['canvas_id'] = item_id
        elif el_data.get('type') == "image":
            pil_img = el_data['pil_image']
            zoomed_w = int(pil_img.width * composite_zoom_level); zoomed_h = int(pil_img.height * composite_zoom_level)
            if zoomed_w <= 0 or zoomed_h <= 0: continue
            try:
                resized_pil = pil_img.resize((zoomed_w, zoomed_h), Image.LANCZOS)
                el_data['tk_image_ref'] = ImageTk.PhotoImage(resized_pil)
                item_id = preview_canvas.create_image(int(draw_x), int(draw_y), anchor=tk.NW, 
                                                      image=el_data['tk_image_ref'], 
                                                      tags=("composite_item", el_data['display_tag']))
                el_data['canvas_id'] = item_id 
            except Exception as e_redraw_img: logging.error(f"Redraw img {el_data.get('display_tag')}: {e_redraw_img}")
        else: logging.warning(f"Unknown element type: {el_data.get('type')}")

def display_composite_view(): # MODIFIED: Initial visual positions from GUI_Ref + Deviation.
    global composite_elements, preview_canvas, file_path, composite_mode_active
    global initial_text_elements_config, predefined_image_coords, offsets, root 
    
    logging.info("Displaying composite view (Visuals relative to game data deviation).")
    if not file_path: composite_mode_active=False; return
    preview_canvas.config(bg="gray70")

    try:
        big_file = FifaBigFile(file_path)
        if not read_internal_name(file_path): composite_mode_active=False; return
        canvas_w=preview_canvas.winfo_width(); canvas_h=preview_canvas.winfo_height()
        if canvas_w<=1: canvas_w=580; canvas_h=150
        
        images_to_load_config = [("10","10"), ("14","14"), ("30","30_orig"), ("30","30_dup")]
        source_entries_map = {e.name:e for e in big_file.entries if e.name in ["10","14","30"] and e.file_type=="DDS" and e.data}
        
        temp_composite_elements_dict: Dict[str, Dict[str, Any]] = {}
        
        for name_to_find, display_suffix in images_to_load_config:
            if name_to_find not in source_entries_map: continue
            entry=source_entries_map[name_to_find]; temp_dds_path=None
            try:
                with tempfile.NamedTemporaryFile(delete=False,suffix=".dds") as tmp_f:
                    tmp_f.write(entry.data); temp_dds_path=tmp_f.name
                pil_img=Image.open(temp_dds_path).convert("RGBA")
                current_display_tag = f"img_{display_suffix}"

                img_config_tuple = predefined_image_coords.get(current_display_tag)
                if not img_config_tuple: 
                    logging.error(f"Missing predefined_image_coords for {current_display_tag}. Skipping."); continue
                
                gui_ref_x, gui_ref_y, img_x_offset_label, base_game_img_x, img_y_offset_label, base_game_img_y = img_config_tuple
                
                current_original_x = float(gui_ref_x) 
                current_original_y = float(gui_ref_y)
                img_x_var_linked = None; img_y_var_linked = None

                if img_x_offset_label and img_y_offset_label and base_game_img_x is not None and base_game_img_y is not None and \
                   hasattr(root, 'offsets_vars') and offsets:
                    if img_x_offset_label in offsets and img_y_offset_label in offsets:
                        x_key = tuple(offsets[img_x_offset_label]); y_key = tuple(offsets[img_y_offset_label])
                        if x_key in root.offsets_vars and y_key in root.offsets_vars:
                            img_x_var_linked = root.offsets_vars[x_key]; img_y_var_linked = root.offsets_vars[y_key]
                            try:
                                current_game_x = float(img_x_var_linked.get())
                                current_game_y = float(img_y_var_linked.get())
                                deviation_x = current_game_x - base_game_img_x
                                deviation_y = current_game_y - base_game_img_y
                                current_original_x = float(gui_ref_x) + deviation_x 
                                current_original_y = float(gui_ref_y) + deviation_y
                            except ValueError: img_x_var_linked=None; img_y_var_linked=None 
                
                is_fixed_image = (display_suffix == "10") 
                # img_14 will be marked fixed during conjoining setup

                element_data = {'type':"image",'pil_image':pil_img,
                                'original_x':current_original_x,'original_y':current_original_y,
                                'current_x':current_original_x,'current_y':current_original_y,
                                'image_name':entry.name, 'display_tag':current_display_tag,
                                'tk_image_ref':None,'canvas_id':None, 'is_fixed': is_fixed_image,
                                'x_offset_label_linked': img_x_offset_label, 
                                'y_offset_label_linked': img_y_offset_label,
                                'x_var_linked': img_x_var_linked, 'y_var_linked': img_y_var_linked,
                                'base_game_x': base_game_img_x, 'base_game_y': base_game_img_y,
                                'gui_ref_x': gui_ref_x, 'gui_ref_y': gui_ref_y 
                               }
                temp_composite_elements_dict[current_display_tag] = element_data
            except Exception as e_img: logging.error(f"Error prep img {entry.name}({display_suffix}): {e_img}")
            finally:
                if temp_dds_path and os.path.exists(temp_dds_path): os.remove(temp_dds_path)

        for tag, text, gui_ref_x, gui_ref_y, size_override, color_label, is_fixed_text, x_offset_label, base_game_x, y_offset_label, base_game_y in initial_text_elements_config:
            current_original_x = float(gui_ref_x) 
            current_original_y = float(gui_ref_y)
            x_var_linked = None; y_var_linked = None

            if x_offset_label and y_offset_label and base_game_x is not None and base_game_y is not None and \
               hasattr(root, 'offsets_vars') and offsets:
                if x_offset_label in offsets and y_offset_label in offsets:
                    x_key_tuple = tuple(offsets[x_offset_label]); y_key_tuple = tuple(offsets[y_offset_label])
                    if x_key_tuple in root.offsets_vars and y_key_tuple in root.offsets_vars:
                        x_var_linked = root.offsets_vars[x_key_tuple]
                        y_var_linked = root.offsets_vars[y_key_tuple]
                        try:
                            current_game_offset_x = float(x_var_linked.get())
                            current_game_offset_y = float(y_var_linked.get())
                            deviation_x = current_game_offset_x - base_game_x
                            deviation_y = current_game_offset_y - base_game_y
                            current_original_x = float(gui_ref_x) + deviation_x 
                            current_original_y = float(gui_ref_y) + deviation_y
                        except ValueError: x_var_linked = None; y_var_linked = None 
            
            element_data = {'type':"text",'text_content':text,
                            'original_x':current_original_x,'original_y':current_original_y,
                            'current_x':current_original_x,'current_y':current_original_y,
                            'base_font_size':size_override or DEFAULT_TEXT_BASE_FONT_SIZE,
                            'font_family':DEFAULT_TEXT_FONT_FAMILY, 'color_offset_label': color_label, 
                            'display_tag':tag,'canvas_id':None, 'is_fixed': is_fixed_text,
                            'x_offset_label_linked': x_offset_label, 'y_offset_label_linked': y_offset_label,
                            'x_var_linked': x_var_linked, 'y_var_linked': y_var_linked,
                            'base_game_x': base_game_x, 'base_game_y': base_game_y,
                            'gui_ref_x': gui_ref_x, 'gui_ref_y': gui_ref_y
                           }
            temp_composite_elements_dict[tag] = element_data
        
        leader_tag_for_img14 = "text_added_time"; follower_tag_img14 = "img_14"
        if leader_tag_for_img14 in temp_composite_elements_dict and follower_tag_img14 in temp_composite_elements_dict:
            leader_el = temp_composite_elements_dict[leader_tag_for_img14]
            follower_el = temp_composite_elements_dict[follower_tag_img14]
            
            img14_gui_ref_x = predefined_image_coords[follower_tag_img14][0]
            img14_gui_ref_y = predefined_image_coords[follower_tag_img14][1]
            
            text_added_time_cfg = next(item for item in initial_text_elements_config if item[0] == leader_tag_for_img14)
            text_added_time_gui_ref_x = text_added_time_cfg[2]
            text_added_time_gui_ref_y = text_added_time_cfg[3]

            design_relative_offset_x = img14_gui_ref_x - text_added_time_gui_ref_x
            design_relative_offset_y = img14_gui_ref_y - text_added_time_gui_ref_y

            follower_el['original_x'] = leader_el['original_x'] + design_relative_offset_x
            follower_el['original_y'] = leader_el['original_y'] + design_relative_offset_y
            
            follower_el['conjoined_to_tag'] = leader_tag_for_img14
            follower_el['relative_offset_x'] = design_relative_offset_x 
            follower_el['relative_offset_y'] = design_relative_offset_y
            follower_el['is_fixed'] = True 
            if not any(item[0] == leader_tag_for_img14 and item[6] for item in initial_text_elements_config):
                 leader_el['is_fixed'] = False # Ensure leader is draggable if not explicitly fixed in its own config
        
        composite_elements = list(temp_composite_elements_dict.values())
        redraw_composite_view()
        texture_label.config(text="Composite Mode Active"); image_dimensions_label.config(text=f"Canvas: {canvas_w}x{canvas_h}")
    except Exception as e:
        messagebox.showerror("Composite Err",f"Display fail: {e}")
        logging.error(f"CRITICAL Comp display error: {e}", exc_info=True)
        composite_mode_active = False; toggle_composite_mode()

def zoom_composite_view(event): # (Same)
    global composite_zoom_level, composite_pan_offset_x, composite_pan_offset_y, preview_canvas
    if not composite_elements: return
    factor = 1.1 if event.delta > 0 else (1/1.1); new_zoom = max(0.05, min(composite_zoom_level * factor, 10.0))
    canvas_w=preview_canvas.winfo_width(); canvas_h=preview_canvas.winfo_height()
    mouse_x_rel_center = event.x - canvas_w / 2; mouse_y_rel_center = event.y - canvas_h / 2
    if abs(composite_zoom_level)>1e-6 and abs(new_zoom)>1e-6:
        composite_pan_offset_x += mouse_x_rel_center * (1.0/composite_zoom_level - 1.0/new_zoom)
        composite_pan_offset_y += mouse_y_rel_center * (1.0/composite_zoom_level - 1.0/new_zoom)
    composite_zoom_level = new_zoom
    redraw_composite_view()

def start_pan_composite(event): # (Same)
    global drag_data
    drag_data["is_panning_rmb"] = True 
    drag_data["x"] = event.x; drag_data["y"] = event.y
    logging.debug(f"start_pan_composite: RMB PANNING started at ({event.x},{event.y})")

def on_pan_composite(event): # (Same)
    global drag_data, composite_pan_offset_x, composite_pan_offset_y, composite_zoom_level
    if not drag_data.get("is_panning_rmb"): return
    dx = event.x - drag_data["x"]; dy = event.y - drag_data["y"]
    if abs(composite_zoom_level) > 1e-6: 
        composite_pan_offset_x -= dx / composite_zoom_level 
        composite_pan_offset_y -= dy / composite_zoom_level
    drag_data["x"] = event.x; drag_data["y"] = event.y
    redraw_composite_view()

def start_drag_composite(event): # (Same - already stores initial game offsets)
    global composite_drag_data, composite_elements, drag_data, highlighted_offset_entries, offsets, root
    clear_all_highlights()
    if event.num == 3: start_pan_composite(event); return
    drag_data["is_panning"] = False; drag_data["is_panning_rmb"] = False
    item_tuple = event.widget.find_closest(event.x,event.y)
    if not item_tuple: composite_drag_data['item']=None; return
    item_id = item_tuple[0]
    if "composite_item" not in preview_canvas.gettags(item_id):
        composite_drag_data['item']=None; return
    for el_data in composite_elements:
        if el_data.get('canvas_id') == item_id:
            if el_data.get('is_fixed', False): 
                logging.info(f"Attempted to drag fixed item: {el_data.get('display_tag')}")
                composite_drag_data['item'] = None; return 
            initial_game_x, initial_game_y = 0.0, 0.0 
            x_var = el_data.get('x_var_linked')
            y_var = el_data.get('y_var_linked')
            if x_var and y_var: 
                try: initial_game_x = float(x_var.get()); initial_game_y = float(y_var.get())
                except ValueError: logging.warning(f"Could not parse initial game offsets for {el_data.get('display_tag')}. Using 0,0.")
            composite_drag_data.update({'item':item_id, 'x':event.x, 'y':event.y, 'element_data':el_data,
                                        'start_original_x': el_data['original_x'], 'start_original_y': el_data['original_y'],
                                        'initial_game_offset_x_at_drag_start': initial_game_x, 
                                        'initial_game_offset_y_at_drag_start': initial_game_y })
            preview_canvas.tag_raise(item_id)
            x_label = el_data.get('x_offset_label_linked'); y_label = el_data.get('y_offset_label_linked')
            if x_label and x_label in offsets and hasattr(root, 'offset_entry_widgets'):
                x_key = tuple(offsets[x_label])
                if x_key in root.offset_entry_widgets:
                    entry_w = root.offset_entry_widgets[x_key]
                    highlighted_offset_entries.append((entry_w, entry_w.cget("background"))); entry_w.config(bg="lightyellow")
            if y_label and y_label in offsets and hasattr(root, 'offset_entry_widgets'):
                y_key = tuple(offsets[y_label])
                if y_key in root.offset_entry_widgets:
                    entry_w = root.offset_entry_widgets[y_key]
                    highlighted_offset_entries.append((entry_w, entry_w.cget("background"))); entry_w.config(bg="lightyellow")
            return
    composite_drag_data['item']=None

def on_drag_composite(event): # (Same - already handles relative game offset updates 1:1)
    global composite_drag_data, composite_zoom_level, drag_data, composite_elements, offsets
    if event.num == 3 or drag_data.get("is_panning_rmb"): on_pan_composite(event); return
    if composite_drag_data.get('item') is None or drag_data.get("is_panning"): return 
    dragged_elem_data = composite_drag_data.get('element_data')
    if not dragged_elem_data: return
    mouse_dx_canvas = event.x - composite_drag_data['x']
    mouse_dy_canvas = event.y - composite_drag_data['y']
    if abs(composite_zoom_level) < 1e-6: return 
    delta_visual_original_x = mouse_dx_canvas / composite_zoom_level 
    delta_visual_original_y = mouse_dy_canvas / composite_zoom_level
    new_visual_original_x = composite_drag_data['start_original_x'] + delta_visual_original_x
    new_visual_original_y = composite_drag_data['start_original_y'] + delta_visual_original_y
    dragged_elem_data['original_x'] = new_visual_original_x
    dragged_elem_data['original_y'] = new_visual_original_y
    log_message_suffix = f"dragged to canvas original (X:{new_visual_original_x:.2f}, Y:{new_visual_original_y:.2f})"
    x_var_linked = dragged_elem_data.get('x_var_linked')
    y_var_linked = dragged_elem_data.get('y_var_linked')
    if x_var_linked and y_var_linked: 
        initial_game_x = composite_drag_data['initial_game_offset_x_at_drag_start']
        initial_game_y = composite_drag_data['initial_game_offset_y_at_drag_start']
        new_game_offset_x = initial_game_x + delta_visual_original_x 
        new_game_offset_y = initial_game_y + delta_visual_original_y
        old_x_str = x_var_linked.get(); old_y_str = y_var_linked.get() 
        x_var_linked.set(f"{new_game_offset_x:.2f}"); y_var_linked.set(f"{new_game_offset_y:.2f}")
        logging.info(f"  -> For '{dragged_elem_data.get('display_tag')}': Linked Game Offsets set to X={new_game_offset_x:.2f}, Y={new_game_offset_y:.2f} (relative to start)")
        x_offset_label = dragged_elem_data.get('x_offset_label_linked'); y_offset_label = dragged_elem_data.get('y_offset_label_linked')
        if x_offset_label and x_offset_label in offsets:
            x_key_tuple = tuple(offsets[x_offset_label])
            if old_x_str != x_var_linked.get(): 
                action_x = EditAction(x_var_linked, old_x_str, x_var_linked.get(), x_key_tuple, root.offset_entry_widgets.get(x_key_tuple), f"Drag {dragged_elem_data.get('display_tag')} X")
                undo_manager.record_action(action_x)
            update_value(x_key_tuple, x_var_linked, from_undo_redo=True) 
        if y_offset_label and y_offset_label in offsets:
            y_key_tuple = tuple(offsets[y_offset_label])
            if old_y_str != y_var_linked.get():
                action_y = EditAction(y_var_linked, old_y_str, y_var_linked.get(), y_key_tuple, root.offset_entry_widgets.get(y_key_tuple), f"Drag {dragged_elem_data.get('display_tag')} Y")
                undo_manager.record_action(action_y)
            update_value(y_key_tuple, y_var_linked, from_undo_redo=True) 
    if dragged_elem_data.get('type') == "text": logging.info(f"Text '{dragged_elem_data.get('display_tag')}' {log_message_suffix}")
    elif dragged_elem_data.get('type') == "image": logging.info(f"Image '{dragged_elem_data.get('display_tag')}' {log_message_suffix}")
    dragged_tag = dragged_elem_data.get('display_tag')
    if dragged_tag:
        for follower_elem in composite_elements:
            if follower_elem.get('conjoined_to_tag') == dragged_tag:
                follower_elem['original_x'] = dragged_elem_data['original_x'] + follower_elem.get('relative_offset_x', 0)
                follower_elem['original_y'] = dragged_elem_data['original_y'] + follower_elem.get('relative_offset_y', 0)
    redraw_composite_view()

def on_drag_release_composite(event): # Same
    global drag_data
    if event.num == 3: drag_data["is_panning_rmb"] = False; logging.debug("RMB Pan released")

# --- UI Setup --- (Same)
root = tk.Tk()
root.title("FLP Scoreboard Editor 25 (v1.13)") 
root.geometry("930x710"); root.resizable(False, False)
menubar = tk.Menu(root); filemenu = tk.Menu(menubar, tearoff=0); filemenu.add_command(label="Open", command=open_file, accelerator="Ctrl+O"); filemenu.add_command(label="Save", command=save_file, accelerator="Ctrl+S"); filemenu.add_separator(); filemenu.add_command(label="Exit", command=exit_app); menubar.add_cascade(label="File", menu=filemenu)
editmenu = tk.Menu(menubar, tearoff=0); editmenu.add_command(label="Undo", command=lambda: undo_manager.undo(), accelerator="Ctrl+Z", state=tk.DISABLED); editmenu.add_command(label="Redo", command=lambda: undo_manager.redo(), accelerator="Ctrl+Y", state=tk.DISABLED); menubar.add_cascade(label="Edit", menu=editmenu); root.editmenu = editmenu
root.bind_all("<Control-z>", lambda event: undo_manager.undo()); root.bind_all("<Control-y>", lambda event: undo_manager.redo())
helpmenu = tk.Menu(menubar, tearoff=0); helpmenu.add_command(label="About", command=about); helpmenu.add_separator(); helpmenu.add_command(label="Documentation", command=show_documentation); menubar.add_cascade(label="Help", menu=helpmenu); root.config(menu=menubar)
notebook = ttk.Notebook(root); positions_frame=ttk.Frame(notebook); sizes_frame=ttk.Frame(notebook); colors_frame=ttk.Frame(notebook)
notebook.add(positions_frame,text="Positions"); notebook.add(sizes_frame,text="Sizes"); notebook.add(colors_frame,text="Colors"); notebook.pack(expand=1,fill="both",padx=10,pady=5)
preview_controls_frame=tk.Frame(root); preview_controls_frame.pack(fill=tk.X,padx=10,pady=5)
left_arrow_button=ttk.Button(preview_controls_frame,text="◀",command=previous_image,width=2); left_arrow_button.pack(side=tk.LEFT,padx=(0,5),pady=5,anchor='center')
preview_canvas=tk.Canvas(preview_controls_frame,width=580,height=150,bg="#CCCCCC",relief="solid",bd=1); preview_canvas.pack(side=tk.LEFT,padx=5,pady=5,anchor='center')
preview_canvas.bind("<MouseWheel>", zoom_image_handler); preview_canvas.bind("<ButtonPress-1>", start_drag_handler); preview_canvas.bind("<B1-Motion>", on_drag_handler); preview_canvas.bind("<ButtonRelease-1>", on_drag_release_handler) 
preview_canvas.bind("<ButtonPress-3>", start_pan_composite); preview_canvas.bind("<B3-Motion>", on_pan_composite); preview_canvas.bind("<ButtonRelease-3>", on_drag_release_composite)
right_arrow_button=ttk.Button(preview_controls_frame,text="▶",command=next_image,width=2); right_arrow_button.pack(side=tk.LEFT,padx=5,pady=5,anchor='center')
vertical_buttons_frame=tk.Frame(preview_controls_frame); vertical_buttons_frame.pack(side=tk.LEFT,padx=(10,0),pady=0,anchor='n')
toggle_bg_button=ttk.Button(vertical_buttons_frame,text="Toggle Alpha",command=toggle_preview_background,width=15); toggle_bg_button.pack(side=tk.TOP,pady=(5,2)) 
composite_view_button=ttk.Button(vertical_buttons_frame,text="Composite View",command=toggle_composite_mode,width=15); composite_view_button.pack(side=tk.TOP,pady=(2,5))
texture_info_frame=tk.Frame(root); texture_info_frame.pack(fill=tk.X,padx=10,pady=(0,5))
texture_label=tk.Label(texture_info_frame,text="No texture loaded",font=('Helvetica',9),anchor='w'); texture_label.pack(side=tk.LEFT,padx=5)
image_dimensions_label=tk.Label(texture_info_frame,text=" ",font=('Helvetica',10),anchor='e'); image_dimensions_label.pack(side=tk.RIGHT,padx=10)
buttons_frame=tk.Frame(root); buttons_frame.place(relx=1.0,rely=1.0,anchor='se',x=-10,y=-85) 
bottom_frame = tk.Frame(root); bottom_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=(0,5))
status_label = tk.Label(bottom_frame, text="Ready", anchor=tk.W, fg="blue", font=('Helvetica', 10)); status_label.pack(side=tk.LEFT, padx=0)
file_path_label = tk.Label(bottom_frame, text="File: None", anchor=tk.W, font=('Helvetica', 9)); file_path_label.pack(side=tk.LEFT, padx=10) 
internal_name_label = tk.Label(bottom_frame, text="Internal Name: Not Loaded", anchor=tk.E, font=('Helvetica', 10)); internal_name_label.pack(side=tk.RIGHT, padx=0)
import_button=ttk.Button(buttons_frame,text="IMPORT",command=import_texture,width=10); import_button.pack(pady=2)
export_button=ttk.Button(buttons_frame,text="EXPORT",command=export_selected_file,width=10); export_button.pack(pady=2)
save_button_main=ttk.Button(buttons_frame,text="SAVE",command=save_file,width=10); save_button_main.pack(pady=(2,0))
root.style=ttk.Style(); root.style.configure('TButton',font=('Helvetica',10),padding=3); root.style.configure('Large.TButton',font=('Helvetica',12),padding=5)
left_arrow_button.configure(style='TButton'); right_arrow_button.configure(style='TButton'); toggle_bg_button.configure(style='TButton'); composite_view_button.configure(style='TButton')
import_button.configure(style='Large.TButton'); export_button.configure(style='Large.TButton'); save_button_main.configure(style='Large.TButton')

def on_map_event(event): # Same
    if file_path and not current_image and not composite_mode_active: extract_and_display_texture()

root.bind("<Map>", on_map_event, "+")
clear_editor_widgets()
undo_manager.update_menu_states() 
root.mainloop()