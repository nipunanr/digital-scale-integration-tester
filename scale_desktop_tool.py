import tkinter as tk
from tkinter import scrolledtext, ttk
import asyncio
import websockets
import threading
import socket
import time
import random
import json
import sys
import os

def get_resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

# ---------------------------------------------------------------------------
# Asyncio WebSocket Bridge Server
# ---------------------------------------------------------------------------
async def tcp_to_ws(reader, websocket, log_callback):
    try:
        while True:
            data = await reader.read(4096)
            if not data:
                break
            text_data = data.decode('utf-8', errors='replace')
            await websocket.send(json.dumps({"event": "data", "data": text_data}))
    except Exception as e:
        log_callback(f"[Bridge] TCP read error: {e}")
    finally:
        try:
            await websocket.send(json.dumps({"event": "disconnected"}))
        except:
            pass

async def handle_ws_client(websocket, path, log_callback):
    log_callback(f"[Bridge] Browser connected from {websocket.remote_address}")
    active_tcp = None
    try:
        async for message in websocket:
            try:
                cmd = json.loads(message)
            except json.JSONDecodeError:
                continue
                
            action = cmd.get("action")
            if action == "connect":
                ip = cmd.get("ip")
                port = int(cmd.get("port", 8101))
                timeout = cmd.get("timeout", 3000) / 1000.0
                
                log_callback(f"[Bridge] Connecting to Scale at {ip}:{port}...")
                try:
                    fut = asyncio.open_connection(ip, port)
                    reader, writer = await asyncio.wait_for(fut, timeout=timeout)
                    active_tcp = writer
                    
                    await websocket.send(json.dumps({
                        "event": "connected", "ip": ip, "port": port
                    }))
                    log_callback(f"[Bridge] Connected to {ip}:{port}")
                    
                    asyncio.create_task(tcp_to_ws(reader, websocket, log_callback))
                except asyncio.TimeoutError:
                    log_callback("[Bridge] Connection timed out")
                    await websocket.send(json.dumps({"event": "error", "message": "Connection timed out"}))
                except Exception as e:
                    log_callback(f"[Bridge] Connection failed: {e}")
                    await websocket.send(json.dumps({"event": "error", "message": str(e)}))
                    
            elif action == "disconnect":
                if active_tcp:
                    active_tcp.close()
                    active_tcp = None
                    await websocket.send(json.dumps({"event": "disconnected"}))
                    log_callback("[Bridge] Disconnected from scale")
    except websockets.exceptions.ConnectionClosed:
        log_callback("[Bridge] Browser disconnected.")
    finally:
        if active_tcp:
            active_tcp.close()

def start_asyncio_server(loop, log_callback, app):
    asyncio.set_event_loop(loop)
    async def handler(websocket, path):
        await handle_ws_client(websocket, path, log_callback)
    
    try:
        start_server = websockets.serve(handler, '0.0.0.0', app.bridge_port)
        app.bridge_server = loop.run_until_complete(start_server)
        log_callback(f"[Bridge] Running on ws://0.0.0.0:{app.bridge_port}")
        loop.run_forever()
    except Exception as e:
        log_callback(f"[Bridge] Server error: {e}")
    finally:
        # Crucial for cleaning up port bindings on Windows so it can be restarted!
        if hasattr(app, 'bridge_server') and app.bridge_server:
            app.bridge_server.close()
            loop.run_until_complete(app.bridge_server.wait_closed())
            app.bridge_server = None

# ---------------------------------------------------------------------------
# Mock TCP Scale Server
# ---------------------------------------------------------------------------
def handle_mock_client(conn, addr, log_callback, app):
    log_callback(f"[Mock Scale] Client connected from {addr}")
    try:
        weight = 2000.0
        while app.mock_running:
            weight += random.uniform(-1.5, 1.5)
            
            decimals = getattr(app, 'mock_decimals', 2)
            t_sep = getattr(app, 'mock_thousands_sep', ',')
            d_sep = getattr(app, 'mock_decimal_sep', '.')
            
            if t_sep == "Space":
                t_sep = " "
            elif t_sep == "None":
                t_sep = ""
                
            format_str = f"{{:,.{decimals}f}}"
            weight_str = format_str.format(weight)
            
            if t_sep != ',' or d_sep != '.':
                weight_str = weight_str.replace(',', 'X_TEMP_T_X')
                weight_str = weight_str.replace('.', 'X_TEMP_D_X')
                weight_str = weight_str.replace('X_TEMP_T_X', t_sep)
                weight_str = weight_str.replace('X_TEMP_D_X', d_sep)
            
            pattern = getattr(app, 'mock_pattern', "US,GS, {weight_str:>9}kg\\r\\n")
            pattern = pattern.replace('\\r', '\r').replace('\\n', '\n')
            
            try:
                data = pattern.format(weight=weight, weight_str=weight_str)
            except Exception:
                data = f"US,GS, {weight_str:>9}kg\r\n"
                
            conn.sendall(data.encode('ascii'))
            time.sleep(0.5)
    except Exception:
        pass
    finally:
        log_callback(f"[Mock Scale] Client {addr} disconnected.")
        conn.close()

def run_mock_scale(log_callback, app):
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    app.mock_server = server
    try:
        server.bind(('0.0.0.0', app.mock_port))
        server.listen(5)
        server.settimeout(1.0)
        log_callback(f"[Mock Scale] Listening on 0.0.0.0:{app.mock_port}")
        
        while app.mock_running:
            try:
                conn, addr = server.accept()
                t = threading.Thread(target=handle_mock_client, args=(conn, addr, log_callback, app))
                t.daemon = True
                t.start()
            except socket.timeout:
                continue
            except Exception as e:
                if app.mock_running:
                    log_callback(f"[Mock Scale] Error: {e}")
    finally:
        server.close()

def run_listener(ip, port, log_callback, app):
    log_callback(f"[Listener] Connecting to {ip}:{port}...")
    try:
        with socket.create_connection((ip, port), timeout=5) as sock:
            log_callback(f"[Listener] Connected to {ip}:{port}")
            sock.settimeout(1.0)
            while app.listener_running:
                try:
                    data = sock.recv(4096)
                    if not data:
                        log_callback("[Listener] Server closed connection.")
                        break
                    try:
                        text = data.decode('utf-8', errors='replace').strip()
                    except:
                        text = repr(data)
                    if text:
                        log_callback(f"[Listener] Data: {text}")
                except socket.timeout:
                    continue
                except Exception as e:
                    if app.listener_running:
                        log_callback(f"[Listener] Error reading data: {e}")
                    break
    except Exception as e:
        log_callback(f"[Listener] Connection failed: {e}")
    finally:
        app.listener_running = False
        def reset_ui():
            if hasattr(app, 'btn_listener'):
                app.btn_listener.config(text="▶ Start Listener", style="Start.TButton")
                app.ent_listener_ip.config(state="normal")
                app.ent_listener_port.config(state="normal")
        try:
            app.root.after(0, reset_ui)
        except Exception:
            pass

# ---------------------------------------------------------------------------
# Modern GUI Application
# ---------------------------------------------------------------------------
class ScaleDesktopApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Digital Scale Integration Tester")
        self.root.geometry("850x650")
        self.root.configure(bg="#f8fafc")
        
        try:
            icon_path = get_resource_path("scale.ico")
            self.root.iconbitmap(default=icon_path)
            self.root.iconbitmap(icon_path)
        except Exception as e:
            import tkinter.messagebox as mb
            mb.showerror("Icon Error", f"Failed to load icon:\n{e}")
        
        # Make UI Modern
        style = ttk.Style()
        if "clam" in style.theme_names():
            style.theme_use("clam")
            
        style.configure("TFrame", background="#f8fafc")
        style.configure("TLabelframe", background="#f8fafc", font=("Segoe UI", 11, "bold"), foreground="#0f172a")
        style.configure("TLabelframe.Label", background="#f8fafc", foreground="#0f172a")
        style.configure("TLabel", background="#f8fafc", font=("Segoe UI", 10), foreground="#334155")
        
        style.configure("Start.TButton", font=("Segoe UI", 10, "bold"), background="#22c55e", foreground="white", padding=6)
        style.map("Start.TButton", background=[("active", "#16a34a")])
        
        style.configure("Stop.TButton", font=("Segoe UI", 10, "bold"), background="#ef4444", foreground="white", padding=6)
        style.map("Stop.TButton", background=[("active", "#dc2626")])
        
        style.configure("TNotebook", background="#f8fafc")
        style.configure("TNotebook.Tab", background="#e2e8f0", padding=[15, 5], font=("Segoe UI", 10, "bold"))
        style.map("TNotebook.Tab", background=[("selected", "#ffffff")], foreground=[("selected", "#0f172a")])
        
        # State
        self.bridge_running = False
        self.mock_running = False
        self.listener_running = False
        self.loop = None
        self.bridge_port = 8181
        self.mock_port = 9101
        
        self.setup_ui()
        self.log("Ready. Use the buttons below to start services.")

    def setup_ui(self):
        # Header
        header = tk.Frame(self.root, bg="#0f172a", pady=15)
        header.pack(fill=tk.X)
        tk.Label(header, text="Digital Scale Integration Tester", font=("Segoe UI", 18, "bold"), bg="#0f172a", fg="white").pack()
        tk.Label(header, text="Developed by Nipuna Rangika", font=("Segoe UI", 10), bg="#0f172a", fg="#94a3b8").pack()
        
        # Notebook for Tabs
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill=tk.BOTH, expand=True, padx=15, pady=15)
        
        # Tab 1: Dashboard
        tab_dashboard = ttk.Frame(notebook)
        notebook.add(tab_dashboard, text=" 🎛️ Dashboard ")
        
        # Controls Frame
        controls = ttk.Frame(tab_dashboard, padding="15")
        controls.pack(fill=tk.X)
        
        # Bridge Controls
        bridge_frame = ttk.LabelFrame(controls, text=" 🌐 Browser WebSocket Bridge ", padding="15")
        bridge_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5)
        
        ttk.Label(bridge_frame, text="WS Port:").grid(row=0, column=0, sticky="w", pady=5)
        self.ent_bridge_port = ttk.Entry(bridge_frame, width=12, font=("Segoe UI", 10))
        self.ent_bridge_port.insert(0, "8181")
        self.ent_bridge_port.grid(row=0, column=1, sticky="w", padx=10, pady=5)
        
        self.btn_bridge = ttk.Button(bridge_frame, text="▶ Start Bridge", style="Start.TButton", command=self.toggle_bridge)
        self.btn_bridge.grid(row=1, column=0, columnspan=2, pady=10, sticky="we")
        
        # Mock Scale Controls
        mock_frame = ttk.LabelFrame(controls, text=" ⚖️ Mock Scale Simulator ", padding="15")
        mock_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=5)
        
        ttk.Label(mock_frame, text="TCP Port:").grid(row=0, column=0, sticky="w", pady=5)
        self.ent_mock_port = ttk.Entry(mock_frame, width=12, font=("Segoe UI", 10))
        self.ent_mock_port.insert(0, "9101")
        self.ent_mock_port.grid(row=0, column=1, sticky="w", padx=10, pady=5)
        
        ttk.Label(mock_frame, text="Data Pattern:").grid(row=1, column=0, sticky="w", pady=5)
        self.ent_mock_pattern = ttk.Entry(mock_frame, width=25, font=("Segoe UI", 10))
        self.ent_mock_pattern.insert(0, "US,GS, {weight_str:>9}kg\\r\\n")
        self.ent_mock_pattern.grid(row=1, column=1, sticky="w", padx=10, pady=5)
        
        ttk.Label(mock_frame, text="Decimals:").grid(row=2, column=0, sticky="w", pady=5)
        self.ent_mock_decimals = ttk.Spinbox(mock_frame, from_=0, to=5, width=10, font=("Segoe UI", 10))
        self.ent_mock_decimals.set("2")
        self.ent_mock_decimals.grid(row=2, column=1, sticky="w", padx=10, pady=5)

        ttk.Label(mock_frame, text="1000s Sep:").grid(row=3, column=0, sticky="w", pady=5)
        self.cbo_thousands_sep = ttk.Combobox(mock_frame, values=[",", ".", "Space", "None"], width=10, state="readonly")
        self.cbo_thousands_sep.set(",")
        self.cbo_thousands_sep.grid(row=3, column=1, sticky="w", padx=10, pady=5)

        ttk.Label(mock_frame, text="Decimal Sep:").grid(row=4, column=0, sticky="w", pady=5)
        self.cbo_decimal_sep = ttk.Combobox(mock_frame, values=[".", ","], width=10, state="readonly")
        self.cbo_decimal_sep.set(".")
        self.cbo_decimal_sep.grid(row=4, column=1, sticky="w", padx=10, pady=5)
        
        self.btn_mock = ttk.Button(mock_frame, text="▶ Start Mock Scale", style="Start.TButton", command=self.toggle_mock)
        self.btn_mock.grid(row=5, column=0, columnspan=2, pady=10, sticky="we")
        
        controls2 = ttk.Frame(tab_dashboard, padding="0 15 15 15")
        controls2.pack(fill=tk.X)
        
        listener_frame = ttk.LabelFrame(controls2, text=" 📡 Scale Data Listener ", padding="15")
        listener_frame.pack(fill=tk.BOTH, expand=True, padx=20)
        
        ttk.Label(listener_frame, text="Target IP:").grid(row=0, column=0, sticky="w", pady=5)
        self.ent_listener_ip = ttk.Entry(listener_frame, width=15, font=("Segoe UI", 10))
        self.ent_listener_ip.insert(0, "127.0.0.1")
        self.ent_listener_ip.grid(row=0, column=1, sticky="w", padx=10, pady=5)
        
        ttk.Label(listener_frame, text="Target Port:").grid(row=0, column=2, sticky="w", pady=5)
        self.ent_listener_port = ttk.Entry(listener_frame, width=10, font=("Segoe UI", 10))
        self.ent_listener_port.insert(0, "9101")
        self.ent_listener_port.grid(row=0, column=3, sticky="w", padx=10, pady=5)
        
        self.btn_listener = ttk.Button(listener_frame, text="▶ Start Listener", style="Start.TButton", command=self.toggle_listener)
        self.btn_listener.grid(row=0, column=4, padx=20, pady=5)
        
        # Log Area
        log_frame = ttk.Frame(tab_dashboard, padding="15 0 15 15")
        log_frame.pack(fill=tk.BOTH, expand=True)
        
        self.log_area = scrolledtext.ScrolledText(log_frame, state='disabled', bg="#1e293b", fg="#34d399", font=("Consolas", 11), borderwidth=0)
        self.log_area.pack(fill=tk.BOTH, expand=True)

        # Tab 2: User Guide
        tab_guide = ttk.Frame(notebook, padding="20")
        notebook.add(tab_guide, text=" 📖 User Guide ")
        
        guide_text = scrolledtext.ScrolledText(tab_guide, bg="#ffffff", fg="#334155", font=("Segoe UI", 11), borderwidth=0, wrap=tk.WORD)
        guide_text.pack(fill=tk.BOTH, expand=True)
        
        guide_content = """# Digital Scale Integration Tester - User Guide

Welcome to the Digital Scale Integration Tester! This tool acts as a swiss-army knife for developers working with digital scale hardware over TCP connections.

1. 🌐 Browser WebSocket Bridge
Most modern web browsers block direct TCP connections. If you have a web application that needs to read live weight data from a scale on the local network, you can use this bridge.
- What it does: It runs a local WebSocket server. When your web app connects to it, the bridge opens a raw TCP connection to the scale and forwards all incoming data seamlessly.
- How to use: Set the desired WebSocket Port (default 8181) and click 'Start Bridge'. Then, in your web app, connect to ws://<YOUR_IP>:8181 and send a JSON payload {"action": "connect", "ip": "<SCALE_IP>", "port": <SCALE_PORT>}.

2. ⚖️ Mock Scale Simulator
If you don't have a physical scale hardware available, you can simulate one.
- What it does: Runs a fake TCP scale server on your computer that generates random, fluctuating weight values exactly like a live scale.
- Data Pattern: You can customize the exact string format sent by the simulator. Use {weight_str} to inject the formatted weight (e.g., US,GS, {weight_str:>9}kg\\r\\n).
- How to use: Choose a TCP port and click 'Start Mock Scale'. Any application can now connect to <YOUR_IP>:<PORT> via TCP to receive live scale data.

3. 📡 Scale Data Listener
Use this tool to connect to a real, physical scale (or the Mock Simulator) to monitor its data stream.
- What it does: Connects to any IP and Port via TCP and streams all incoming data directly into the application log.
- How to use: Enter the IP address and Port of the target scale and click 'Start Listener'. If the scale is sending continuous data, you will see it immediately in the log area.
"""
        guide_text.insert(tk.END, guide_content.strip())
        guide_text.config(state='disabled')
        
    def toggle_bridge(self):
        if not self.bridge_running:
            self.bridge_port = int(self.ent_bridge_port.get())
            self.bridge_running = True
            self.btn_bridge.config(text="⏹ Stop Bridge", style="Stop.TButton")
            self.ent_bridge_port.config(state="disabled")
            
            self.loop = asyncio.new_event_loop()
            self.bridge_thread = threading.Thread(target=start_asyncio_server, args=(self.loop, self.log, self))
            self.bridge_thread.daemon = True
            self.bridge_thread.start()
        else:
            self.bridge_running = False
            self.btn_bridge.config(text="▶ Start Bridge", style="Start.TButton")
            self.ent_bridge_port.config(state="normal")
            if self.loop:
                self.loop.call_soon_threadsafe(self.loop.stop)
                self.log("[Bridge] Stopped.")

    def toggle_mock(self):
        if not self.mock_running:
            self.mock_port = int(self.ent_mock_port.get())
            self.mock_pattern = self.ent_mock_pattern.get()
            
            try:
                self.mock_decimals = int(self.ent_mock_decimals.get())
            except ValueError:
                self.mock_decimals = 2
            self.mock_thousands_sep = self.cbo_thousands_sep.get()
            self.mock_decimal_sep = self.cbo_decimal_sep.get()
            
            self.mock_running = True
            self.btn_mock.config(text="⏹ Stop Mock Scale", style="Stop.TButton")
            self.ent_mock_port.config(state="disabled")
            self.ent_mock_pattern.config(state="disabled")
            self.ent_mock_decimals.config(state="disabled")
            self.cbo_thousands_sep.config(state="disabled")
            self.cbo_decimal_sep.config(state="disabled")
            
            self.mock_thread = threading.Thread(target=run_mock_scale, args=(self.log, self))
            self.mock_thread.daemon = True
            self.mock_thread.start()
        else:
            self.mock_running = False
            self.btn_mock.config(text="▶ Start Mock Scale", style="Start.TButton")
            self.ent_mock_port.config(state="normal")
            self.ent_mock_pattern.config(state="normal")
            self.ent_mock_decimals.config(state="normal")
            self.cbo_thousands_sep.config(state="readonly")
            self.cbo_decimal_sep.config(state="readonly")
            self.log("[Mock Scale] Stopped.")

    def toggle_listener(self):
        if not self.listener_running:
            self.listener_running = True
            ip = self.ent_listener_ip.get()
            port = int(self.ent_listener_port.get())
            self.btn_listener.config(text="⏹ Stop Listener", style="Stop.TButton")
            self.ent_listener_ip.config(state="disabled")
            self.ent_listener_port.config(state="disabled")
            
            self.listener_thread = threading.Thread(target=run_listener, args=(ip, port, self.log, self))
            self.listener_thread.daemon = True
            self.listener_thread.start()
        else:
            self.listener_running = False
            self.log("[Listener] Stopping...")

    def log(self, message):
        def append():
            self.log_area.configure(state='normal')
            self.log_area.insert(tk.END, message + "\n")
            self.log_area.see(tk.END)
            self.log_area.configure(state='disabled')
        self.root.after(0, append)
        
    def on_closing(self):
        if self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(self.loop.stop)
        self.mock_running = False
        self.listener_running = False
        self.root.destroy()
        sys.exit(0)

if __name__ == "__main__":
    try:
        import ctypes
        myappid = 'nipun.scale_desktop_tool.1.0'
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
    except Exception:
        pass

    root = tk.Tk()
    app = ScaleDesktopApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()
