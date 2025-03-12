import tkinter as tk
from tkinter import filedialog, messagebox, ttk, colorchooser
import struct
import webbrowser
import struct
import os
import tempfile
from PIL import Image, ImageTk
import json
import logging
from dataclasses import dataclass
from enum import Enum
from typing import List

# Load offsets from JSON file
with open('offsets.json', 'r') as f:
    offsets_data = json.load(f)

file_path = None
offsets = {}
colors = {}
current_image = None  # Store original image for zooming
# New global variables to store the previous file path and values
previous_file_path = None
previous_offsets_values = {}
previous_color_values = {}

class Compression(Enum):
    NONE = "None"
    EAHD = "EAHD"

@dataclass
class FileEntry:
    offset: int
    size: int
    name: str
    file_type: str
    compression: Compression
    data: bytes

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
        chunk = self.data[self.pos:self.pos + bytes_count]
        self.pos += bytes_count
        return int.from_bytes(chunk, "big" if big_endian else "little")

    def read_string(self, encoding: str) -> str:
        start = self.pos
        while self.pos < len(self.data) and self.data[self.pos] != 0:
            self.pos += 1
        result = self.data[start:self.pos].decode(encoding, errors="ignore")
        self.pos += 1  # Skip null terminator
        return result

    def skip(self, count: int):
        self.pos += count

class Decompressor:
    @staticmethod
    def detect_compression(data: bytes) -> Compression:
        """Detect if data uses EAHD compression based on the first two bytes."""
        return Compression.EAHD if len(data) >= 2 and data[:2] == b"\xfb\x10" else Compression.NONE

    @staticmethod
    def decompress_eahd(data: bytes) -> bytes:
        """Decompress EAHD-compressed data."""
        try:
            reader = BinaryReader(bytearray(data))
            if reader.read_int(2, True) != 0xFB10:
                return data

            total_size = reader.read_int(3, True)
            output = bytearray(total_size)
            pos = 0

            while reader.pos < len(reader.data):
                ctrl = reader.read_byte()

                if ctrl < 0x80:  # Short copy
                    a = reader.read_byte()
                    to_read = ctrl & 0x03
                    to_copy = ((ctrl & 0x1C) >> 2) + 3
                    offset = ((ctrl & 0x60) << 3) + a + 1
                elif ctrl < 0xC0:  # Medium copy
                    a, b = reader.read_byte(), reader.read_byte()
                    to_read = (a >> 6) & 0x03
                    to_copy = (ctrl & 0x3F) + 4
                    offset = ((a & 0x3F) << 8) + b + 1
                elif ctrl < 0xE0:  # Long copy
                    a, b, c = reader.read_byte(), reader.read_byte(), reader.read_byte()
                    to_read = ctrl & 0x03
                    to_copy = ((ctrl & 0x0C) << 6) + c + 5
                    offset = ((ctrl & 0x10) << 12) + (a << 8) + b + 1
                elif ctrl < 0xFC:  # Large read
                    to_read = ((ctrl & 0x1F) << 2) + 4
                    to_copy = 0
                    offset = 0
                else:  # Small read
                    to_read = ctrl & 0x03
                    to_copy = 0
                    offset = 0

                for _ in range(to_read):
                    output[pos] = reader.read_byte()
                    pos += 1

                copy_start = pos - offset
                for _ in range(to_copy):
                    output[pos] = output[copy_start]
                    pos += 1
                    copy_start += 1

            return bytes(output[:pos])
        except Exception as e:
            logging.error(f"ERROR: EAHD decompression failed - {e}")
            return data

class FifaBigFile:
    def __init__(self, filename):
        self.filename = filename
        self.entries: List[FileEntry] = []
        self._load()

    def _load(self):
        with open(self.filename, 'rb') as f:
            self.data = bytearray(f.read())

        reader = BinaryReader(self.data)
        magic = bytes(self.data[:4])
        reader.skip(4)  # Skip magic
        total_data_size = reader.read_int(4, False)
        num_entries = reader.read_int(4, True)
        unknown_offset = reader.read_int(4, True)

        current_type = "DAT"
        for _ in range(num_entries):
            offset = reader.read_int(4, True)
            size = reader.read_int(4, True)
            name = reader.read_string('utf-8')

            if size == 0 and name in {"sg1", "sg2"}:
                current_type = {"sg1": "DDS", "sg2": "APT"}[name]
                self.entries.append(FileEntry(offset, size, name, current_type, Compression.NONE, b""))
                continue

            raw_data = bytes(self.data[offset:offset + size])
            compression = Decompressor.detect_compression(raw_data)
            data = Decompressor.decompress_eahd(raw_data) if compression == Compression.EAHD else raw_data

            self.entries.append(FileEntry(offset, len(data), name, current_type, compression, data))

    def list_files(self):
        return [entry.name for entry in self.entries if entry.size > 0]

    def detect_file_type(self, data):
        if data[:4] == b'DDS ':
            return "[DDS]"
        return ""

    def export_file(self, file_name):
        for entry in self.entries:
            if entry.name == file_name:
                data = entry.data
                file_type = self.detect_file_type(data)

                output_path = filedialog.asksaveasfilename(
                    defaultextension="",
                    filetypes=[("All Files", "*.*")],
                    initialfile=os.path.basename(file_name)
                )
                if not output_path:
                    return

                if file_type == "[DDS]":
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".dds") as temp_file:
                        temp_dds_path = temp_file.name
                        temp_file.write(data)

                    try:
                        image = Image.open(temp_dds_path)
                        image.save(output_path, "PNG")
                        messagebox.showinfo("Success", f"Exported {file_name} as PNG to {output_path}")
                    except Exception as e:
                        messagebox.showerror("Error", f"Failed to convert DDS to PNG: {e}")
                    finally:
                        if os.path.exists(temp_dds_path):
                            os.remove(temp_dds_path)
                else:
                    with open(output_path, 'wb') as out_f:
                        out_f.write(data)
                    messagebox.showinfo("Success", f"Exported {file_name} to {output_path}")
                return
        messagebox.showerror("Error", "File not found")

    def import_texture(self, file_name, new_file_path):
        if new_file_path.lower().endswith(".png"):
            try:
                image = Image.open(new_file_path)
                image = image.convert("RGBA")  # Convert to BGRA8888 format
                with tempfile.NamedTemporaryFile(delete=False, suffix=".dds") as temp_dds_file:
                    temp_dds_path = temp_dds_file.name
                    image.save(temp_dds_path, "DDS")
                    new_file_path = temp_dds_path
            except Exception as e:
                messagebox.showerror("Error", f"Failed to convert PNG to DDS: {e}")
                return

        with open(new_file_path, 'rb') as new_file:
            new_data = new_file.read()

        for entry in self.entries:
            if entry.name == file_name:
                if len(new_data) > entry.size:
                    messagebox.showerror("Error", "New file is larger than the original")
                    return
                with open(self.filename, 'r+b') as f:
                    f.seek(entry.offset)
                    f.write(new_data)
                    if len(new_data) < entry.size:
                        f.write(b'\x00' * (entry.size - len(new_data)))
                messagebox.showinfo("Success", f"Imported {file_name}")
                return
        messagebox.showerror("Error", "File not found in BIG file")

def read_internal_name(file_path):
    try:
        with open(file_path, 'rb') as file:
            file_content = file.read()
            decoded_text = file_content.decode('utf-8', errors='ignore')
            
            # Internal Name 7002 was not included here because their color and size offsets couldn't be found
            possible_internal_names = ["15002", "2002", "3002", "4002", "5002", "6002", "8002"]

            for internal_name in possible_internal_names:
                if internal_name in decoded_text:
                    return internal_name

            return None
    except Exception as e:
        messagebox.showerror("Error", f"Failed to read internal name: {e}")
        return None

def open_file():
    global file_path, current_image
    file_path = filedialog.askopenfilename(filetypes=[("FIFA Big Files", "*.big")])
    
    if file_path:
        update_status(f"File Loaded: {file_path}", "blue")
        add_internal_name()
        load_current_values()
        extract_and_display_texture()  # Extract and display the "11" texture

        # Reset the preview area
        preview_canvas.delete("all")
        current_image = None
        texture_label.config(text="")
        image_dimensions_label.config(text="")


current_image_index = 0
image_files = [str(i) for i in range(1, 81)]

def extract_and_display_texture():
    global file_path, preview_canvas, current_image, current_image_index, image_dimensions_label

    if not file_path:
        return False

    try:
        with open(file_path, 'rb') as f:
            # Read Magic Header
            magic = f.read(4).decode('ascii')
            if magic not in ('BIGF', 'BIG4'):
                return False

            # Read File Counts and Header Size
            total_size = struct.unpack('<I', f.read(4))[0]
            n_files = struct.unpack('<I', f.read(4))[0]
            header_size = struct.unpack('<I', f.read(4))[0]

            found = False
            dds_data = None
            image_file = image_files[current_image_index]

            # Read File Entries
            for _ in range(n_files):
                def swap_endian(value):
                    return struct.unpack('<I', struct.pack('>I', value))[0]  # Swap Big ↔ Little

                start_pos = swap_endian(struct.unpack('<I', f.read(4))[0])
                size = swap_endian(struct.unpack('<I', f.read(4))[0])
                name_bytes = bytearray()
                if size > 10_000_000:  # If size is unreasonably big (>10MB)
                    size = swap_endian(size)  # Swap again if necessary
                # Read Filename (Null-Terminated)
                while (byte := f.read(1)) != b'\x00':
                    name_bytes.extend(byte)

                file_name = name_bytes.decode('ascii')

                if file_name == image_file:  # Locate Scoreboard Texture
                    found = True
                    if size == 0:
                        return False

                    f.seek(start_pos)
                    dds_data = f.read(size)
                    break  # Stop Searching

            if not found:
                return False
            
            # Validate DDS Header
            if len(dds_data) < 128 or dds_data[:4] != b'DDS ':
                return False

            # Save DDS Temporarily
            with tempfile.NamedTemporaryFile(delete=False, suffix=".dds") as temp_dds_file:
                temp_dds_path = temp_dds_file.name
                temp_dds_file.write(dds_data)

            # Convert DDS to Image and Display
            try:
                image = Image.open(temp_dds_path)
                image.thumbnail((600, 300))  # Set default size

                # Create a white background image
                background = Image.new('RGBA', image.size, (255, 255, 255, 255))
                combined = Image.alpha_composite(background, image.convert('RGBA'))

                img_tk = ImageTk.PhotoImage(combined)

                preview_canvas.delete("all")  # Clear previous image
                preview_canvas.create_image(0, 0, anchor=tk.NW, image=img_tk)
                preview_canvas.image_ref = img_tk  # Store reference in a persistent attribute
                global current_image
                current_image = combined  # Store original image

                # Update the texture label to show the file name with .dds extension
                texture_label.config(text=f"{file_name}.dds")

                # Update the image dimensions label
                image_dimensions_label.config(text=f"{image.width}x{image.height}")

                return True
            except Exception:
                pass
            finally:
                os.remove(temp_dds_path)  # Cleanup

    except Exception:
        pass

    return False

zoom_level = 1.0  # Default zoom

def zoom_image(event):
    global zoom_level, current_image

    if current_image is None:
        return

    # Adjust zoom factor (scroll up = zoom in, scroll down = zoom out)
    if event.delta > 0:
        zoom_level *= 1.1  # Zoom in
    else:
        zoom_level /= 1.1  # Zoom out

    # Resize image
    new_width = int(current_image.width * zoom_level)
    new_height = int(current_image.height * zoom_level)
    resized_image = current_image.resize((new_width, new_height), Image.LANCZOS)

    # Update Tkinter preview
    img_tk = ImageTk.PhotoImage(resized_image)
    preview_canvas.create_image(0, 0, anchor=tk.NW, image=img_tk)
    preview_canvas.image_ref = img_tk  # Prevent garbage collection
    
drag_data = {"x": 0, "y": 0, "item": None}  # Store drag start position and item

def start_drag(event):
    drag_data["x"] = event.x
    drag_data["y"] = event.y
    drag_data["item"] = preview_canvas.find_closest(event.x, event.y)

def on_drag(event):
    dx = event.x - drag_data["x"]
    dy = event.y - drag_data["y"]
    preview_canvas.move(drag_data["item"], dx, dy)
    drag_data["x"] = event.x
    drag_data["y"] = event.y

def load_current_values():
    global file_path, previous_file_path, previous_offsets_values, previous_color_values  # Declare globals
    if not file_path:
        return
    
    with open(file_path, 'rb') as file:
        for offset_list in list(offsets_values.keys()):
            for offset in offset_list:
                file.seek(offset)
                data = file.read(4)
                value = struct.unpack('<f', data)[0]
                offsets_vars[tuple(offset_list)].set(value)
                # Update previous values as well
                previous_offsets_values[offset] = value
        
        for offset_list in list(color_values.keys()):
            for offset in offset_list:
                file.seek(offset)
                data = file.read(4)
                # Read the color in little-endian format
                color_code = f'#{data[2]:02X}{data[1]:02X}{data[0]:02X}'
                color_values[tuple(offset_list)] = color_code
                color_vars[tuple(offset_list)].set(color_code)
                color_previews[tuple(offset_list)].config(bg=color_code)
                # Update previous color values as well
                previous_color_values[offset] = color_code

def add_internal_name():
    global file_path, previous_file_path, previous_offsets_values, previous_color_values  # Declare globals
    internal_name = read_internal_name(file_path)
    if internal_name:
        internal_name_label.config(text=f"Internal Name: {internal_name}")
        set_offsets_and_colors(internal_name)
        # Store the current file path and values as the last valid ones
        previous_file_path = file_path
        previous_offsets_values = {offset: offsets_vars[offset].get() for offset in offsets_vars}
        previous_color_values = {offset: color_vars[offset].get() for offset in color_vars}
    else:
        messagebox.showerror("Error", "No internal name was detected. Reverting back to the previous file.")
        if previous_file_path:
            file_path = previous_file_path
            load_previous_values()
        else:
            update_status("No valid file to revert to.", "red")
        return

def load_previous_values():
    global file_path  # Declare file_path as global
    if previous_file_path:
        file_path = previous_file_path
        for offset in previous_offsets_values:
            offsets_vars[offset].set(previous_offsets_values[offset])
        for offset in previous_color_values:
            color_vars[offset].set(previous_color_values[offset])
            color_previews[offset].config(bg=previous_color_values[offset])
        update_status(f"Reverted to previous file: {file_path}", "orange")

def set_offsets_and_colors(internal_name):
    global offsets, colors
    if (internal_name in offsets_data):
        offsets = {k: [int(v, 16) for v in (v if isinstance(v, list) else [v])] for k, v in offsets_data[internal_name]["offsets"].items()}
        colors = {k: [int(v, 16) for v in (v if isinstance(v, list) else [v])] for k, v in offsets_data[internal_name]["colors"].items()}
    else:
        messagebox.showerror("Error", "Invalid internal name detected.")
        return

    recreate_widgets()

def recreate_widgets():
    global offsets_vars, offsets_values, color_vars, color_values, color_previews

    # Clear previous widgets
    for widget in positions_frame.winfo_children():
        widget.destroy()
    for widget in sizes_frame.winfo_children():
        widget.destroy()
    for widget in colors_frame.winfo_children():
        widget.destroy()

    # Define new variables and values
    offsets_vars = {tuple(offsets): tk.StringVar() for offsets in offsets.values()}
    offsets_values = {tuple(offsets): 0.0 for offsets in offsets.values()}
    color_vars = {tuple(offsets): tk.StringVar(value='#000000') for offsets in colors.values()}
    color_values = {tuple(offsets): "#000000" for offsets in colors.values()}
    color_previews = {}

    # Add positions to Positions tab
    row = 0
    for label_text, offset_list in offsets.items():
        if "Size" not in label_text:
            col = 0 if "X" in label_text else 4
            tk.Label(positions_frame, text=label_text).grid(row=row, column=col, padx=10, pady=5)
            entry = tk.Entry(positions_frame, textvariable=offsets_vars[tuple(offset_list)])
            entry.grid(row=row, column=col+1, padx=10, pady=5)
            entry.bind("<KeyRelease>", lambda e, offset_list=offset_list, var=offsets_vars[tuple(offset_list)]: update_value(offset_list, var))
            entry.bind('<KeyPress-Up>', lambda e, var=offsets_vars[tuple(offset_list)]: increment_value(e, var))
            entry.bind('<KeyPress-Down>', lambda e, var=offsets_vars[tuple(offset_list)]: increment_value(e, var))
            if col == 4:
                row += 1

    # Add sizes to Sizes tab
    row = 0
    for label_text, offset_list in offsets.items():
        if "Size" in label_text:
            tk.Label(sizes_frame, text=label_text).grid(row=row, column=0, padx=10, pady=5)
            entry = tk.Entry(sizes_frame, textvariable=offsets_vars[tuple(offset_list)])
            entry.grid(row=row, column=1, padx=10, pady=5)
            entry.bind("<KeyRelease>", lambda e, offset_list=offset_list, var=offsets_vars[tuple(offset_list)]: update_value(offset_list, var))
            entry.bind('<KeyPress-Up>', lambda e, var=offsets_vars[tuple(offset_list)]: increment_value(e, var))
            entry.bind('<KeyPress-Down>', lambda e, var=offsets_vars[tuple(offset_list)]: increment_value(e, var))
            row += 1

    # Add colors to Colors tab
    row = 0
    for label_text, offset_list in colors.items():
        tk.Label(colors_frame, text=label_text).grid(row=row, column=0, padx=10, pady=5)
        entry = tk.Entry(colors_frame, textvariable=color_vars[tuple(offset_list)])
        entry.grid(row=row, column=1, padx=10, pady=5)
        entry.bind('<KeyPress>', lambda e, var=color_vars[tuple(offset_list)]: restrict_color_entry(e, var))
        entry.bind('<KeyRelease>', lambda e, offset_list=offset_list, var=color_vars[tuple(offset_list)]: update_color_preview(tuple(offset_list), var.get()))
        color_preview = tk.Label(colors_frame, bg=color_values[tuple(offset_list)], width=2)
        color_preview.grid(row=row, column=2, padx=10, pady=5)
        color_preview.bind("<Button-1>", lambda e, offset_list=offset_list, var=color_vars[tuple(offset_list)]: choose_color(tuple(offset_list), var))
        color_previews[tuple(offset_list)] = color_preview
        update_func = lambda offset_list=offset_list, var=color_vars[tuple(offset_list)]: update_color(tuple(offset_list), var)
        tk.Button(colors_frame, text="Update", command=update_func).grid(row=row, column=3, padx=10, pady=5)
        row += 1

def save_file():
    global file_path
    if not file_path:
        messagebox.showerror("Error", "No file loaded.")
        return
    
    try:
        with open(file_path, 'r+b') as file:  # Open the file in read and write binary mode
            # First, read the entire content of the file
            file_content = file.read()
            file.seek(0)  # Rewind to the beginning of the file

            # Update all offsets with the current values
            for offset_list, var in offsets_vars.items():
                value = var.get()
                try:
                    # Ensure the value is a float
                    value = float(value)
                    packed_value = struct.pack('<f', value)
                    # Debug: Print the value and packed bytes
                    print(f"Offsets: {offset_list}, Value: {value}, Packed: {packed_value.hex()}")
                    for offset in offset_list:
                        # Ensure correct file positioning
                        file.seek(offset)
                        file.write(packed_value)
                except ValueError:
                    messagebox.showerror("Error", f"Invalid float value at offsets {offset_list}: {value}")
                    return

            for offset_list, var in color_vars.items():
                color_code = var.get()
                try:
                    # Convert color to little-endian format and pack it
                    color_bytes = bytes.fromhex(color_code[1:])[::-1]
                    # Debug: Print the color code and packed bytes
                    print(f"Offsets: {offset_list}, Color Code: {color_code}, Packed: {color_bytes.hex()}")
                    for offset in offset_list:
                        # Ensure correct file positioning
                        file.seek(offset)
                        file.write(color_bytes)
                except ValueError:
                    messagebox.showerror("Error", f"Invalid color code at offsets {offset_list}: {color_code}")
                    return

        update_status("File saved successfully.", "green")

    except Exception as e:
        messagebox.showerror("Error", f"Failed to save file: {e}")

def update_value(offset_list, var):
    try:
        value = float(var.get())
        offsets_values[tuple(offset_list)] = value
        update_status("Value Updated!", "green")
    except ValueError:
        update_status("Invalid value", "red")

def increment_value(event, var):
    try:
        value = float(var.get())
        if event.state & 0x0001:  # Shift key
            value += 0.1 if event.keysym == 'Up' else -0.1
        else:
            value += 1.0 if event.keysym == 'Up' else -1.0
        var.set(round(value, 1))
    except ValueError:
        update_status("Invalid value", "red")

def update_color_preview(offset, color):
    color_previews[offset].config(bg=color)

def choose_color(offset, var):
    color_code = colorchooser.askcolor()[1]
    if color_code:
        var.set(color_code)
        update_color_preview(offset, color_code)

def update_color(offset_list, var):
    color_values[tuple(offset_list)] = var.get()
    update_color_preview(tuple(offset_list), var.get())

def update_status(message, color):
    status_label.config(text=message, fg=color)

def about():
    about_window = tk.Toplevel(root)
    about_window.title("About")
    about_window.geometry("420x270")
    about_window.resizable(False, False)
    bold_font = ("Helvetica", 12, "bold")
    tk.Label(about_window, text="FLP Scoreboard Editor 25 By FIFA Legacy Project.", pady=10, font=bold_font).pack()
    tk.Label(about_window, text="Version 1.0 [Build 12 March 2025]", pady=10).pack()
    tk.Label(about_window, text="© 2025 FIFA Legacy Project. All Rights Reserved.", pady=10).pack()
    tk.Label(about_window, text="Designed & Developed By Emran_Ahm3d.", pady=10).pack()
    tk.Label(about_window, text="Special Thanks to Riesscar, KO, MCK and Marconis for the Research.", pady=10).pack()
    tk.Label(about_window, text="Discord: @emran_ahm3d", pady=10).pack()

def show_documentation():
    webbrowser.open("https://soccergaming.com/")

def restrict_color_entry(event, var):
    if event.keysym == 'BackSpace' and var.get() == '#':
        return 'break'

def exit_app():
    if messagebox.askyesno("Exit", "Are you sure you want to exit?"):
        root.destroy()

import imageio

def import_texture():
    global file_path, current_image_index, image_files, current_image

    if not file_path:
        messagebox.showerror("Error", "No file loaded.")
        return

    bigfile = FifaBigFile(file_path)
    file_name = image_files[current_image_index]  # Use the currently previewed file
    new_file_path = filedialog.askopenfilename(filetypes=[("DDS Files", "*.dds")])
    if not new_file_path:
        return

    try:
        with open(new_file_path, 'rb') as new_file:
            new_data = new_file.read()

        # Check the size of the original file
        original_size = None
        for entry in bigfile.entries:
            if entry.name == file_name:
                original_size = entry.size
                break

        if original_size is None:
            messagebox.showerror("Error", "Original file size not found.")
            return

        if len(new_data) > original_size:
            messagebox.showerror("Error", "New file is larger than the original.")
            return

        with open(bigfile.filename, 'r+b') as f:
            for entry in bigfile.entries:
                if entry.name == file_name:
                    f.seek(entry.offset)
                    f.write(new_data)
                    if len(new_data) < entry.size:
                        f.write(b'\x00' * (entry.size - len(new_data)))
                    bigfile.modified = True
                    messagebox.showinfo("Success", f"Imported {file_name}")

                    # Update the preview canvas with the new image
                    try:
                        with Image.open(new_file_path) as image:
                            image.thumbnail((600, 300))  # Set default size

                            # Create a white background image
                            background = Image.new('RGBA', image.size, (255, 255, 255, 255))
                            combined = Image.alpha_composite(background, image.convert('RGBA'))

                            img_tk = ImageTk.PhotoImage(combined)

                            preview_canvas.delete("all")  # Clear previous image
                            preview_canvas.create_image(0, 0, anchor=tk.NW, image=img_tk)
                            preview_canvas.image_ref = img_tk  # Store reference in a persistent attribute
                            current_image = combined  # Store original image

                            # Update the texture label to show the file name with .dds extension
                            texture_label.config(text=f"{file_name}.dds")
                    except Exception as e:
                        messagebox.showerror("Error", f"Failed to update preview: {e}")

                    return
    except Exception as e:
        messagebox.showerror("Error", f"Failed to import DDS: {e}")
        return

    messagebox.showerror("Error", "File not found in BIG file")

def export_selected_file():
    global file_path, current_image_index, image_files
    if not file_path:
        messagebox.showerror("Error", "No file loaded.")
        return

    bigfile = FifaBigFile(file_path)
    file_name = image_files[current_image_index]  # Use the currently previewed file

    # Ask the user for the export format
    export_format = filedialog.asksaveasfilename(
        defaultextension=".png",
        filetypes=[("PNG Files", "*.png")],
        initialfile=os.path.basename(file_name)
    )
    if not export_format:
        return

    for entry in bigfile.entries:
        if entry.name == file_name:
            data = entry.data
            file_type = bigfile.detect_file_type(data)

            if file_type == "[DDS]":
                with tempfile.NamedTemporaryFile(delete=False, suffix=".dds") as temp_file:
                    temp_dds_path = temp_file.name
                    temp_file.write(data)

                try:
                    image = Image.open(temp_dds_path)
                    image.save(export_format, "PNG")
                    messagebox.showinfo("Success", f"Exported {file_name} as PNG to {export_format}")
                except Exception as e:
                    messagebox.showerror("Error", f"Failed to convert DDS to PNG: {e}")
                finally:
                    if os.path.exists(temp_dds_path):
                        os.remove(temp_dds_path)
            else:
                with open(export_format, 'wb') as out_f:
                    out_f.write(data)
                messagebox.showinfo("Success", f"Exported {file_name} to {export_format}")
            return
    messagebox.showerror("Error", "File not found")

def previous_image():
    global current_image_index
    while True:
        current_image_index = (current_image_index - 1) % len(image_files)
        if extract_and_display_texture():
            break

def next_image():
    global current_image_index
    while True:
        current_image_index = (current_image_index + 1) % len(image_files)
        if extract_and_display_texture():
            break

# Main Window
root = tk.Tk()
root.title("FLP Scoreboard Editor 25 (v1.0)")
root.geometry("930x680")
root.resizable(False, False)

# Menu
menubar = tk.Menu(root)
filemenu = tk.Menu(menubar, tearoff=0)
filemenu.add_command(label="Open                        ", command=open_file)
filemenu.add_command(label="Save", command=save_file)
filemenu.add_separator()
filemenu.add_command(label="Exit", command=exit_app)
menubar.add_cascade(label="    File    ", menu=filemenu)

helpmenu = tk.Menu(menubar, tearoff=0)
helpmenu.add_command(label="About                        ", command=about)
helpmenu.add_separator()
helpmenu.add_command(label="Documentation", command=show_documentation)
menubar.add_cascade(label="    Help    ", menu=helpmenu)

root.config(menu=menubar)

# Tabs
notebook = ttk.Notebook(root)
positions_frame = ttk.Frame(notebook)
sizes_frame = ttk.Frame(notebook)
colors_frame = ttk.Frame(notebook)

notebook.add(positions_frame, text="Positions")
notebook.add(sizes_frame, text="Sizes")
notebook.add(colors_frame, text="Colors")
notebook.pack(expand=1, fill="both")

# Frame for Scoreboard Texture Preview
preview_frame = tk.Frame(root)
preview_frame.pack(fill=tk.X, padx=10, pady=18)

# Left arrow button
left_arrow_button = ttk.Button(preview_frame, text="◀", style="Large.TButton", command=previous_image, width=3)
left_arrow_button.pack(side=tk.LEFT, padx=5)

# Adjust the width of the canvas and add padding to the right
preview_canvas = tk.Canvas(preview_frame, width=650, height=150, bg="gray", relief="solid")
preview_canvas.pack(side=tk.LEFT, padx=(0, 5))  # Add padding to the right

preview_canvas.bind("<MouseWheel>", zoom_image)
preview_canvas.bind("<ButtonPress-1>", start_drag)  # Start dragging on left click
preview_canvas.bind("<B1-Motion>", on_drag)         # Move when dragging

# Right arrow button
right_arrow_button = ttk.Button(preview_frame, text="▶", style="Large.TButton", command=next_image, width=3)
right_arrow_button.pack(side=tk.LEFT, padx=5)

# Label for displaying the current texture's label
texture_label = tk.Label(root, text="", font=('Helvetica', 12))
texture_label.place(relx=1.0, rely=1.0, anchor='se', x=-20, y=-150)

# Add a new label for displaying image dimensions
image_dimensions_label = tk.Label(root, text="", font=('Helvetica', 10))
image_dimensions_label.place(x=660, y=640)

def place_save_button():
    import_button = ttk.Button(root, text="IMPORT", style="Large.TButton", command=import_texture, width=10)
    import_button.place(relx=1.0, rely=1.0, anchor='se', x=-20, y=-110)

    export_button = ttk.Button(root, text="EXPORT", style="Large.TButton", command=export_selected_file, width=10)
    export_button.place(relx=1.0, rely=1.0, anchor='se', x=-20, y=-70)

    save_button = ttk.Button(root, text="SAVE", style="Large.TButton", command=save_file, width=10)
    save_button.place(relx=1.0, rely=1.0, anchor='se', x=-20, y=-30)

# Frame to hold both labels
bottom_frame = tk.Frame(root)
bottom_frame.pack(side=tk.BOTTOM, fill=tk.X)

# Internal Name Label
internal_name_label = tk.Label(bottom_frame, text="Internal Name: Not Loaded", anchor=tk.E, font=('Helvetica', 10))
internal_name_label.pack(side=tk.RIGHT, padx=10, pady=0)

# Status Bar
status_label = tk.Label(bottom_frame, text="Ready", anchor=tk.W, fg="blue", font=('Helvetica', 10))
status_label.pack(side=tk.LEFT, padx=5, pady=0)

# Define a function to place the SAVE button at the bottom right
def place_save_button():
    import_button = ttk.Button(root, text="IMPORT", style="Large.TButton", command=import_texture, width=10)
    import_button.place(relx=1.0, rely=1.0, anchor='se', x=-20, y=-110)

    export_button = ttk.Button(root, text="EXPORT", style="Large.TButton", command=export_selected_file, width=10)
    export_button.place(relx=1.0, rely=1.0, anchor='se', x=-20, y=-70)

    save_button = ttk.Button(root, text="SAVE", style="Large.TButton", command=save_file, width=10)
    save_button.place(relx=1.0, rely=1.0, anchor='se', x=-20, y=-30)

# Add the SAVE button
root.style = ttk.Style()
root.style.configure('Large.TButton', font=('Helvetica', 15), foreground='green')
place_save_button()

# Recreate the widgets based on the internal name
if file_path:
    add_internal_name()

root.mainloop()