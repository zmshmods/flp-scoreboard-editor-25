import logging
from dataclasses import dataclass
from enum import Enum
from typing import List, Any, Optional

# --- Enums and Data Classes ---

class Compression(Enum):
    """Enumeration for compression types."""
    NONE = "None"
    EAHD = "EAHD"

@dataclass
class FileEntry:
    """Represents a single file entry within a .big archive."""
    offset: int
    size: int
    name: str
    file_type: str
    compression: Compression
    data: bytes
    raw_size: int

@dataclass
class EditAction:
    """Represents a single undoable/redoable action."""
    string_var: Any  # tk.StringVar
    old_value: str
    new_value: str
    key_tuple: tuple
    entry_widget_ref: Any  # tk.Widget
    description: str = "value change"

    def __str__(self):
        return f"EditAction({self.description}: {self.old_value} -> {self.new_value})"

# --- Core Logic Classes ---

class UndoManager:
    """Manages undo and redo stacks for application actions."""
    def __init__(self, app_instance, max_history=50):
        self.app = app_instance
        self.undo_stack: List[EditAction] = []
        self.redo_stack: List[EditAction] = []
        self.max_history = max_history

    def record_action(self, action: EditAction):
        """Records a new action, clearing the redo stack."""
        self.redo_stack.clear()
        self.undo_stack.append(action)
        if len(self.undo_stack) > self.max_history:
            self.undo_stack.pop(0)
        self.app.update_menu_states()
        logging.debug(f"Recorded action: {action}")

    def can_undo(self):
        return bool(self.undo_stack)

    def can_redo(self):
        return bool(self.redo_stack)

    def perform_undo(self):
        """
        Pops an action from the undo stack, moves it to redo, and returns it.
        The caller is responsible for applying the action's effects.
        """
        if not self.can_undo():
            return None
        action = self.undo_stack.pop()
        self.redo_stack.append(action)
        self.app.update_menu_states()
        logging.info(f"Undone: {action}")
        return action

    def perform_redo(self):
        """
        Pops an action from the redo stack, moves it to undo, and returns it.
        The caller is responsible for applying the action's effects.
        """
        if not self.can_redo():
            return None
        action = self.redo_stack.pop()
        self.undo_stack.append(action)
        self.app.update_menu_states()
        logging.info(f"Redone: {action}")
        return action

    def clear_history(self):
        """Clears both undo and redo stacks."""
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.app.update_menu_states()
        logging.info("Undo/Redo history cleared.")