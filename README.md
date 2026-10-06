# Digital Scale Integration Tester

Developed by Nipuna Rangika

A desktop utility designed to help develop, test, and integrate digital scales with web applications.

## Features

This tool provides three main services in a modern desktop UI:

1. **🌐 Browser WebSocket Bridge**: A bridge that allows browser-based web applications to connect to TCP digital scales. It creates a local WebSocket server that forwards all traffic to the scale's raw TCP port.
2. **⚖️ Mock Scale Simulator**: Acts as a fake digital scale running locally on your computer. You can configure a custom **Data Pattern** (e.g., `US,GS, {weight_str:>9}kg\r\n`) and it will generate fluctuating weights, behaving exactly like real digital scale hardware over TCP.
3. **📡 Scale Data Listener**: A diagnostic tool that connects to any real scale's IP and Port, streaming and logging its raw data directly into the UI for easy hardware debugging.

## Getting Started

You can download the pre-compiled `scale_desktop_tool.exe` from the `dist/` directory (if built) to run the tool without installing Python.

## Running from Source

If you want to run or modify the Python script directly:

1. Make sure you have Python 3 installed.
2. Install the required dependencies:
   ```bash
   pip install websockets
   ```
3. Run the application:
   ```bash
   python scale_desktop_tool.py
   ```

## Building the Executable

To build the standalone `.exe` yourself, use PyInstaller:

```bash
pip install pyinstaller
pyinstaller --onefile --noconsole --icon=scale.ico --add-data "scale.ico;." scale_desktop_tool.py
```
The output executable will be placed in the `dist/` folder.
