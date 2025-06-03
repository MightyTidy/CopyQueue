import logging
import threading
import time
import tkinter as tk
from queue import Queue as ThreadQueue
from tkinter import Listbox, Menu, messagebox
from typing import Any, Callable, Dict, List, Optional, TypedDict

# Third-party imports
import keyboard
import pystray
import pyperclip
from PIL import Image, ImageDraw
from plyer import notification

# Configure basic logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)

# Constants
DEFAULT_MAX_QUEUE_SIZE: int = 25
STATUS_UPDATE_TIMEOUT_SHORT: int = 2  # seconds for notifications
STATUS_UPDATE_TIMEOUT_MEDIUM: int = 3 # seconds for notifications
CLIPBOARD_POLLING_INTERVAL_SECONDS: float = 0.5 # Interval for checking clipboard changes


# Type definition for messages passed to the GUI queue
class GuiCommand(TypedDict):
    command: str
    data: Optional[Any]


class ClipboardManager:
    """
    Manages a queue of copied clipboard items and interacts with the system clipboard.
    """

    def __init__(self, max_queue_size: int = DEFAULT_MAX_QUEUE_SIZE) -> None:
        """
        Initializes the ClipboardManager.

        Args:
            max_queue_size: The maximum number of items to store in the queue.
        """
        self.clipboard_queue: List[str] = []
        self.current_view_index: int = -1  # -1 for no selection
        self.queue_mode_active: bool = True
        self.max_queue_size: int = max_queue_size
        self._stop_event: threading.Event = threading.Event()
        self.gui_queue: ThreadQueue[GuiCommand] = ThreadQueue()

        self.monitor_thread: Optional[threading.Thread] = None
        self.hotkey_listener_thread: Optional[threading.Thread] = None


        logging.info(
            "ClipboardManager initialized. Max queue size: %s", self.max_queue_size
        )

    def _send_to_gui_thread(self, command: str, data: Optional[Any] = None) -> None:
        """Helper to send commands/data to the GUI thread."""
        try:
            gui_command: GuiCommand = {'command': command, 'data': data}
            self.gui_queue.put_nowait(gui_command)
        except Exception as e:
            logging.error("Error sending to GUI queue: %s", e)

    def toggle_queue_mode(self) -> None:
        """Toggles the clipboard queueing functionality on or off."""
        self.queue_mode_active = not self.queue_mode_active
        status: str = "ACTIVE" if self.queue_mode_active else "INACTIVE"
        logging.info("Queue mode is now %s.", status)
        self._send_to_gui_thread('status_update', f"Queue mode: {status}")
        self._send_to_gui_thread('toggle_queue_mode_update', self.queue_mode_active)
        try:
            notification.notify(
                title='Clipboard Manager',
                message=f'Queue mode is now {status}.',
                app_name='Clipboard Manager',
                timeout=STATUS_UPDATE_TIMEOUT_MEDIUM,
            )
        except Exception as e:
            logging.warning("Failed to send notification: %s", e)

    def _get_clipboard_content(self) -> Optional[str]:
        """Safely retrieves text data from the clipboard using pyperclip."""
        try:
            return pyperclip.paste()
        except pyperclip.PyperclipException as e:
            # This can happen if the clipboard is empty or contains non-string data
            # or if another application is holding the clipboard.
            logging.debug("Error getting clipboard data with pyperclip: %s", e)
            # Optionally, notify GUI only on persistent or more severe errors.
            # self._send_to_gui_thread('status_update', "Notice: Clipboard inaccessible or empty.")
            return None
        except Exception as e_general: # Catch other potential errors like from OS directly
            logging.error("Unexpected error getting clipboard content: %s", e_general)
            return None


    def _set_clipboard_content(self, data: str) -> None:
        """Safely sets text data to the clipboard using pyperclip."""
        if not isinstance(data, str):
            logging.warning(
                "Attempted to set non-string data (type: %s) to clipboard. Converting.",
                type(data).__name__,
            )
            data = str(data)
        try:
            pyperclip.copy(data)
            logging.info("Clipboard updated with new item.")
        except pyperclip.PyperclipException as e:
            logging.error("Error setting clipboard data with pyperclip: %s", e)
            self._send_to_gui_thread('status_update', "Error: Could not set clipboard.")
        except Exception as e_general:
            logging.error("Unexpected error setting clipboard content: %s", e_general)
            self._send_to_gui_thread('status_update', "Error: Could not set clipboard.")

    def enqueue_item(self, item_data: str) -> None:
        """Adds an item to the clipboard queue if queue mode is active."""
        if not self.queue_mode_active:
            logging.debug("Queue mode is inactive. Item not added.")
            return

        if not item_data or not item_data.strip():
            logging.warning("No valid text data found to enqueue.")
            return

        if self.clipboard_queue and self.clipboard_queue[-1] == item_data:
            logging.info("Item is the same as the last one in queue. Not adding.")
            return

        self.clipboard_queue.append(item_data)
        log_msg: str = f"Item added to queue: '{item_data[:50]}...'"
        logging.info(log_msg)
        self._send_to_gui_thread('status_update', f"Item added: {item_data[:30]}...")

        if len(self.clipboard_queue) > self.max_queue_size:
            removed_item: str = self.clipboard_queue.pop(0)
            logging.info(
                "Queue reached max size. Removed oldest: '%s...'", removed_item[:50]
            )
            self._send_to_gui_thread(
                'status_update', f"Queue full. Oldest removed: {removed_item[:30]}..."
            )

        self.current_view_index = len(self.clipboard_queue) - 1
        self._send_to_gui_thread('update_list', list(self.clipboard_queue))
        self._send_to_gui_thread('select_item_in_list', self.current_view_index)

        try:
            notification.notify(
                title='Clipboard Manager',
                message=f'Item added: {item_data[:30]}...',
                app_name='Clipboard Manager',
                timeout=STATUS_UPDATE_TIMEOUT_SHORT,
            )
        except Exception as e:
            logging.warning("Failed to send 'item added' notification: %s", e)

    def dequeue_to_clipboard_and_paste(self) -> None:
        """
        Places the oldest item from the queue onto the clipboard, removes it,
        and attempts to simulate a paste action.
        """
        if not self.queue_mode_active:
            msg = "Queue mode inactive. Cannot dequeue."
            logging.debug(msg)
            self._send_to_gui_thread('status_update', msg)
            return

        if not self.clipboard_queue:
            msg = "Queue empty. Nothing to paste."
            logging.info(msg)
            self._send_to_gui_thread('status_update', msg)
            return

        item_to_paste: str = self.clipboard_queue.pop(0)
        self._set_clipboard_content(item_to_paste)
        logging.info(
            "Dequeued to clipboard: '%s...'. Remaining: %s",
            item_to_paste[:50],
            len(self.clipboard_queue),
        )
        self._send_to_gui_thread('status_update', f"Pasted oldest: {item_to_paste[:30]}...")
        self._send_to_gui_thread('update_list', list(self.clipboard_queue))

        if not self.clipboard_queue:
            self.current_view_index = -1
        elif self.current_view_index != -1:
            self.current_view_index = max(-1, self.current_view_index - 1)

        self._send_to_gui_thread('select_item_in_list', self.current_view_index)

        try:
            time.sleep(0.1)  # Brief delay for clipboard to update
            keyboard.press_and_release('ctrl+v') # Or 'cmd+v' on macOS
            logging.info("Simulated Ctrl+V paste.")
        except Exception as e:
            logging.error("Could not simulate paste: %s. Item is on clipboard.", e)
            self._send_to_gui_thread(
                'status_update', "Oldest item on clipboard. Paste manually."
            )

    def navigate_queue_and_set_clipboard(self, direction: int) -> None:
        """
        Navigates the queue (next/previous) and sets the selected item to the clipboard.
        Args:
            direction: 1 for next, -1 for previous.
        """
        if not self.queue_mode_active or not self.clipboard_queue:
            status_msg: str = "Queue mode inactive." if not self.queue_mode_active \
                else "Queue is empty."
            logging.debug("%s Cannot navigate.", status_msg)
            self._send_to_gui_thread('status_update', f"{status_msg} No item to show.")
            return

        if self.current_view_index == -1:  # No current selection
            self.current_view_index = 0 if direction == 1 \
                else len(self.clipboard_queue) - 1
        else:
            self.current_view_index = (
                self.current_view_index + direction + len(self.clipboard_queue)
            ) % len(self.clipboard_queue)

        item_to_show: str = self.clipboard_queue[self.current_view_index]
        self._set_clipboard_content(item_to_show)
        logging.info(
            "Navigated: Index %s, Item: '%s...'",
            self.current_view_index,
            item_to_show[:50],
        )
        self._send_to_gui_thread('status_update', f"On clipboard: {item_to_show[:30]}...")
        self._send_to_gui_thread('select_item_in_list', self.current_view_index)

    def _clipboard_monitor_loop(self) -> None:
        """Monitors clipboard for new text content by polling."""
        logging.info(
            "Clipboard monitor thread started (polling every %s seconds).",
            CLIPBOARD_POLLING_INTERVAL_SECONDS
            )
        recent_data: Optional[str] = self._get_clipboard_content()

        while not self._stop_event.is_set():
            if self.queue_mode_active: # Only poll if queue mode is active
                try:
                    # It's important to handle exceptions from _get_clipboard_content()
                    # as some OSes might restrict access or clipboard might be in a weird state.
                    current_clipboard_data: Optional[str] = self._get_clipboard_content()

                    if current_clipboard_data is not None and \
                       current_clipboard_data != recent_data:
                        logging.debug(
                            "New clipboard content by polling: %s...", current_clipboard_data[:30]
                        )
                        # Ensure it's not an empty string if that's not desired
                        if current_clipboard_data.strip():
                            self.enqueue_item(current_clipboard_data)
                        recent_data = current_clipboard_data
                    # If current_clipboard_data is None, we might want to update recent_data
                    # to avoid re-triggering if it becomes None and then previous content again.
                    # Or, simply keep recent_data as the last known valid string.
                    # For now, only update recent_data if new valid data is found.
                    # If clipboard becomes empty (None), recent_data holds the last copied item.
                    # If user copies something new, it will be different from recent_data.
                    # If user copies the *same* thing again, it won't be re-added due to enqueue_item logic.

                except Exception as e:
                    # This catches unexpected errors during the poll, not from _get_clipboard_content
                    # as those are handled inside that method.
                    logging.error("Unexpected error in clipboard polling loop: %s", e)
                    # Avoid rapid error looping if something is seriously wrong
                    self._stop_event.wait(CLIPBOARD_POLLING_INTERVAL_SECONDS * 2) # Wait longer on error
                    continue

            # Wait for the defined interval or until the stop event is set.
            # The wait method returns True if the event was set, False on timeout.
            if self._stop_event.wait(CLIPBOARD_POLLING_INTERVAL_SECONDS):
                break # Stop event was set, exit loop

        logging.info("Clipboard monitor thread stopped.")


    def _setup_hotkeys_and_wait(self) -> None:
        """Sets up global hotkeys and waits for stop event."""
        try:
            keyboard.add_hotkey(
                "ctrl+alt+v", self.dequeue_to_clipboard_and_paste
            )
            keyboard.add_hotkey("ctrl+shift+p", self.toggle_queue_mode)
            keyboard.add_hotkey("ctrl+right", lambda: self.navigate_queue_and_set_clipboard(1))
            keyboard.add_hotkey("ctrl+left", lambda: self.navigate_queue_and_set_clipboard(-1))
            logging.info("Global hotkeys registered.")
            self._send_to_gui_thread('status_update', "Hotkeys active.")
        except Exception as e: # Catching generic Exception as keyboard can raise various things
            # Check if it's an ImportError (keyboard not installed, common on some systems)
            # or an OS-level issue (permissions, accessibility settings on macOS/Linux)
            if isinstance(e, ImportError):
                logging.error("Keyboard library not found or could not be loaded. Hotkeys disabled. %s", e)
                self._send_to_gui_thread('status_update', "Error: Keyboard library missing. Hotkeys off.")
            else:
                logging.error("Failed to register hotkeys: %s. Try running as admin or check OS permissions.", e)
                self._send_to_gui_thread(
                    'status_update', "Error: Hotkeys failed. Try admin/check OS permissions."
                )
        
        self._stop_event.wait() # Keep thread alive until stop_event is set
        logging.info("Hotkey listener thread stopping.")


    def start_monitoring(self) -> None:
        """Starts clipboard monitoring and hotkey listener threads."""
        self._stop_event.clear()
        self.monitor_thread = threading.Thread(
            target=self._clipboard_monitor_loop, daemon=True
        )
        self.monitor_thread.start()

        self.hotkey_listener_thread = threading.Thread(
            target=self._setup_hotkeys_and_wait, daemon=True
        )
        self.hotkey_listener_thread.start()


    def stop_monitoring(self) -> None:
        """Stops all background monitoring threads and unhooks hotkeys."""
        self._stop_event.set() # Signal threads to stop

        # Unhook hotkeys as soon as possible
        try:
            # This needs to be called from the main thread or a thread that
            # can interact with the keyboard library's event loop if it has one.
            # If called from a dying thread, it might not always work as expected.
            # However, keyboard docs suggest unhook_all() is global.
            keyboard.unhook_all()
            logging.info("All hotkeys unhooked.")
        except Exception as e: # Catching generic Exception
            logging.error("Error unhooking hotkeys: %s", e)


        if self.monitor_thread and self.monitor_thread.is_alive():
            self.monitor_thread.join(timeout=CLIPBOARD_POLLING_INTERVAL_SECONDS + 0.2)
            if self.monitor_thread.is_alive():
                logging.warning("Clipboard monitor thread did not stop in time.")
        
        if self.hotkey_listener_thread and self.hotkey_listener_thread.is_alive():
            # The _stop_event.set() should make the _setup_hotkeys_and_wait loop terminate.
            self.hotkey_listener_thread.join(timeout=1.0) # Give it a second to stop
            if self.hotkey_listener_thread.is_alive():
                logging.warning("Hotkey listener thread did not stop in time.")


        logging.info("Clipboard manager monitoring stopped.")

class ClipboardApp:
    """
    GUI for the Clipboard Manager application.
    """

    def __init__(self, root_tk: tk.Tk, manager: ClipboardManager) -> None:
        self.root: tk.Tk = root_tk
        self.manager: ClipboardManager = manager
        self.root.title("Clipboard History")
        self.root.geometry("400x500")
        self.root.withdraw()  # Start hidden
        self.root.protocol("WM_DELETE_WINDOW", self.hide_window)

        self._setup_ui()
        self.tray_icon: Optional[pystray.Icon] = None
        self._create_tray_icon_thread()

        self.root.after(100, self._process_gui_queue) # Start GUI queue poller

    def _setup_ui(self) -> None:
        """Configures the Tkinter UI elements."""
        # --- Menu Bar ---
        menubar = Menu(self.root)
        filemenu = Menu(menubar, tearoff=0)
        filemenu.add_command(label="Toggle Queueing", command=self.manager.toggle_queue_mode)
        filemenu.add_separator()
        filemenu.add_command(label="Hide Window", command=self.hide_window)
        filemenu.add_command(label="Exit", command=self.quit_application)
        menubar.add_cascade(label="File", menu=filemenu)
        self.root.config(menu=menubar)

        # --- Clipboard List ---
        self.listbox: Listbox = Listbox(self.root, height=20, exportselection=False)
        self.listbox.pack(pady=10, padx=10, fill=tk.BOTH, expand=True)
        self.listbox.bind("<<ListboxSelect>>", self._on_listbox_select)
        self.listbox.bind("<Double-1>", self._on_listbox_double_click)

        # --- Buttons ---
        button_frame = tk.Frame(self.root)
        button_frame.pack(pady=5)

        self.paste_oldest_button = tk.Button(
            button_frame,
            text="Paste Oldest & Remove",
            command=self.manager.dequeue_to_clipboard_and_paste,
        )
        self.paste_oldest_button.pack(side=tk.LEFT, padx=5)

        self.copy_selected_button = tk.Button(
            button_frame,
            text="Copy Selected to Clipboard",
            command=self._copy_selected_to_clipboard,
            state=tk.DISABLED,
        )
        self.copy_selected_button.pack(side=tk.LEFT, padx=5)

        # --- Status Bar ---
        self.status_var: tk.StringVar = tk.StringVar()
        status_bar_label = tk.Label(
            self.root, textvariable=self.status_var, bd=1, relief=tk.SUNKEN, anchor=tk.W
        )
        status_bar_label.pack(side=tk.BOTTOM, fill=tk.X)
        initial_status = "Ready. Queue mode: ACTIVE" if self.manager.queue_mode_active else "Ready. Queue mode: INACTIVE"
        self.status_var.set(initial_status)


    @staticmethod
    def _create_tray_icon_image(width: int, height: int, color1: str, color2: str) -> Image.Image:
        """Creates a simple PIL Image for the system tray icon."""
        image = Image.new("RGB", (width, height), color1)
        dc = ImageDraw.Draw(image)
        dc.rectangle((width // 2, 0, width, height // 2), fill=color2)
        dc.rectangle((0, height // 2, width // 2, height), fill=color2)
        return image

    def _get_tray_menu_items(self) -> pystray.Menu:
        """Defines the menu items for the system tray icon."""
        return pystray.Menu(
            pystray.MenuItem(
                'Show/Hide History', self.toggle_window_visibility, default=True
            ),
            pystray.MenuItem(
                'Queueing Active',
                self._toggle_queue_mode_from_tray,
                checked=lambda item: self.manager.queue_mode_active,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem('Quit', self.quit_application),
        )

    def _start_tray_icon_process(self) -> None:
        """Initializes and runs the system tray icon. Runs in a separate thread."""
        try:
            icon_image: Image.Image = self._create_tray_icon_image(64, 64, 'black', 'royalblue')
            self.tray_icon = pystray.Icon(
                "clipboard_manager",
                icon_image,
                "Clipboard Manager",
                menu=self._get_tray_menu_items(),
            )
            logging.info("Starting system tray icon.")
            self.tray_icon.run() # This is a blocking call
        except Exception as e:
            logging.error("Failed to start system tray icon: %s.", e)
            # Schedule a messagebox on the main Tkinter thread
            self.root.after(0, lambda: messagebox.showerror(
                "Tray Icon Error",
                f"Could not initialize system tray icon: {e}\n"
                "Application will run without it, limiting some functionality."
            ))


    def _create_tray_icon_thread(self) -> None:
        """Creates and starts the thread for the system tray icon."""
        tray_thread = threading.Thread(target=self._start_tray_icon_process, daemon=True)
        tray_thread.start()


    def _toggle_queue_mode_from_tray(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        """Callback for toggling queue mode from the tray menu."""
        self.manager.toggle_queue_mode()
        if self.tray_icon: # pystray updates checked state automatically based on lambda
            self.tray_icon.update_menu()


    def _update_listbox_display(self, items: List[str]) -> None:
        """Refreshes the listbox with current clipboard queue items."""
        self.listbox.delete(0, tk.END)
        for item in items:
            display_text = item[:100] + "..." if len(item) > 100 else item
            self.listbox.insert(tk.END, display_text)

    def _select_item_in_listbox(self, index: int) -> None:
        """Selects an item in the listbox by its index."""
        if 0 <= index < self.listbox.size():
            self.listbox.selection_clear(0, tk.END)
            self.listbox.selection_set(index)
            self.listbox.activate(index)
            self.listbox.see(index) # Ensure item is visible
            self.copy_selected_button.config(state=tk.NORMAL)
        elif index == -1:  # No selection
            self.listbox.selection_clear(0, tk.END)
            self.copy_selected_button.config(state=tk.DISABLED)

    def _on_listbox_select(self, event: tk.Event) -> None:
        """Handles item selection in the listbox."""
        selected_indices = self.listbox.curselection()
        if selected_indices:
            self.manager.current_view_index = selected_indices[0]
            self.copy_selected_button.config(state=tk.NORMAL)
        else:
            self.copy_selected_button.config(state=tk.DISABLED)

    def _on_listbox_double_click(self, event: tk.Event) -> None:
        """Handles double-click on a listbox item: copies and hides window."""
        self._copy_selected_to_clipboard_and_hide()

    def _copy_selected_to_clipboard(self) -> None:
        """Copies the currently selected listbox item to the system clipboard."""
        idx: int = self.manager.current_view_index
        if idx != -1 and 0 <= idx < len(self.manager.clipboard_queue):
            item_to_copy: str = self.manager.clipboard_queue[idx]
            self.manager._set_clipboard_content(item_to_copy)
            status_msg: str = f"Copied to clipboard: {item_to_copy[:50]}..."
            self.status_var.set(status_msg)
            try:
                notification.notify(
                    title='Clipboard Manager',
                    message=f'Copied: {item_to_copy[:30]}...',
                    app_name='Clipboard Manager',
                    timeout=STATUS_UPDATE_TIMEOUT_SHORT,
                )
            except Exception as e:
                logging.warning("Failed to send 'copied selected' notification: %s", e)

    def _copy_selected_to_clipboard_and_hide(self) -> None:
        """Copies selected item and then hides the main window."""
        self._copy_selected_to_clipboard()
        if self.manager.current_view_index != -1: # If something was actually selected
            self.hide_window()

    def _process_gui_queue(self) -> None:
        """Processes messages from the manager thread to update the GUI."""
        try:
            while not self.manager.gui_queue.empty():
                msg: GuiCommand = self.manager.gui_queue.get_nowait()
                command: str = msg['command']
                data: Optional[Any] = msg['data']

                if command == 'update_list' and isinstance(data, list):
                    self._update_listbox_display(data)
                elif command == 'select_item_in_list' and isinstance(data, int):
                    self._select_item_in_listbox(data)
                elif command == 'status_update' and isinstance(data, str):
                    self.status_var.set(data)
                elif command == 'toggle_queue_mode_update' and isinstance(data, bool):
                    current_status = "ACTIVE" if data else "INACTIVE"
                    self.status_var.set(f"Queue mode: {current_status}")
                    if self.tray_icon:
                        self.tray_icon.update_menu() # Ensure tray reflects change
                elif command == 'show_window':
                    self.show_window()
        except Exception as e:
            logging.error("Error processing GUI queue: %s", e)
        finally:
            self.root.after(100, self._process_gui_queue)  # Reschedule polling

    def show_window(self) -> None:
        """Makes the main application window visible and focused."""
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()
        # Refresh list when showing, in case it was modified while hidden
        self._update_listbox_display(list(self.manager.clipboard_queue))
        self._select_item_in_listbox(self.manager.current_view_index)

    def hide_window(self) -> None:
        """Hides the main application window."""
        self.root.withdraw()

    def toggle_window_visibility(self, icon: Optional[pystray.Icon] = None,
                                 item: Optional[pystray.MenuItem] = None) -> None:
        """Toggles visibility of the main window (for tray menu)."""
        if self.root.state() == 'withdrawn':
            self.show_window()
        else:
            self.hide_window()

    def quit_application(self, icon: Optional[pystray.Icon] = None,
                         item: Optional[pystray.MenuItem] = None) -> None:
        """Handles application shutdown procedure."""
        logging.info("Quit application requested.")
        if messagebox.askokcancel("Quit", "Do you want to quit Clipboard Manager?"):
            self.status_var.set("Exiting...")
            self.manager.stop_monitoring()

            if self.tray_icon:
                self.tray_icon.stop() # Stop pystray's loop

            self.root.quit()    # Quit Tkinter main loop
            self.root.destroy() # Ensure window is destroyed
            logging.info("Application exited.")



def main() -> None:
    """Main function to initialize and run the application."""
    root_tk = tk.Tk()
    root_tk.withdraw() # Start hidden, show via tray or other means

    clipboard_manager = ClipboardManager(max_queue_size=DEFAULT_MAX_QUEUE_SIZE)
    app = ClipboardApp(root_tk, clipboard_manager)

    clipboard_manager.start_monitoring()

    try:
        root_tk.mainloop()
    except KeyboardInterrupt:
        logging.info("KeyboardInterrupt received. Shutting down.")
    finally:
        logging.info("Main loop ended. Ensuring cleanup.")
        # Final cleanup if not handled by quit_application
        if clipboard_manager: # Check if manager was initialized
            clipboard_manager.stop_monitoring()
        if app and app.tray_icon and getattr(app.tray_icon, 'visible', False): # Check if tray_icon exists and might be running
             app.tray_icon.stop()


if __name__ == "__main__":
    main()