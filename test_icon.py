import tkinter as tk
import sys

root = tk.Tk()
try:
    root.iconbitmap("scale.ico")
    print("Icon loaded successfully!")
except Exception as e:
    print(f"Failed to load icon: {e}")
    sys.exit(1)
root.after(1000, root.destroy)
root.mainloop()
