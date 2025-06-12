import tkinter as tk
from gui import App

if __name__ == "__main__":
    """
    Main entry point for the application.
    Initializes the Tkinter root window and the main App class.
    """
    try:
        root = tk.Tk()
        app = App(root)
        root.mainloop()
    except Exception as e:
        # Fallback for critical errors during initialization
        import traceback
        from tkinter import messagebox
        
        # Hide the blank root window if it exists
        if 'root' in locals() and root.winfo_exists():
            root.withdraw()

        error_message = f"A critical error occurred and the application must close.\n\n" \
                        f"Error: {e}\n\n" \
                        f"Please check the log file for more details."
        
        messagebox.showerror("Critical Error", error_message)
        traceback.print_exc()