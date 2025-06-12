import logging
import struct
from typing import Optional, List

from core import Compression, FileEntry

# --- Binary and File Handling Classes ---

class BinaryReader:
    """Helper class for reading data from a byte array."""
    def __init__(self, data: bytearray):
        self.data = data
        self.pos = 0

    def read_byte(self) -> int:
        if self.pos >= len(self.data): raise ValueError("End of stream: cannot read byte")
        v = self.data[self.pos]
        self.pos += 1
        return v

    def read_int(self, count: int = 4, big_endian: bool = False) -> int:
        if self.pos + count > len(self.data): raise ValueError(f"End of stream: cannot read {count} bytes for int")
        chunk = self.data[self.pos : self.pos + count]
        self.pos += count
        return int.from_bytes(chunk, "big" if big_endian else "little")

    def read_string(self, encoding: str, length: Optional[int] = None) -> str:
        if length is not None:
            if self.pos + length > len(self.data):
                raise ValueError(f"Not enough data to read string of length {length}")
            b = self.data[self.pos : self.pos + length]
            self.pos += length
            return b.decode(encoding, errors="ignore").rstrip('\x00')
        else: # Null-terminated
            start_pos = self.pos
            while self.pos < len(self.data) and self.data[self.pos] != 0:
                self.pos += 1
            b = self.data[start_pos : self.pos]
            if self.pos < len(self.data) and self.data[self.pos] == 0:
                self.pos += 1
            return b.decode(encoding, errors="ignore")

    def skip(self, count: int):
        self.pos = min(len(self.data), self.pos + count)


class Decompressor:
    """Handles decompression of file data."""
    @staticmethod
    def detect_compression(data: bytes) -> Compression:
        return Compression.EAHD if len(data) >= 2 and data[:2] == b"\xfb\x10" else Compression.NONE

    @staticmethod
    def decompress_eahd(data: bytes) -> bytes:
        try:
            reader = BinaryReader(bytearray(data))
            if reader.read_int(2, True) != 0xFB10: return data
            total_size = reader.read_int(3, True)
            out = bytearray(total_size)
            pos = 0
            while reader.pos < len(reader.data) and pos < total_size:
                ctrl = reader.read_byte()
                to_read = 0
                to_copy = 0
                off_val = 0
                if ctrl < 0x80:
                    a = reader.read_byte()
                    to_read = ctrl & 0x03
                    to_copy = ((ctrl & 0x1C) >> 2) + 3
                    off_val = ((ctrl & 0x60) << 3) + a + 1
                elif ctrl < 0xC0:
                    a, b = reader.read_byte(), reader.read_byte()
                    to_read = (a >> 6) & 0x03
                    to_copy = (ctrl & 0x3F) + 4
                    off_val = ((a & 0x3F) << 8) + b + 1
                elif ctrl < 0xE0:
                    a, b, c = reader.read_byte(), reader.read_byte(), reader.read_byte()
                    to_read = ctrl & 0x03
                    to_copy = ((ctrl & 0x0C) << 6) + c + 5
                    off_val = ((ctrl & 0x10) << 12) + (a << 8) + b + 1
                elif ctrl < 0xFC:
                    to_read = ((ctrl & 0x1F) << 2) + 4
                else:
                    to_read = ctrl & 0x03

                if pos + to_read > total_size: to_read = total_size - pos
                for _ in range(to_read):
                    if reader.pos >= len(reader.data): break
                    out[pos] = reader.read_byte()
                    pos += 1

                if to_copy > 0:
                    copy_start = pos - off_val
                    if copy_start < 0:
                        logging.error("EAHD: Invalid copy offset.")
                        return data
                    if pos + to_copy > total_size: to_copy = total_size - pos
                    for _ in range(to_copy):
                        if copy_start >= pos:
                            logging.error("EAHD: copy_start >= pos.")
                            return data
                        out[pos] = out[copy_start]
                        pos += 1
                        copy_start += 1
            return bytes(out[:pos])
        except ValueError as e:
            logging.error(f"EAHD Decompression ValueError: {e}")
            return data
        except Exception as e:
            logging.error(f"EAHD Decompression Exception: {e}", exc_info=True)
            return data


class Compressor:
    """Handles compression of file data."""
    @staticmethod
    def compress_eahd(data: bytes) -> bytes:
        # NOTE: EAHD compression is not implemented.
        logging.warning("EAHD COMPRESSION IS NOT IMPLEMENTED. Returning uncompressed data.")
        return data


class FifaBigFile:
    """Class to read and parse FIFA .big archives."""
    def __init__(self, filename: str):
        self.filename = filename
        self.entries: List[FileEntry] = []
        self._load()

    def _load(self):
        try:
            with open(self.filename, 'rb') as f:
                data_content = bytearray(f.read())
        except FileNotFoundError:
            logging.error(f"BIG file not found: {self.filename}")
            raise

        reader = BinaryReader(data_content)
        try:
            magic = bytes(data_content[:4])
            if magic not in (b'BIGF', b'BIG4'):
                raise ValueError(f"Invalid BIG magic: {magic.decode(errors='ignore')}")
            reader.skip(4)
            reader.read_int(4, False)
            num_entries = reader.read_int(4, True)
            reader.read_int(4, True)
        except ValueError as e:
            logging.error(f"BIG header error: {e}")
            raise

        content_type_tag = "DAT"
        for i in range(num_entries):
            try:
                entry_offset = reader.read_int(4, True)
                entry_raw_size = reader.read_int(4, True)
                entry_name = reader.read_string('utf-8')
            except ValueError as e:
                logging.error(f"Entry read error at index {i}: {e}")
                continue

            if entry_raw_size == 0 and entry_name in {"sg1", "sg2"}:
                content_type_tag = {"sg1": "DDS", "sg2": "APT"}[entry_name]
                self.entries.append(FileEntry(entry_offset, 0, entry_name, content_type_tag, Compression.NONE, b"", 0))
                continue

            actual_raw_size = entry_raw_size
            if entry_offset + entry_raw_size > len(data_content):
                actual_raw_size = len(data_content) - entry_offset
                if actual_raw_size < 0:
                    actual_raw_size = 0
            
            raw_data = bytes(data_content[entry_offset : entry_offset + actual_raw_size])
            compression_type = Decompressor.detect_compression(raw_data)
            decompressed_data = Decompressor.decompress_eahd(raw_data) if compression_type == Compression.EAHD else raw_data
            
            determined_file_type = content_type_tag
            if decompressed_data[:4] == b'DDS ':
                determined_file_type = "DDS"
            
            self.entries.append(FileEntry(
                entry_offset, len(decompressed_data), entry_name, determined_file_type,
                compression_type, decompressed_data, entry_raw_size
            ))
            
    def list_files(self) -> List[str]:
        return [e.name for e in self.entries if e.size > 0]