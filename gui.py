import tkinter as tk
from tkinter import filedialog, messagebox, ttk, colorchooser
import struct
import webbrowser
import os
import tempfile
import subprocess
import logging
from typing import List, Optional, Dict, Any

from PIL import Image, ImageTk

import config
from core import EditAction, UndoManager, Compression
from file_io import FifaBigFile, Compressor
from utils import format_filesize, read_internal_name

# Configure logging
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s')

class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        if not config.OFFSETS_DATA:
            logging.critical("offsets_data not loaded. Application cannot start.")
            self.root.after(100, self.root.destroy)
            return

        # --- State Variables ---
        self.file_path: Optional[str] = None
        self.offsets: Dict[str, List[int]] = {}
        self.colors: Dict[str, List[int]] = {}
        self.current_image: Optional[Image.Image] = None

        self.original_loaded_offsets: Dict[tuple, str] = {}
        self.original_loaded_colors: Dict[tuple, str] = {}

        self.preview_bg_color_is_white = True
        self.current_image_index = 0

        # Single View State
        self.single_view_zoom_level = 1.0
        self.single_view_pan_offset_x = 0.0
        self.single_view_pan_offset_y = 0.0
        self.drag_data = {"x": 0, "y": 0, "is_panning": False, "is_panning_rmb": False}

        # Composite View State
        self.composite_mode_active = False
        self.composite_elements: List[Dict[str, Any]] = []
        self.current_reference_width: Optional[int] = None
        self.current_reference_height: Optional[int] = None
        self.composite_drag_data = {
            "x": 0, "y": 0, "item": None, "element_data": None,
            "start_original_x": 0.0, "start_original_y": 0.0,
            "initial_game_offset_x_at_drag_start": 0.0,
            "initial_game_offset_y_at_drag_start": 0.0
        }
        self.composite_zoom_level = 1.0
        self.composite_pan_offset_x = 0.0
        self.composite_pan_offset_y = 0.0
        
        self.highlighted_offset_entries = []

        # --- Managers and Data ---
        self.undo_manager = UndoManager(self)
        self.offsets_data = config.OFFSETS_DATA

        # --- Widget References (for dynamic access) ---
        self.offsets_vars: Dict[tuple, tk.StringVar] = {}
        self.color_vars: Dict[tuple, tk.StringVar] = {}
        self.color_previews: Dict[tuple, tk.Label] = {}
        self.offset_entry_widgets: Dict[tuple, tk.Entry] = {}
        self.color_comboboxes: Dict[tuple, ttk.Combobox] = {}
        self.asterisk_labels: Dict[tuple, tk.Label] = {}

        # --- UI Setup ---
        self._setup_window()
        self._setup_styles()
        self._setup_menus()
        self._setup_ui_layout()
        self._setup_bindings()
        
        self.clear_editor_widgets()
        self.update_menu_states()

    def _setup_window(self):
        self.root.title("FLP Scoreboard Editor 25 (v1.13)")
        self.root.geometry("930x710")
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", self.exit_app)

    def _setup_styles(self):
        self.root.style = ttk.Style()
        self.root.style.configure('TButton', font=('Helvetica', 10), padding=3)
        self.root.style.configure('Large.TButton', font=('Helvetica', 12), padding=5)

    def _setup_menus(self):
        self.menubar = tk.Menu(self.root)
        
        # File Menu
        self.filemenu = tk.Menu(self.menubar, tearoff=0)
        self.filemenu.add_command(label="Open", command=self.open_file, accelerator="Ctrl+O")
        self.filemenu.add_command(label="Save", command=self.save_file, accelerator="Ctrl+S")
        self.filemenu.add_separator()
        self.filemenu.add_command(label="Exit", command=self.exit_app)
        self.menubar.add_cascade(label="File", menu=self.filemenu)
        
        # Edit Menu
        self.editmenu = tk.Menu(self.menubar, tearoff=0)
        self.editmenu.add_command(label="Undo", command=self.undo, accelerator="Ctrl+Z", state=tk.DISABLED)
        self.editmenu.add_command(label="Redo", command=self.redo, accelerator="Ctrl+Y", state=tk.DISABLED)
        self.menubar.add_cascade(label="Edit", menu=self.editmenu)
        
        # Help Menu
        self.helpmenu = tk.Menu(self.menubar, tearoff=0)
        self.helpmenu.add_command(label="About", command=self.about)
        self.helpmenu.add_separator()
        self.helpmenu.add_command(label="Documentation", command=self.show_documentation)
        self.menubar.add_cascade(label="Help", menu=self.helpmenu)
        
        self.root.config(menu=self.menubar)

    def _setup_ui_layout(self):
        # Notebook for editor tabs
        notebook = ttk.Notebook(self.root)
        
        # Positions Tab
        positions_frame_container = ttk.Frame(notebook)
        self.positions_canvas = tk.Canvas(positions_frame_container, highlightthickness=0)
        positions_scrollbar = ttk.Scrollbar(positions_frame_container, orient="vertical", command=self.positions_canvas.yview)
        self.positions_frame = ttk.Frame(self.positions_canvas)
        self.positions_frame.bind("<Configure>", lambda e: self.positions_canvas.configure(scrollregion=self.positions_canvas.bbox("all")))
        self.positions_canvas.create_window((0, 0), window=self.positions_frame, anchor="nw")
        self.positions_canvas.configure(yscrollcommand=positions_scrollbar.set)
        self.positions_canvas.pack(side="left", fill="both", expand=True)
        positions_scrollbar.pack(side="right", fill="y")
        notebook.add(positions_frame_container, text="Positions")

        # Sizes and Colors Tabs
        self.sizes_frame = ttk.Frame(notebook)
        notebook.add(self.sizes_frame, text="Sizes")
        self.colors_frame = ttk.Frame(notebook)
        notebook.add(self.colors_frame, text="Colors")
        
        notebook.pack(expand=1, fill="both", padx=10, pady=5)

        # Preview Area
        preview_controls_frame = tk.Frame(self.root)
        preview_controls_frame.pack(fill=tk.X, padx=10, pady=5)
        
        self.left_arrow_button = ttk.Button(preview_controls_frame, text="◀", command=self.previous_image, width=2)
        self.left_arrow_button.pack(side=tk.LEFT, padx=(0, 5), pady=5, anchor='center')
        
        self.preview_canvas = tk.Canvas(preview_controls_frame, width=580, height=150, bg="#CCCCCC", relief="solid", bd=1)
        self.preview_canvas.pack(side=tk.LEFT, padx=5, pady=5, anchor='center')
        
        self.right_arrow_button = ttk.Button(preview_controls_frame, text="▶", command=self.next_image, width=2)
        self.right_arrow_button.pack(side=tk.LEFT, padx=5, pady=5, anchor='center')

        vertical_buttons_frame = tk.Frame(preview_controls_frame)
        vertical_buttons_frame.pack(side=tk.LEFT, padx=(10, 0), pady=0, anchor='n')
        self.toggle_bg_button = ttk.Button(vertical_buttons_frame, text="Toggle Alpha", command=self.toggle_preview_background, width=15)
        self.toggle_bg_button.pack(side=tk.TOP, pady=(5, 2))
        self.composite_view_button = ttk.Button(vertical_buttons_frame, text="Composite View", command=self.toggle_composite_mode, width=15)
        self.composite_view_button.pack(side=tk.TOP, pady=(2, 5))

        # Texture Info Area
        texture_info_frame = tk.Frame(self.root)
        texture_info_frame.pack(fill=tk.X, padx=10, pady=(0, 5))
        self.texture_label = tk.Label(texture_info_frame, text="No texture loaded", font=('Helvetica', 9), anchor='w')
        self.texture_label.pack(side=tk.LEFT, padx=5)
        self.image_dimensions_label = tk.Label(texture_info_frame, text=" ", font=('Helvetica', 10), anchor='e')
        self.image_dimensions_label.pack(side=tk.RIGHT, padx=10)

        # Main Action Buttons
        buttons_frame = tk.Frame(self.root)
        buttons_frame.place(relx=1.0, rely=1.0, anchor='se', x=-10, y=-85)
        self.import_button = ttk.Button(buttons_frame, text="IMPORT", command=self.import_texture, width=10, style='Large.TButton')
        self.import_button.pack(pady=2)
        self.export_button = ttk.Button(buttons_frame, text="EXPORT", command=self.export_selected_file, width=10, style='Large.TButton')
        self.export_button.pack(pady=2)
        self.save_button_main = ttk.Button(buttons_frame, text="SAVE", command=self.save_file, width=10, style='Large.TButton')
        self.save_button_main.pack(pady=(2, 0))

        # Status Bar
        bottom_frame = tk.Frame(self.root)
        bottom_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=(0, 5))
        self.status_label = tk.Label(bottom_frame, text="Ready", anchor=tk.W, fg="blue", font=('Helvetica', 10))
        self.status_label.pack(side=tk.LEFT, padx=0)
        self.file_path_label = tk.Label(bottom_frame, text="File: None", anchor=tk.W, font=('Helvetica', 9))
        self.file_path_label.pack(side=tk.LEFT, padx=10)
        self.internal_name_label = tk.Label(bottom_frame, text="Internal Name: Not Loaded", anchor=tk.E, font=('Helvetica', 10))
        self.internal_name_label.pack(side=tk.RIGHT, padx=0)
    
    def _setup_bindings(self):
        # Global key bindings
        self.root.bind_all("<Control-o>", lambda event: self.open_file())
        self.root.bind_all("<Control-s>", lambda event: self.save_file())
        self.root.bind_all("<Control-z>", lambda event: self.undo())
        self.root.bind_all("<Control-y>", lambda event: self.redo())
        
        # Canvas bindings
        self.preview_canvas.bind("<MouseWheel>", self.zoom_image_handler)
        self.preview_canvas.bind("<ButtonPress-1>", self.start_drag_handler)
        self.preview_canvas.bind("<B1-Motion>", self.on_drag_handler)
        self.preview_canvas.bind("<ButtonRelease-1>", self.on_drag_release_handler)
        self.preview_canvas.bind("<ButtonPress-3>", self.start_pan_composite)
        self.preview_canvas.bind("<B3-Motion>", self.on_pan_composite)
        self.preview_canvas.bind("<ButtonRelease-3>", self.on_drag_release_composite)
        
        # Window event
        self.root.bind("<Map>", self.on_map_event, "+")

    # --- Undo/Redo ---
    def update_menu_states(self):
        """Updates the state of the Undo/Redo menu items."""
        self.editmenu.entryconfig("Undo", state=tk.NORMAL if self.undo_manager.can_undo() else tk.DISABLED)
        self.editmenu.entryconfig("Redo", state=tk.NORMAL if self.undo_manager.can_redo() else tk.DISABLED)

    def _apply_action(self, action: EditAction, is_undo: bool):
        """Applies an undo or redo action and updates the UI accordingly."""
        if not action: return
        logging.debug(f"Applying {'undo' if is_undo else 'redo'} for: {action}")
        
        # Set the variable's value
        action.string_var.set(action.old_value if is_undo else action.new_value)
        
        # Determine the type of variable and call the appropriate update function
        is_offset_var = any(var == action.string_var for var in self.offsets_vars.values())

        if is_offset_var:
            self.update_value(action.key_tuple, action.string_var, from_undo_redo=True)
        else: # It's a color var
            color_json_label = None
            for lbl, c_key_tuple in self.colors.items():
                if tuple(c_key_tuple) == action.key_tuple:
                    color_json_label = lbl
                    break
            
            if color_json_label in config.SPECIAL_TEXT_COLOR_LABELS:
                self.handle_special_text_color_change(action.key_tuple, action.string_var, from_undo_redo=True)
            else:
                self.update_color_preview_from_entry(action.key_tuple, action.string_var, from_undo_redo=True)

        # Focus the widget that was changed
        if action.entry_widget_ref and isinstance(action.entry_widget_ref, (tk.Entry, ttk.Combobox)):
            try:
                action.entry_widget_ref.focus_set()
                if isinstance(action.entry_widget_ref, tk.Entry):
                    action.entry_widget_ref.selection_range(0, tk.END)
            except tk.TclError:
                logging.debug("TclError focusing widget during undo/redo.")
        
        self.update_menu_states()

    def undo(self):
        """Performs an undo operation."""
        action = self.undo_manager.perform_undo()
        self._apply_action(action, is_undo=True)

    def redo(self):
        """Performs a redo operation."""
        action = self.undo_manager.perform_redo()
        self._apply_action(action, is_undo=False)

    # --- File Operations ---
    def open_file(self):
        fp_temp = filedialog.askopenfilename(filetypes=[("FIFA Big Files", "*.big")])
        if fp_temp:
            self.file_path = fp_temp
            self.current_image_index = 0
            self.undo_manager.clear_history()
            self.original_loaded_offsets.clear()
            self.original_loaded_colors.clear()
            if hasattr(self, 'asterisk_labels'):
                for al in self.asterisk_labels.values(): al.config(text="")
            
            self.file_path_label.config(text=f"File: {os.path.basename(self.file_path)}")
            self.add_internal_name()
            
            is_ok = self.internal_name_label.cget("text").startswith("Internal Name: ") and \
                    not self.internal_name_label.cget("text").endswith("(No Config)") and \
                    not self.internal_name_label.cget("text").endswith("(Detection Failed)")
            
            if self.composite_mode_active:
                is_comp_eligible = (self.file_path and 0 <= self.current_image_index < len(config.IMAGE_FILES) and config.IMAGE_FILES[self.current_image_index] == "10")
                if not is_comp_eligible or not is_ok:
                    self.toggle_composite_mode()
                else:
                    self.display_composite_view()
            else:
                if is_ok:
                    self.extract_and_display_texture()
                else:
                    self.preview_canvas.delete("all")
                    self.current_image = None
                    self.texture_label.config(text="Load .big / Invalid internal name")
                    self.image_dimensions_label.config(text="")
        elif not self.file_path:
            self.file_path_label.config(text="File: None")

    def save_file(self):
        if not self.file_path:
            messagebox.showerror("Error", "No file is currently open.")
            return
        if not hasattr(self, 'offsets_vars') or not hasattr(self, 'color_vars'):
            messagebox.showerror("Error", "Data is not initialized. Cannot save.")
            return

        try:
            with open(self.file_path, 'r+b') as f:
                # Save numerical offsets
                for off_key, var_obj in self.offsets_vars.items():
                    val_str = var_obj.get()
                    try:
                        val_f = float(val_str)
                        packed = struct.pack('<f', val_f)
                    except ValueError:
                        messagebox.showerror("Save Error", f"Invalid float value '{val_str}' for offset {off_key}. Save aborted.")
                        return
                    for addr in off_key:
                        f.seek(addr)
                        f.write(packed)
                    self.original_loaded_offsets[off_key] = val_str
                    if off_key in self.asterisk_labels: self.asterisk_labels[off_key].config(text="")

                # Save colors
                for color_label, off_tuple_list in self.colors.items():
                    off_key = tuple(off_tuple_list)
                    if off_key not in self.color_vars: continue
                    var_obj = self.color_vars[off_key]
                    
                    if color_label in config.SPECIAL_TEXT_COLOR_LABELS:
                        text_val = var_obj.get()
                        if text_val in ["WHITE", "BLACK"]:
                            bytes_to_write = text_val.encode('ascii').ljust(5, b'\x00')[:5]
                            for addr in off_key:
                                f.seek(addr)
                                f.write(bytes_to_write)
                            self.original_loaded_colors[off_key] = text_val
                        else:
                            messagebox.showerror("Save Error", f"Invalid text color '{text_val}' for '{color_label}'. Save aborted.")
                            return
                    else: # Regular hex color
                        hex_str = var_obj.get()
                        if not (len(hex_str) == 7 and hex_str.startswith('#')):
                            messagebox.showerror("Save Error", f"Invalid hex color '{hex_str}' for '{color_label}'. Save aborted.")
                            return
                        try:
                            r, g, b = int(hex_str[1:3], 16), int(hex_str[3:5], 16), int(hex_str[5:7], 16)
                            bgra = bytes([b, g, r, 0xFF])
                        except ValueError:
                            messagebox.showerror("Save Error", f"Invalid hex value in '{hex_str}' for '{color_label}'. Save aborted.")
                            return
                        for addr in off_key:
                            f.seek(addr)
                            f.write(bgra)
                        self.original_loaded_colors[off_key] = hex_str
                    
                    if off_key in self.asterisk_labels: self.asterisk_labels[off_key].config(text="")

            self.update_status("File saved successfully.", "green")
            self.undo_manager.clear_history()
        except Exception as e:
            messagebox.showerror("Save Error", f"An error occurred while saving the file: {e}")
            logging.error(f"File save failed: {e}", exc_info=True)


    def import_texture(self):
        if not self.file_path:
            messagebox.showerror("Error", "No .big file loaded.")
            return
        if self.composite_mode_active:
            messagebox.showinfo("Info", "Import/Export is disabled in Composite View mode.")
            return

        try:
            big_file_obj = FifaBigFile(self.file_path)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to read BIG file for import: {e}")
            logging.error(f"BIG read error during import: {e}", exc_info=True)
            return

        if not config.IMAGE_FILES or not (0 <= self.current_image_index < len(config.IMAGE_FILES)):
            messagebox.showerror("Error", "No valid texture selected for import.")
            return

        file_name_to_replace = config.IMAGE_FILES[self.current_image_index]
        original_entry_obj = next((entry for entry in big_file_obj.entries if entry.name == file_name_to_replace), None)

        if original_entry_obj is None:
            messagebox.showerror("Error", f"File '{file_name_to_replace}' not found in BIG archive.")
            return

        new_texture_path = filedialog.askopenfilename(
            title=f"Import texture for {file_name_to_replace}.dds",
            filetypes=[("Image Files", "*.png;*.dds"), ("PNG Files", "*.png"), ("DDS Files", "*.dds")]
        )
        if not new_texture_path: return

        new_data_uncompressed = None
        try:
            if new_texture_path.lower().endswith(".png"):
                if not os.path.isfile(config.TEXCONV_PATH):
                    messagebox.showerror("Dependency Missing", f"'texconv.exe' not found at:\n{config.TEXCONV_PATH}\nIt is required for PNG conversion.")
                    logging.error(f"texconv.exe not found at path: {config.TEXCONV_PATH}")
                    return

                with tempfile.TemporaryDirectory() as temp_dir:
                    try:
                        creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
                        proc = subprocess.run(
                            [config.TEXCONV_PATH, "-y", "-f", "BC3_UNORM", "-o", temp_dir, new_texture_path],
                            check=True, capture_output=True, text=True, creationflags=creationflags
                        )
                        logging.info(f"texconv.exe ran for '{new_texture_path}'.\nstdout: {proc.stdout.strip()}")
                        
                        dds_filename = os.path.splitext(os.path.basename(new_texture_path))[0] + ".dds"
                        converted_dds_path = os.path.join(temp_dir, dds_filename)

                        if not os.path.exists(converted_dds_path):
                            messagebox.showerror("Conversion Error", "texconv.exe ran, but the output DDS file was not found.\nCheck logs for details.")
                            logging.error(f"texconv output file missing. Expected at: {converted_dds_path}")
                            return

                        with open(converted_dds_path, 'rb') as f_dds_read:
                            new_data_uncompressed = f_dds_read.read()
                        logging.info("Successfully converted PNG to DDS using texconv.exe.")
                    except subprocess.CalledProcessError as e_texconv:
                        error_details = f"texconv.exe failed with return code {e_texconv.returncode}.\n\nStderr:\n{e_texconv.stderr}\n\nStdout:\n{e_texconv.stdout}"
                        messagebox.showerror("PNG Conversion Error", f"Failed to convert PNG to DDS.\n\n{error_details}")
                        logging.error(f"texconv.exe execution failed: {error_details}")
                        return

            elif new_texture_path.lower().endswith(".dds"):
                with open(new_texture_path, 'rb') as new_f:
                    new_data_uncompressed = new_f.read()
                logging.info(f"Read DDS {new_texture_path} for import.")
            else:
                messagebox.showerror("Error", "Unsupported file type. Please select a DDS or PNG file.")
                return

            if not new_data_uncompressed:
                messagebox.showerror("Error", "Failed to read or convert the new texture data.")
                return

            data_to_write_in_big = new_data_uncompressed
            compression_msg = ""
            if original_entry_obj.compression == Compression.EAHD:
                logging.info(f"Original '{file_name_to_replace}' was EAHD compressed. Attempting to compress new texture.")
                data_to_write_in_big = Compressor.compress_eahd(new_data_uncompressed)
                compression_msg = "(EAHD compression placeholder; data currently uncompressed)" if data_to_write_in_big is new_data_uncompressed else "(EAHD compression attempted)"
                logging.info(f"Compression status: {compression_msg}")

            if original_entry_obj.raw_size > 0 and len(data_to_write_in_big) > original_entry_obj.raw_size:
                msg = (f"Import aborted. The new data size ({format_filesize(len(data_to_write_in_big))}) "
                       f"is larger than the original slot size ({format_filesize(original_entry_obj.raw_size)}) "
                       f"for '{file_name_to_replace}'. {compression_msg}")
                messagebox.showerror("Size Error", msg)
                logging.warning(msg)
                return

            with open(self.file_path, 'r+b') as f_big_write:
                f_big_write.seek(original_entry_obj.offset)
                f_big_write.write(data_to_write_in_big)
                if original_entry_obj.raw_size > 0 and len(data_to_write_in_big) < original_entry_obj.raw_size:
                    padding_size = original_entry_obj.raw_size - len(data_to_write_in_big)
                    f_big_write.write(b'\x00' * padding_size)
                    logging.info(f"Padded import with {padding_size} bytes to match original size.")

            success_msg = (f"Successfully imported '{os.path.basename(new_texture_path)}' as '{file_name_to_replace}.dds'.\n"
                           f"Original slot size: {format_filesize(original_entry_obj.raw_size)}\n"
                           f"New data size: {format_filesize(len(data_to_write_in_big))}. {compression_msg}")
            messagebox.showinfo("Import Successful", success_msg)
            logging.info(success_msg)

            if not self.extract_and_display_texture():
                messagebox.showwarning("Preview Warning", "Could not automatically refresh the texture preview.")
            else:
                self.update_status(f"Texture {file_name_to_replace}.dds imported.", "green")

        except Exception as e_import:
            messagebox.showerror("Import Error", f"An unexpected error occurred during import: {e_import}")
            logging.error(f"General import error: {e_import}", exc_info=True)


    def export_selected_file(self):
        if not self.file_path:
            messagebox.showerror("Error", "No .big file loaded.")
            return
        if self.composite_mode_active:
            messagebox.showinfo("Info", "Import/Export is disabled in Composite View mode.")
            return
        if not config.IMAGE_FILES or not (0 <= self.current_image_index < len(config.IMAGE_FILES)):
            messagebox.showerror("Error", "No texture selected to export.")
            return

        file_name_to_export = config.IMAGE_FILES[self.current_image_index]
        try:
            big_file_obj = FifaBigFile(self.file_path)
        except Exception as e:
            messagebox.showerror("Error", f"Could not read BIG file for export: {e}")
            logging.error(f"BIG read error on export: {e}", exc_info=True)
            return

        entry_obj_to_export = next((e for e in big_file_obj.entries if e.name == file_name_to_export), None)
        if not entry_obj_to_export or not entry_obj_to_export.data:
            messagebox.showerror("Error", f"File '{file_name_to_export}' not found in the archive or is empty.")
            return

        data_for_export = entry_obj_to_export.data
        export_target_path = filedialog.asksaveasfilename(
            defaultextension=".png",
            filetypes=[("PNG Files", "*.png"), ("DDS Files", "*.dds")],
            initialfile=f"{file_name_to_export}"
        )
        if not export_target_path: return

        temp_dds_path_for_export = None
        try:
            if export_target_path.lower().endswith(".png"):
                with tempfile.NamedTemporaryFile(delete=False, suffix=".dds") as temp_dds_f:
                    temp_dds_f.write(data_for_export)
                    temp_dds_path_for_export = temp_dds_f.name
                
                with Image.open(temp_dds_path_for_export) as pil_img_export:
                    pil_img_export.save(export_target_path, "PNG")
                
                messagebox.showinfo("Export Successful", f"Exported '{file_name_to_export}.dds' as a PNG file to:\n'{export_target_path}'")
                logging.info(f"Exported {file_name_to_export}.dds as PNG to {export_target_path}")
            
            elif export_target_path.lower().endswith(".dds"):
                with open(export_target_path, 'wb') as out_f_dds:
                    out_f_dds.write(data_for_export)
                messagebox.showinfo("Export Successful", f"Exported '{file_name_to_export}.dds' to:\n'{export_target_path}'")
                logging.info(f"Exported {file_name_to_export}.dds as DDS to {export_target_path}")
            else:
                messagebox.showerror("Error", "Unsupported export format. Please choose .png or .dds.")
        except Exception as e_export:
            messagebox.showerror("Export Error", f"Failed to export file: {e_export}")
            logging.error(f"Export failed: {e_export}", exc_info=True)
        finally:
            if temp_dds_path_for_export and os.path.exists(temp_dds_path_for_export):
                try:
                    os.remove(temp_dds_path_for_export)
                except Exception as e_clean:
                    logging.warning(f"Could not remove temporary export file: {e_clean}")


    # --- UI and Editor Logic ---
    def add_internal_name(self):
        if not self.file_path:
            self.internal_name_label.config(text="Internal Name: Not Loaded")
            self.clear_editor_widgets()
            self.current_reference_width = None
            self.current_reference_height = None
            if self.composite_mode_active: self.toggle_composite_mode()
            return

        internal_name_str = read_internal_name(self.file_path)
        if internal_name_str:
            self.internal_name_label.config(text=f"Internal Name: {internal_name_str}")
            if internal_name_str in self.offsets_data:
                config_data = self.offsets_data[internal_name_str]
                self.current_reference_width = config_data.get("reference_width")
                self.current_reference_height = config_data.get("reference_height")
                self.offsets = {k: [int(str(v), 16) for v in (vl if isinstance(vl, list) else [vl])] for k, vl in config_data.get("offsets", {}).items()}
                self.colors = {k: [int(str(v), 16) for v in (vl if isinstance(vl, list) else [vl])] for k, vl in config_data.get("colors", {}).items()}
                self._recreate_widgets()
                self.load_current_values()
            else:
                messagebox.showerror("Config Error", f"Configuration for '{internal_name_str}' not found in offsets.json.")
                self.internal_name_label.config(text=f"Internal Name: {internal_name_str} (No Config)")
                self.clear_editor_widgets()
                self.current_reference_width = None
                self.current_reference_height = None
                if self.composite_mode_active: self.toggle_composite_mode()
        else:
            messagebox.showerror("Detection Error", "No internal scoreboard name could be detected in the file.")
            self.internal_name_label.config(text="Internal Name: Detection Failed")
            self.clear_editor_widgets()
            self.preview_canvas.delete("all")
            self.current_image = None
            self.texture_label.config(text="")
            self.image_dimensions_label.config(text="")
            self.current_reference_width = None
            self.current_reference_height = None
            if self.composite_mode_active: self.toggle_composite_mode()

    def clear_editor_widgets(self):
        for frame in [self.positions_frame, self.sizes_frame, self.colors_frame]:
            for widget in frame.winfo_children():
                widget.destroy()
        
        for attr in ['offsets_vars', 'color_vars', 'color_previews', 'offset_entry_widgets', 'asterisk_labels', 'color_comboboxes']:
            if hasattr(self, attr):
                getattr(self, attr).clear()

    def _recreate_widgets(self):
        self.clear_editor_widgets()
        
        self.offsets_vars = {tuple(v): tk.StringVar() for v in self.offsets.values()}
        self.color_vars = {
            tuple(v_list): tk.StringVar(value='#000000' if lbl not in config.SPECIAL_TEXT_COLOR_LABELS else "WHITE")
            for lbl, v_list in self.colors.items()
        }
        self.color_previews = {}
        self.offset_entry_widgets = {}
        self.asterisk_labels = {}
        self.color_comboboxes = {}

        # --- Lambdas for bindings ---
        def make_offset_update_lambda(key_tuple, var, entry_widget):
            def on_offset_update(event=None):
                old_value = self.original_loaded_offsets.get(key_tuple, "")
                new_value = var.get()
                is_focus_out = event and event.type == tk.EventType.FocusOut
                
                # Record undo action on significant changes (not just during typing)
                if old_value != new_value and is_focus_out:
                    # Check if an action for this change was already recorded (e.g., by increment)
                    if not (hasattr(entry_widget, '_undo_recorded') and entry_widget._undo_recorded):
                        action = EditAction(var, old_value, new_value, key_tuple, entry_widget, f"Offset change for {key_tuple}")
                        self.undo_manager.record_action(action)
                    else: # Reset flag
                        entry_widget._undo_recorded = False

                self.update_value(key_tuple, var)
            return on_offset_update

        def make_increment_lambda(key_tuple, var, entry_widget, direction):
            def on_increment(event=None):
                old_value = var.get()
                self._increment_value(event, var, direction)
                new_value = var.get()
                if old_value != new_value:
                    action = EditAction(var, old_value, new_value, key_tuple, entry_widget, f"Increment {direction}")
                    self.undo_manager.record_action(action)
                    entry_widget._undo_recorded = True # Flag that undo was handled
                self.update_value(key_tuple, var)
            return on_increment

        # --- Create offset and size widgets ---
        row_p, row_s = 0, 0
        for lbl, off_list in self.offsets.items():
            key_tuple = tuple(off_list)
            is_font_size = "Size" in lbl and any(kw in lbl for kw in ["Font", "Text", "Team Name", "Score", "Added Time"])

            target_frame, current_row, base_col, asterisk_col = None, 0, 0, 0
            if is_font_size or "Size" in lbl:
                target_frame, current_row, base_col, asterisk_col = self.sizes_frame, row_s, 1, 2
                tk.Label(target_frame, text=lbl).grid(row=row_s, column=0, padx=5, pady=5, sticky="w")
                row_s += 1
            elif not lbl.startswith("Image_"):
                target_frame = self.positions_frame
                current_row = row_p
                col = 0 if "X" in lbl or "Width" in lbl else 4
                base_col = col + 1
                asterisk_col = col + 2
                tk.Label(target_frame, text=lbl).grid(row=row_p, column=col, padx=5, pady=5, sticky="w")
                if col == 4 or "Y" in lbl or "Height" in lbl: row_p += 1
            else: continue # Skip Image_ entries

            if target_frame:
                entry = tk.Entry(target_frame, textvariable=self.offsets_vars[key_tuple], width=10)
                entry.grid(row=current_row, column=base_col, padx=0, pady=5)
                
                update_lambda = make_offset_update_lambda(key_tuple, self.offsets_vars[key_tuple], entry)
                entry.bind("<FocusOut>", update_lambda)
                entry.bind('<KeyPress-Up>', make_increment_lambda(key_tuple, self.offsets_vars[key_tuple], entry, "Up"))
                entry.bind('<KeyPress-Down>', make_increment_lambda(key_tuple, self.offsets_vars[key_tuple], entry, "Down"))
                
                asterisk_lbl = tk.Label(target_frame, text="", fg="red", width=1)
                asterisk_lbl.grid(row=current_row, column=asterisk_col, padx=(0, 5), pady=5, sticky="w")
                self.asterisk_labels[key_tuple] = asterisk_lbl
                self.offset_entry_widgets[key_tuple] = entry

        # --- Create color widgets ---
        row_c = 0
        for lbl, off_list in self.colors.items():
            key_tuple = tuple(off_list)
            tk.Label(self.colors_frame, text=lbl).grid(row=row_c, column=0, padx=5, pady=5, sticky="w")
            
            current_var = self.color_vars[key_tuple]
            asterisk_col_idx = 2

            if lbl in config.SPECIAL_TEXT_COLOR_LABELS:
                combo = ttk.Combobox(self.colors_frame, textvariable=current_var, values=["WHITE", "BLACK"], width=8, state="readonly")
                combo.grid(row=row_c, column=1, padx=0, pady=5)
                self.color_comboboxes[key_tuple] = combo
                
                def make_combo_change_lambda(k_t, var_obj, combo_ref):
                    def on_combo_change(event=None):
                        old_val = self.original_loaded_colors.get(k_t, "WHITE")
                        new_val = var_obj.get()
                        if old_val != new_val:
                            action = EditAction(var_obj, old_val, new_val, k_t, combo_ref, f"Text color change for {lbl}")
                            self.undo_manager.record_action(action)
                        self.handle_special_text_color_change(k_t, var_obj)
                    return on_combo_change
                combo.bind("<<ComboboxSelected>>", make_combo_change_lambda(key_tuple, current_var, combo))
            else: # Regular hex color entry
                asterisk_col_idx = 3
                entry = tk.Entry(self.colors_frame, textvariable=current_var, width=10)
                entry.grid(row=row_c, column=1, padx=0, pady=5)

                def make_color_update_lambda(k_t, var, entry_w):
                    def on_color_update(event=None):
                        if event and event.type == tk.EventType.FocusOut:
                            old_val = self.original_loaded_colors.get(k_t, "")
                            new_val = var.get()
                            if old_val != new_val:
                                action = EditAction(var, old_val, new_val, k_t, entry_w, f"Hex color change for {lbl}")
                                self.undo_manager.record_action(action)
                        self.update_color_preview_from_entry(k_t, var)
                    return on_color_update
                
                color_update_lambda = make_color_update_lambda(key_tuple, current_var, entry)
                entry.bind('<KeyPress>', lambda e, v=current_var: self._restrict_color_entry(e, v))
                entry.bind('<KeyRelease>', color_update_lambda)
                entry.bind("<FocusOut>", color_update_lambda)
                
                preview_lbl = tk.Label(self.colors_frame, bg=current_var.get(), width=3, height=1, relief="sunken")
                preview_lbl.grid(row=row_c, column=2, padx=5, pady=5)
                
                def make_choose_color_lambda(k_t, var_obj, preview_widget, entry_ref):
                    def on_choose_color(event=None):
                        old_color = var_obj.get()
                        self._choose_color(k_t, var_obj)
                        new_color = var_obj.get()
                        if old_color != new_color:
                            action = EditAction(var_obj, old_color, new_color, k_t, entry_ref, f"Choose color for {lbl}")
                            self.undo_manager.record_action(action)
                    return on_choose_color
                
                preview_lbl.bind("<Button-1>", make_choose_color_lambda(key_tuple, current_var, preview_lbl, entry))
                self.color_previews[key_tuple] = preview_lbl

            asterisk_lbl_color = tk.Label(self.colors_frame, text="", fg="red", width=1)
            asterisk_lbl_color.grid(row=row_c, column=asterisk_col_idx, padx=(0, 5), pady=5, sticky="w")
            self.asterisk_labels[key_tuple] = asterisk_lbl_color
            row_c += 1

    def load_current_values(self):
        if not self.file_path or not hasattr(self, 'offsets_vars') or not hasattr(self, 'color_vars'):
            return

        self.original_loaded_offsets.clear()
        self.original_loaded_colors.clear()

        try:
            with open(self.file_path, 'rb') as file:
                # Load numerical offsets
                for off_tuple, var_obj in self.offsets_vars.items():
                    try:
                        file.seek(off_tuple[0])
                        data = file.read(4)
                        val = struct.unpack('<f', data)[0]
                        val_str = f"{val:.2f}"
                        var_obj.set(val_str)
                        self.original_loaded_offsets[off_tuple] = val_str
                        if off_tuple in self.asterisk_labels: self.asterisk_labels[off_tuple].config(text="")
                    except Exception:
                        var_obj.set("ERR")
                
                # Load color values
                for color_label, off_tuple_list in self.colors.items():
                    off_tuple = tuple(off_tuple_list)
                    if off_tuple not in self.color_vars: continue

                    var_obj = self.color_vars[off_tuple]
                    try:
                        file.seek(off_tuple[0])
                        if color_label in config.SPECIAL_TEXT_COLOR_LABELS:
                            data_bytes = file.read(5)
                            text_color_val = data_bytes.decode('ascii', errors='ignore').strip().rstrip('\x00')
                            if text_color_val in ["WHITE", "BLACK"]:
                                var_obj.set(text_color_val)
                                self.original_loaded_colors[off_tuple] = text_color_val
                            else:
                                var_obj.set("ERR_TXT")
                                self.original_loaded_colors[off_tuple] = "ERR_TXT"
                        else: # Regular hex color
                            data_bytes = file.read(4) # BGRA
                            hex_col = f'#{data_bytes[2]:02X}{data_bytes[1]:02X}{data_bytes[0]:02X}'
                            var_obj.set(hex_col)
                            self.original_loaded_colors[off_tuple] = hex_col
                            if off_tuple in self.color_previews: self.color_previews[off_tuple].config(bg=hex_col)
                        
                        if off_tuple in self.asterisk_labels: self.asterisk_labels[off_tuple].config(text="")

                    except Exception as e:
                        var_obj.set("#ERR" if color_label not in config.SPECIAL_TEXT_COLOR_LABELS else "ERR_TXT")
                        logging.error(f"Error loading color/text for {color_label} at {off_tuple}: {e}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to read values from the file: {e}")

    def update_value(self, offset_key_tuple, string_var, from_undo_redo=False):
        val_str = string_var.get()
        if not from_undo_redo:
            logging.debug(f"update_value for {offset_key_tuple} with '{val_str}'")
        
        try:
            new_game_offset_val = float(val_str)
        except (ValueError, TypeError):
            if not from_undo_redo: self.update_status(f"Invalid float value '{val_str}'", "red")
            if offset_key_tuple in self.asterisk_labels: self.asterisk_labels[offset_key_tuple].config(text="!")
            return

        if offset_key_tuple in self.asterisk_labels:
            original_val = self.original_loaded_offsets.get(offset_key_tuple)
            is_changed = True
            if original_val is not None:
                try:
                    if abs(float(original_val) - new_game_offset_val) < 0.001: is_changed = False
                except (ValueError, TypeError): pass
            self.asterisk_labels[offset_key_tuple].config(text="*" if is_changed else "")
        
        if not from_undo_redo:
            self.update_status(f"Updated value for {offset_key_tuple}", "blue")

        if self.composite_mode_active:
            self._update_composite_element_from_offset(offset_key_tuple, new_game_offset_val)

    def _update_composite_element_from_offset(self, offset_key_tuple, new_game_offset_val):
        current_offset_json_label = next((label for label, off_list in self.offsets.items() if tuple(off_list) == offset_key_tuple), None)
        if not current_offset_json_label: return

        visual_updated = False
        is_font_size_update = "Size" in current_offset_json_label and any(kw in current_offset_json_label for kw in ["Font", "Text", "Name", "Score"])

        for el_data in self.composite_elements:
            element_modified = False
            if el_data.get('x_offset_label_linked') == current_offset_json_label:
                base_game_x = el_data.get('base_game_x')
                if base_game_x is not None:
                    el_data['original_x'] = float(el_data.get('gui_ref_x', 0)) + (new_game_offset_val - base_game_x)
                    element_modified = True
            if el_data.get('y_offset_label_linked') == current_offset_json_label:
                base_game_y = el_data.get('base_game_y')
                if base_game_y is not None:
                    el_data['original_y'] = float(el_data.get('gui_ref_y', 0)) + (new_game_offset_val - base_game_y)
                    element_modified = True
            
            if is_font_size_update and el_data.get('type') == "text" and el_data.get('font_size_offset_label_linked') == current_offset_json_label:
                el_data['base_font_size'] = new_game_offset_val / 1.5
                element_modified = True

            if element_modified:
                visual_updated = True
                leader_tag = el_data.get('display_tag')
                if leader_tag: # Update conjoined elements
                    for follower in self.composite_elements:
                        if follower.get('conjoined_to_tag') == leader_tag:
                            follower['original_x'] = el_data['original_x'] + follower.get('relative_offset_x', 0)
                            follower['original_y'] = el_data['original_y'] + follower.get('relative_offset_y', 0)
        
        if visual_updated: self.redraw_composite_view()

    def _increment_value(self, event, str_var, direction):
        try:
            current_val_str = str_var.get()
            if not current_val_str or current_val_str == "ERR": current_val_str = "0.0"
            value_float = float(current_val_str)

            increment = 1.0
            if event.state & 0x0001: increment = 0.1  # Shift
            if event.state & 0x0004: increment = 0.01 # Ctrl
            
            value_float += increment if direction == 'Up' else -increment
            str_var.set(f"{value_float:.4f}")
        except ValueError:
            self.update_status("Invalid value for increment.", "red")

    def update_color_preview_from_entry(self, off_key_tuple, str_var, from_undo_redo=False):
        hex_color_str = str_var.get()
        is_valid = False

        if len(hex_color_str) == 7 and hex_color_str.startswith('#'):
            try:
                int(hex_color_str[1:], 16)
                is_valid = True
                if hasattr(self, 'color_previews') and off_key_tuple in self.color_previews:
                    self.color_previews[off_key_tuple].config(bg=hex_color_str)
                if not from_undo_redo: self.update_status("Color preview updated.", "blue")
                if self.composite_mode_active: self.redraw_composite_view()
            except ValueError:
                if not from_undo_redo: self.update_status("Invalid hex color code.", "red")
        elif not from_undo_redo and len(hex_color_str) > 0 and not hex_color_str.startswith('#') and all(c in "0123456789abcdefABCDEF" for c in hex_color_str) and len(hex_color_str) <= 6:
            str_var.set("#" + hex_color_str.upper())
            self.update_color_preview_from_entry(off_key_tuple, str_var, from_undo_redo)
            return

        if off_key_tuple in self.asterisk_labels:
            original_val = self.original_loaded_colors.get(off_key_tuple)
            is_changed = (is_valid and original_val and original_val.lower() != hex_color_str.lower())
            self.asterisk_labels[off_key_tuple].config(text="*" if is_changed else "")

    def handle_special_text_color_change(self, off_key_tuple, str_var, from_undo_redo=False):
        text_color_value = str_var.get()
        if not from_undo_redo:
            self.update_status(f"Text color set to {text_color_value}.", "blue")
        if self.composite_mode_active:
            self.redraw_composite_view()

        if off_key_tuple in self.asterisk_labels:
            original_val = self.original_loaded_colors.get(off_key_tuple)
            is_changed = (original_val != text_color_value) if original_val else True
            self.asterisk_labels[off_key_tuple].config(text="*" if is_changed else "")

    def _choose_color(self, off_key_tuple, str_var):
        initial_color = str_var.get()
        if not (initial_color.startswith("#") and len(initial_color) == 7):
            initial_color = "#000000"
        
        new_color = colorchooser.askcolor(initialcolor=initial_color, title="Choose Color")
        if new_color and new_color[1]:
            chosen_hex = new_color[1].lower()
            str_var.set(chosen_hex)
            self.update_color_preview_from_entry(off_key_tuple, str_var)

    def _restrict_color_entry(self, event, str_var):
        allowed_keys = ['Left', 'Right', 'BackSpace', 'Delete', 'Tab', 'Home', 'End', 'Shift_L', 'Shift_R', 'Control_L', 'Control_R']
        if event.keysym in allowed_keys or (event.state & 4 and event.keysym.lower() in ('c', 'v', 'x')):
            return

        current_text = str_var.get()
        char_typed = event.char
        if not char_typed or not char_typed.isprintable(): return

        if not current_text and char_typed != '#':
            str_var.set('#' + char_typed.upper())
            event.widget.after_idle(lambda: event.widget.icursor(tk.END))
            return 'break'
        
        if current_text == '#' and char_typed == '#': return 'break'

        has_selection = False
        try: has_selection = event.widget.selection_present()
        except tk.TclError: pass
        
        if len(current_text) >= 7 and not has_selection: return 'break'
        if current_text.startswith('#') and char_typed.lower() not in '0123456789abcdef': return 'break'


    # --- Texture and Preview ---
    def extract_and_display_texture(self) -> bool:
        if self.composite_mode_active: return False
        if not self.file_path:
            self.preview_canvas.delete("all")
            self.texture_label.config(text="No file loaded")
            self.current_image = None
            return False

        try:
            big_file = FifaBigFile(self.file_path)
            if not (0 <= self.current_image_index < len(config.IMAGE_FILES)): return False
            img_name = config.IMAGE_FILES[self.current_image_index]
            entry = next((e for e in big_file.entries if e.name == img_name), None)

            if not entry or not entry.data or entry.file_type != "DDS" or entry.data[:4] != b'DDS ':
                logging.info(f"Texture '{img_name}' is not a valid or displayable DDS file.")
                return False

            with tempfile.NamedTemporaryFile(delete=False, suffix=".dds") as tmp_f:
                tmp_f.write(entry.data)
                temp_dds_path = tmp_f.name
            
            try:
                pil_img = Image.open(temp_dds_path)
                w, h = pil_img.width, pil_img.height
                
                bg_color = (255, 255, 255, 255) if self.preview_bg_color_is_white else (0, 0, 0, 255)
                pil_rgba = pil_img.convert('RGBA') if pil_img.mode != 'RGBA' else pil_img
                background = Image.new('RGBA', pil_rgba.size, bg_color)
                self.current_image = Image.alpha_composite(background, pil_rgba)
                
                self.single_view_zoom_level = 1.0
                self.single_view_pan_offset_x = 0.0
                self.single_view_pan_offset_y = 0.0
                self.redraw_single_view_image()
                
                self.texture_label.config(text=f"{img_name}.dds")
                self.image_dimensions_label.config(text=f"{w}x{h}")
                return True
            except Exception as e_disp:
                logging.warning(f"Failed to display DDS texture '{img_name}': {e_disp}")
                return False
            finally:
                if os.path.exists(temp_dds_path): os.remove(temp_dds_path)
        
        except Exception as e_outer:
            logging.error(f"Error during texture extraction: {e_outer}", exc_info=True)
            return False

    def redraw_single_view_image(self):
        if self.current_image is None:
            self.preview_canvas.delete("all")
            return
        
        canvas_w = self.preview_canvas.winfo_width()
        canvas_h = self.preview_canvas.winfo_height()
        if canvas_w <= 1 or canvas_h <= 1: return

        zoomed_w = int(self.current_image.width * self.single_view_zoom_level)
        zoomed_h = int(self.current_image.height * self.single_view_zoom_level)
        if zoomed_w <= 0 or zoomed_h <= 0: return

        try:
            resized_img = self.current_image.resize((zoomed_w, zoomed_h), Image.LANCZOS)
            img_tk = ImageTk.PhotoImage(resized_img)
            self.preview_canvas.delete("all")
            
            draw_x = canvas_w / 2 + self.single_view_pan_offset_x
            draw_y = canvas_h / 2 + self.single_view_pan_offset_y
            self.preview_canvas.create_image(draw_x, draw_y, anchor=tk.CENTER, image=img_tk, tags="image_on_canvas")
            self.preview_canvas.image_ref = img_tk
        except Exception as e:
            logging.error(f"Error redrawing single view image: {e}")

    def previous_image(self):
        if self.composite_mode_active or not self.file_path or not config.IMAGE_FILES: return
        original_idx = self.current_image_index
        num_files = len(config.IMAGE_FILES)
        if num_files == 0: return

        for i in range(1, num_files + 1):
            self.current_image_index = (original_idx - i + num_files) % num_files
            if self.extract_and_display_texture(): return
        
        self.current_image_index = original_idx # Revert if no displayable found
        if not self.extract_and_display_texture():
            self.preview_canvas.delete("all")
            self.texture_label.config(text="No displayable textures found")
            self.current_image = None
            
    def next_image(self):
        if self.composite_mode_active or not self.file_path or not config.IMAGE_FILES: return
        original_idx = self.current_image_index
        num_files = len(config.IMAGE_FILES)
        if num_files == 0: return

        for i in range(1, num_files + 1):
            self.current_image_index = (original_idx + i) % num_files
            if self.extract_and_display_texture(): return

        self.current_image_index = original_idx # Revert
        if not self.extract_and_display_texture():
            self.preview_canvas.delete("all")
            self.texture_label.config(text="No displayable textures found")
            self.current_image = None

    def toggle_preview_background(self):
        if self.composite_mode_active: return
        self.preview_bg_color_is_white = not self.preview_bg_color_is_white
        if self.file_path and self.current_image:
            self.extract_and_display_texture()

    # --- Mouse/Drag Handlers ---
    def zoom_image_handler(self, event):
        if self.composite_mode_active: self.zoom_composite_view(event)
        else: self.zoom_single_view(event)

    def start_drag_handler(self, event):
        if self.composite_mode_active: self.start_drag_composite(event)
        else: self.start_drag_single(event)

    def on_drag_handler(self, event):
        if self.composite_mode_active: self.on_drag_composite(event)
        else: self.on_drag_single(event)

    def on_drag_release_handler(self, event):
        self.drag_data["is_panning"] = False
        self.drag_data["is_panning_rmb"] = False
        if self.composite_mode_active: self.clear_all_highlights()

    def zoom_single_view(self, event):
        if self.current_image is None: return
        factor = 1.1 if event.delta > 0 else (1 / 1.1)
        self.single_view_zoom_level = max(0.05, min(self.single_view_zoom_level * factor, 10.0))
        self.redraw_single_view_image()

    def start_drag_single(self, event):
        self.drag_data["is_panning"] = True
        self.drag_data["x"] = event.x
        self.drag_data["y"] = event.y

    def on_drag_single(self, event):
        if not self.drag_data["is_panning"] or self.current_image is None: return
        dx = event.x - self.drag_data["x"]
        dy = event.y - self.drag_data["y"]
        self.single_view_pan_offset_x += dx
        self.single_view_pan_offset_y += dy
        self.drag_data["x"] = event.x
        self.drag_data["y"] = event.y
        self.redraw_single_view_image()


    # --- Composite View ---
    def toggle_composite_mode(self):
        logging.info(f"Toggling composite mode. Currently: {self.composite_mode_active}")
        if not self.composite_mode_active:
            is_ok = self.internal_name_label.cget("text").startswith("Internal Name: ") and \
                    not self.internal_name_label.cget("text").endswith("(No Config)") and \
                    not self.internal_name_label.cget("text").endswith("(Detection Failed)")

            if not self.file_path or not is_ok:
                messagebox.showinfo("Information", "Please load a .big file with a valid configuration before entering Composite View.")
                logging.warning("Composite mode prerequisites not met (no file or bad config).")
                return

            try: # Ensure image '10' is selected
                target_img_name = "10"
                idx_10 = config.IMAGE_FILES.index(target_img_name)
                if self.current_image_index != idx_10:
                    self.current_image_index = idx_10
                    if not self.extract_and_display_texture():
                        messagebox.showerror("Error", f"Could not load base texture '{target_img_name}.dds'. Cannot enter composite mode.")
                        return
            except ValueError:
                messagebox.showerror("Error", f"Base texture '{target_img_name}.dds' is not in the list of available images. Cannot enter composite mode.")
                return

            self.composite_mode_active = True
            self.composite_zoom_level = 1.0
            self.composite_pan_offset_x = 250.0
            self.composite_pan_offset_y = 150.0
            
            self.preview_canvas.delete("all")
            self.current_image = None
            self.texture_label.config(text="")
            self.image_dimensions_label.config(text="")

            self.display_composite_view()
            if not self.composite_mode_active: return # display_composite_view might fail and reset the flag

            self.composite_view_button.config(text="Single View")
            self.left_arrow_button.pack_forget()
            self.right_arrow_button.pack_forget()
            self.import_button.config(state=tk.DISABLED)
            self.export_button.config(state=tk.DISABLED)
            self.toggle_bg_button.config(state=tk.DISABLED)
            logging.info("Switched TO composite mode successfully.")
        else:
            self.clear_all_highlights()
            self.composite_mode_active = False
            self.clear_composite_view()
            
            self.composite_view_button.config(text="Composite View")
            self.left_arrow_button.pack(side=tk.LEFT, padx=(0, 5), pady=5, anchor='center')
            self.right_arrow_button.pack(side=tk.LEFT, padx=5, pady=5, anchor='center')
            self.import_button.config(state=tk.NORMAL)
            self.export_button.config(state=tk.NORMAL)
            self.toggle_bg_button.config(state=tk.NORMAL)
            
            if self.file_path: self.extract_and_display_texture()
            else:
                self.preview_canvas.delete("all")
                self.texture_label.config(text="No file loaded")
                self.image_dimensions_label.config(text="")
            logging.info("Switched FROM composite mode.")

    def display_composite_view(self):
        logging.info("Attempting to display composite view.")
        if not self.file_path:
            self.composite_mode_active = False
            return

        self.preview_canvas.config(bg="gray70")
        try:
            big_file = FifaBigFile(self.file_path)
            canvas_w = self.preview_canvas.winfo_width() or 580
            canvas_h = self.preview_canvas.winfo_height() or 150
            
            # Load images
            temp_elements_map: Dict[str, Dict[str, Any]] = {}
            images_to_load_cfg = [("10", "10"), ("14", "14"), ("30", "30_orig"), ("30", "30_dup")]
            source_dds_entries = {e.name: e for e in big_file.entries if e.name in [c[0] for c in images_to_load_cfg] and e.file_type == "DDS" and e.data}

            for big_name, disp_tag_suffix in images_to_load_cfg:
                if big_name not in source_dds_entries: continue
                source_entry = source_dds_entries[big_name]
                img_tag = f"img_{disp_tag_suffix}"
                img_cfg = config.PREDEFINED_IMAGE_COORDS.get(img_tag)
                if not img_cfg: continue

                with tempfile.NamedTemporaryFile(delete=False, suffix=".dds") as tmp_f:
                    tmp_f.write(source_entry.data)
                    tmp_path = tmp_f.name
                
                try:
                    pil_img = Image.open(tmp_path).convert("RGBA")
                    gui_ref_x, gui_ref_y, x_lbl, base_gx, y_lbl, base_gy = img_cfg
                    vis_x, vis_y = float(gui_ref_x), float(gui_ref_y)
                    
                    if x_lbl in self.offsets and y_lbl in self.colors and hasattr(self, 'offsets_vars'):
                        x_key, y_key = tuple(self.offsets[x_lbl]), tuple(self.offsets[y_lbl])
                        if x_key in self.offsets_vars and y_key in self.offsets_vars:
                            try:
                                cur_gx, cur_gy = float(self.offsets_vars[x_key].get()), float(self.offsets_vars[y_key].get())
                                vis_x += (cur_gx - base_gx)
                                vis_y += (cur_gy - base_gy)
                            except ValueError: pass
                    
                    temp_elements_map[img_tag] = {
                        'type': "image", 'pil_image': pil_img, 'original_x': vis_x, 'original_y': vis_y,
                        'display_tag': img_tag, 'is_fixed': (img_tag == "img_10"),
                        'x_offset_label_linked': x_lbl, 'y_offset_label_linked': y_lbl,
                        'base_game_x': base_gx, 'base_game_y': base_gy, 'gui_ref_x': gui_ref_x, 'gui_ref_y': gui_ref_y
                    }
                finally:
                    if os.path.exists(tmp_path): os.remove(tmp_path)
            
            # Load text elements
            for cfg_tuple in config.INITIAL_TEXT_ELEMENTS_CONFIG:
                tag, txt, gui_x, gui_y, d_font_sz, f_sz_lbl, c_lbl, is_fixed, x_lbl, base_gx, y_lbl, base_gy = cfg_tuple
                vis_x, vis_y = float(gui_x), float(gui_y)
                gui_font_sz = float(d_font_sz)

                if x_lbl in self.offsets and y_lbl in self.offsets and hasattr(self, 'offsets_vars'):
                    x_key, y_key = tuple(self.offsets[x_lbl]), tuple(self.offsets[y_lbl])
                    if x_key in self.offsets_vars and y_key in self.offsets_vars:
                        try:
                            cur_gx, cur_gy = float(self.offsets_vars[x_key].get()), float(self.offsets_vars[y_key].get())
                            vis_x += (cur_gx - base_gx)
                            vis_y += (cur_gy - base_gy)
                        except ValueError: pass

                if f_sz_lbl != "PlaceHolder" and f_sz_lbl in self.offsets and hasattr(self, 'offsets_vars'):
                    f_sz_key = tuple(self.offsets[f_sz_lbl])
                    if f_sz_key in self.offsets_vars:
                        try:
                            gui_font_sz = float(self.offsets_vars[f_sz_key].get()) / 1.5
                        except ValueError: pass
                
                temp_elements_map[tag] = {
                    'type': "text", 'text_content': txt, 'original_x': vis_x, 'original_y': vis_y,
                    'base_font_size': gui_font_sz, 'font_size_offset_label_linked': f_sz_lbl,
                    'color_offset_label': c_lbl, 'display_tag': tag, 'is_fixed': is_fixed,
                    'x_offset_label_linked': x_lbl, 'y_offset_label_linked': y_lbl,
                    'base_game_x': base_gx, 'base_game_y': base_gy, 'gui_ref_x': gui_x, 'gui_ref_y': gui_y
                }

            # Conjoin elements
            leader_tag, follower_tag = "text_added_time", "img_14"
            if leader_tag in temp_elements_map and follower_tag in temp_elements_map:
                leader, follower = temp_elements_map[leader_tag], temp_elements_map[follower_tag]
                img14_gui_x, img14_gui_y = config.PREDEFINED_IMAGE_COORDS[follower_tag][:2]
                txt_cfg = next(item for item in config.INITIAL_TEXT_ELEMENTS_CONFIG if item[0] == leader_tag)
                rel_off_x = img14_gui_x - txt_cfg[2]
                rel_off_y = img14_gui_y - txt_cfg[3]
                
                follower['original_x'] = leader['original_x'] + rel_off_x
                follower['original_y'] = leader['original_y'] + rel_off_y
                follower.update({'conjoined_to_tag': leader_tag, 'relative_offset_x': rel_off_x, 'relative_offset_y': rel_off_y, 'is_fixed': True})

            self.composite_elements = list(temp_elements_map.values())
            self.redraw_composite_view()
            self.texture_label.config(text="Composite Mode Active")
            self.image_dimensions_label.config(text=f"Canvas: {canvas_w}x{canvas_h} | Ref: {self.current_reference_width or 'N/A'}x{self.current_reference_height or 'N/A'}")
        except Exception as e:
            messagebox.showerror("Composite View Error", f"Failed to build composite view: {e}")
            logging.error(f"Critical composite display error: {e}", exc_info=True)
            self.toggle_composite_mode() # Switch back to single view

    def redraw_composite_view(self):
        self.preview_canvas.delete("composite_item")
        canvas_w = self.preview_canvas.winfo_width() or 580
        canvas_h = self.preview_canvas.winfo_height() or 150
        
        view_origin_x = canvas_w / 2.0
        view_origin_y = canvas_h / 2.0
        eff_pan_x = self.composite_pan_offset_x * self.composite_zoom_level
        eff_pan_y = self.composite_pan_offset_y * self.composite_zoom_level

        for el_data in self.composite_elements:
            screen_x = view_origin_x - eff_pan_x + (el_data['original_x'] * self.composite_zoom_level)
            screen_y = view_origin_y - eff_pan_y + (el_data['original_y'] * self.composite_zoom_level)
            el_data.update({'current_x_on_canvas': screen_x, 'current_y_on_canvas': screen_y})

            if el_data.get('type') == "text":
                zoomed_font_size = max(1, int(el_data.get('base_font_size', config.DEFAULT_TEXT_BASE_FONT_SIZE) * self.composite_zoom_level))
                
                text_color = config.DEFAULT_TEXT_COLOR_FALLBACK
                color_label = el_data.get('color_offset_label')
                if color_label and color_label in self.colors and hasattr(self, 'color_vars'):
                    key_tuple = tuple(self.colors[color_label])
                    if key_tuple in self.color_vars:
                        val = self.color_vars[key_tuple].get()
                        if color_label in config.SPECIAL_TEXT_COLOR_LABELS:
                            text_color = val.lower()
                        elif val.startswith("#") and len(val) == 7:
                            text_color = val
                
                item_id = self.preview_canvas.create_text(
                    int(screen_x), int(screen_y), anchor=tk.NW, text=el_data['text_content'],
                    font=(config.DEFAULT_TEXT_FONT_FAMILY, zoomed_font_size, "bold"), fill=text_color,
                    tags=("composite_item", el_data['display_tag'])
                )
                el_data['canvas_id'] = item_id

            elif el_data.get('type') == "image":
                pil_img = el_data['pil_image']
                zoomed_w = int(pil_img.width * self.composite_zoom_level)
                zoomed_h = int(pil_img.height * self.composite_zoom_level)
                if zoomed_w <= 0 or zoomed_h <= 0: continue

                try:
                    resized_pil = pil_img.resize((zoomed_w, zoomed_h), Image.LANCZOS)
                    el_data['tk_image_ref'] = ImageTk.PhotoImage(resized_pil)
                    item_id = self.preview_canvas.create_image(
                        int(screen_x), int(screen_y), anchor=tk.NW,
                        image=el_data['tk_image_ref'], tags=("composite_item", el_data['display_tag'])
                    )
                    el_data['canvas_id'] = item_id
                except Exception as e_redraw:
                    logging.error(f"Error redrawing image {el_data.get('display_tag')}: {e_redraw}")

    def clear_composite_view(self):
        self.preview_canvas.delete("composite_item")
        for el in self.composite_elements:
            if 'tk_image_ref' in el: del el['tk_image_ref']
        self.composite_elements.clear()
        self.preview_canvas.config(bg="#CCCCCC")
        
    def clear_all_highlights(self):
        for entry_widget, original_bg in self.highlighted_offset_entries:
            try:
                if entry_widget.winfo_exists(): entry_widget.config(bg=original_bg)
            except tk.TclError: pass
        self.highlighted_offset_entries.clear()

    def zoom_composite_view(self, event):
        if not self.composite_elements: return
        factor = 1.1 if event.delta > 0 else (1 / 1.1)
        new_zoom = max(0.05, min(self.composite_zoom_level * factor, 10.0))

        canvas_w = self.preview_canvas.winfo_width()
        canvas_h = self.preview_canvas.winfo_height()
        mouse_x_from_center = event.x - (canvas_w / 2.0)
        mouse_y_from_center = event.y - (canvas_h / 2.0)

        if abs(self.composite_zoom_level) > 1e-6 and abs(new_zoom) > 1e-6:
            pan_adj_x = mouse_x_from_center * ((1.0 / self.composite_zoom_level) - (1.0 / new_zoom))
            pan_adj_y = mouse_y_from_center * ((1.0 / self.composite_zoom_level) - (1.0 / new_zoom))
            self.composite_pan_offset_x += pan_adj_x
            self.composite_pan_offset_y += pan_adj_y

        self.composite_zoom_level = new_zoom
        self.redraw_composite_view()

    def start_pan_composite(self, event):
        self.drag_data["is_panning_rmb"] = True
        self.drag_data["x"] = event.x
        self.drag_data["y"] = event.y

    def on_pan_composite(self, event):
        if not self.drag_data.get("is_panning_rmb"): return
        dx = event.x - self.drag_data["x"]
        dy = event.y - self.drag_data["y"]
        if abs(self.composite_zoom_level) > 1e-6:
            self.composite_pan_offset_x -= dx / self.composite_zoom_level
            self.composite_pan_offset_y -= dy / self.composite_zoom_level
        self.drag_data["x"] = event.x
        self.drag_data["y"] = event.y
        self.redraw_composite_view()

    def start_drag_composite(self, event):
        if event.num == 3: # Right click
            self.start_pan_composite(event)
            return
        
        self.clear_all_highlights()
        self.drag_data["is_panning"] = False
        
        item_tuple = self.preview_canvas.find_closest(event.x, event.y)
        if not item_tuple:
            self.composite_drag_data['item'] = None
            return
        
        item_id = item_tuple[0]
        if "composite_item" not in self.preview_canvas.gettags(item_id):
            self.composite_drag_data['item'] = None
            return

        for el_data in self.composite_elements:
            if el_data.get('canvas_id') == item_id:
                if el_data.get('is_fixed', False):
                    logging.info(f"Attempted to drag a fixed element: {el_data.get('display_tag')}")
                    self.composite_drag_data['item'] = None
                    return
                
                initial_gx, initial_gy = 0.0, 0.0
                try:
                    if el_data.get('x_offset_label_linked') in self.offsets:
                        initial_gx = float(self.offsets_vars[tuple(self.offsets[el_data['x_offset_label_linked']])].get())
                    if el_data.get('y_offset_label_linked') in self.offsets:
                        initial_gy = float(self.offsets_vars[tuple(self.offsets[el_data['y_offset_label_linked']])].get())
                except (ValueError, KeyError):
                    logging.warning(f"Could not parse initial game offsets for {el_data.get('display_tag')}.")

                self.composite_drag_data.update({
                    'item': item_id, 'x': event.x, 'y': event.y, 'element_data': el_data,
                    'start_original_x': el_data['original_x'], 'start_original_y': el_data['original_y'],
                    'initial_game_offset_x_at_drag_start': initial_gx,
                    'initial_game_offset_y_at_drag_start': initial_gy
                })
                self.preview_canvas.tag_raise(item_id)
                self._highlight_linked_entries(el_data)
                return
        self.composite_drag_data['item'] = None

    def _highlight_linked_entries(self, el_data):
        labels_to_highlight = [
            (el_data.get('x_offset_label_linked'), "lightyellow"),
            (el_data.get('y_offset_label_linked'), "lightyellow"),
        ]
        if el_data.get('type') == 'text' and not el_data.get('is_fixed'):
            labels_to_highlight.append((el_data.get('font_size_offset_label_linked'), "lightcyan"))

        for label, color in labels_to_highlight:
            if label and label in self.offsets:
                key = tuple(self.offsets[label])
                if key in self.offset_entry_widgets:
                    widget = self.offset_entry_widgets[key]
                    if not any(h[0] == widget for h in self.highlighted_offset_entries):
                        self.highlighted_offset_entries.append((widget, widget.cget("background")))
                        widget.config(bg=color)

    def on_drag_composite(self, event):
        if event.num == 3 or self.drag_data.get("is_panning_rmb"):
            self.on_pan_composite(event)
            return
        if self.composite_drag_data.get('item') is None: return

        elem_data = self.composite_drag_data.get('element_data')
        if not elem_data: return

        dx = (event.x - self.composite_drag_data['x']) / self.composite_zoom_level
        dy = (event.y - self.composite_drag_data['y']) / self.composite_zoom_level
        
        elem_data['original_x'] = self.composite_drag_data['start_original_x'] + dx
        elem_data['original_y'] = self.composite_drag_data['start_original_y'] + dy

        # Update linked offset variables and their UI
        x_label, y_label = elem_data.get('x_offset_label_linked'), elem_data.get('y_offset_label_linked')
        if x_label in self.offsets:
            new_game_x = self.composite_drag_data['initial_game_offset_x_at_drag_start'] + dx
            self.offsets_vars[tuple(self.offsets[x_label])].set(f"{new_game_x:.2f}")
            self.update_value(tuple(self.offsets[x_label]), self.offsets_vars[tuple(self.offsets[x_label])])
        if y_label in self.offsets:
            new_game_y = self.composite_drag_data['initial_game_offset_y_at_drag_start'] + dy
            self.offsets_vars[tuple(self.offsets[y_label])].set(f"{new_game_y:.2f}")
            self.update_value(tuple(self.offsets[y_label]), self.offsets_vars[tuple(self.offsets[y_label])])
            
        # Update conjoined elements
        if elem_data.get('display_tag'):
            for follower in self.composite_elements:
                if follower.get('conjoined_to_tag') == elem_data['display_tag']:
                    follower['original_x'] = elem_data['original_x'] + follower.get('relative_offset_x', 0)
                    follower['original_y'] = elem_data['original_y'] + follower.get('relative_offset_y', 0)

        self.redraw_composite_view()

    def on_drag_release_composite(self, event):
        if event.num == 3: # Right click
            self.drag_data["is_panning_rmb"] = False
        else: # Left click
            # Create a single undo action for the entire drag operation
            elem_data = self.composite_drag_data.get('element_data')
            if elem_data and self.composite_drag_data.get('item'):
                x_label = elem_data.get('x_offset_label_linked')
                y_label = elem_data.get('y_offset_label_linked')
                if x_label in self.offsets and y_label in self.offsets:
                    x_key, y_key = tuple(self.offsets[x_label]), tuple(self.offsets[y_label])
                    # For simplicity, we record the end state. A more complex system
                    # could bundle both X and Y into a single "Move" action.
                    # For now, we rely on the continuous updates during drag being coalesced
                    # by the undo manager if we were to record them there.
                    # With this release-based approach, we need to get the "before" values.
                    # This is complex, so for now we'll just let the last update_value call handle it.
                    pass 
            self.composite_drag_data['item'] = None
            self.clear_all_highlights()

    # --- Misc and Helpers ---
    def update_status(self, msg: str, color: str):
        self.status_label.config(text=msg, fg=color)

    def on_map_event(self, event):
        """On first window map, attempt to display texture if a file is loaded."""
        if self.file_path and not self.current_image and not self.composite_mode_active:
            self.extract_and_display_texture()

    def about(self):
        win = tk.Toplevel(self.root)
        win.title("About FLP Scoreboard Editor 25")
        win.geometry("450x250")
        win.resizable(False, False)
        win.transient(self.root)
        win.grab_set()
        
        tk.Label(win, text="FLP Scoreboard Editor 25", pady=10, font=("Helvetica", 12, "bold")).pack()
        tk.Label(win, text="Version 1.13 [Build 12 May 2025]", pady=5).pack()
        tk.Label(win, text="© 2025 FIFA Legacy Project. All Rights Reserved.", pady=5).pack()
        tk.Label(win, text="Designed & Developed By: Emran_Ahm3d", pady=5).pack()
        tk.Label(win, text="Special Thanks: Riesscar, KO, MCK, Marconis (Research)", pady=5, wraplength=400).pack()
        tk.Label(win, text="Discord: @emran_ahm3d", pady=5).pack()
        
        ttk.Button(win, text="OK", command=win.destroy, width=10).pack(pady=10)
        win.wait_window()

    def show_documentation(self):
        webbrowser.open("https://soccergaming.com/")

    def exit_app(self):
        if messagebox.askyesno("Exit Application", "Are you sure you want to exit?"):
            self.root.destroy()