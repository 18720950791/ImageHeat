"""
Copyright © 2024-2026  Bartłomiej Duda
License: GPL-3.0 License
"""

import os
import platform
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText
from typing import List, Optional

import center_tk_window
from reversebox.common.logger import get_logger

from src.GUI.gui_params import GuiParams
from src.Image.batch_processor import BatchFileResult, BatchProcessor
from src.Image.constants import TranslationKeys

logger = get_logger(__name__)

BATCH_WINDOW_WIDTH = 550
BATCH_WINDOW_HEIGHT = 520


class BatchExportDialog:
    """
    Modal dialog for batch exporting multiple image files.
    Allows selecting input files, output format/directory/naming,
    then runs the batch in a background thread with progress and logging.
    """

    def __init__(self, gui_object, source_gui_params: GuiParams):
        self.gui = gui_object
        self.source_gui_params = source_gui_params
        self.file_paths: List[str] = []
        self.batch_processor: Optional[BatchProcessor] = None
        self.is_processing: bool = False

        # Create window
        self.window = tk.Toplevel(width=BATCH_WINDOW_WIDTH, height=BATCH_WINDOW_HEIGHT)
        self.window.wm_title(
            self.gui.get_translation_text(TranslationKeys.TRANSLATION_TEXT_BATCH_TITLE)
        )
        self.window.minsize(BATCH_WINDOW_WIDTH, BATCH_WINDOW_HEIGHT)
        self.window.resizable(False, False)

        if platform.uname().system != "Linux":
            self.window.wm_attributes("-toolwindow", "True")
        self.window.attributes("-topmost", "true")
        self.window.grab_set()  # modal

        # Copy icon from main window
        try:
            if platform.uname().system == "Linux":
                self.window.iconphoto(False, tk.PhotoImage(file=self.gui.icon_path))
            else:
                self.window.iconbitmap(self.gui.icon_path)
        except Exception:
            pass

        self.gui_font = ("Arial", 8)
        self._build_ui()

        self.window.lift()
        self.window.focus_force()
        center_tk_window.center_on_screen(self.window)

    def _tr(self, key) -> str:
        """Shortcut for translation lookup."""
        return self.gui.get_translation_text(key)

    def _build_ui(self):
        main_frame = tk.Frame(self.window, bg="#f0f0f0")
        main_frame.place(x=0, y=0, relwidth=1, relheight=1)

        y_pos = 5

        # ── Input Files ──────────────────────────────────────────────
        input_label_frame = tk.LabelFrame(
            main_frame,
            text=self._tr(TranslationKeys.TRANSLATION_TEXT_BATCH_INPUT_FILES),
            font=self.gui_font,
        )
        input_label_frame.place(x=5, y=y_pos, width=530, height=110)

        # Browse button + count label
        self.files_count_var = tk.StringVar(value=f"0 {self._tr(TranslationKeys.TRANSLATION_TEXT_BATCH_FILES_SELECTED)}")
        self.files_count_label = tk.Label(
            input_label_frame, textvariable=self.files_count_var, font=self.gui_font, anchor="w"
        )
        self.files_count_label.place(x=5, y=2, width=350, height=18)

        self.browse_files_btn = tk.Button(
            input_label_frame,
            text=self._tr(TranslationKeys.TRANSLATION_TEXT_BATCH_BROWSE_FILES),
            command=self._browse_files,
            font=self.gui_font,
        )
        self.browse_files_btn.place(x=420, y=0, width=100, height=20)

        # File list
        self.file_listbox = tk.Listbox(input_label_frame, font=self.gui_font, selectmode=tk.EXTENDED)
        self.file_listbox.place(x=5, y=22, width=515, height=78)

        y_pos += 115

        # ── Output Options ───────────────────────────────────────────
        options_label_frame = tk.LabelFrame(
            main_frame,
            text=self._tr(TranslationKeys.TRANSLATION_TEXT_BATCH_OUTPUT_FORMAT),
            font=self.gui_font,
        )
        options_label_frame.place(x=5, y=y_pos, width=530, height=100)

        # Output format
        tk.Label(
            options_label_frame,
            text=self._tr(TranslationKeys.TRANSLATION_TEXT_BATCH_OUTPUT_FORMAT) + ":",
            font=self.gui_font,
            anchor="w",
        ).place(x=5, y=5, width=90, height=20)

        self.output_format_var = tk.StringVar(value="DDS")
        self.output_format_combo = ttk.Combobox(
            options_label_frame,
            values=["DDS", "PNG", "BMP"],
            textvariable=self.output_format_var,
            font=self.gui_font,
            state="readonly",
            width=10,
        )
        self.output_format_combo.place(x=100, y=5, width=80, height=20)

        # Output directory
        tk.Label(
            options_label_frame,
            text=self._tr(TranslationKeys.TRANSLATION_TEXT_BATCH_OUTPUT_DIR) + ":",
            font=self.gui_font,
            anchor="w",
        ).place(x=5, y=30, width=90, height=20)

        self.output_dir_var = tk.StringVar(value="")
        self.output_dir_entry = tk.Entry(
            options_label_frame, textvariable=self.output_dir_var, font=self.gui_font, state="readonly"
        )
        self.output_dir_entry.place(x=100, y=30, width=310, height=20)

        self.browse_dir_btn = tk.Button(
            options_label_frame,
            text=self._tr(TranslationKeys.TRANSLATION_TEXT_BATCH_BROWSE_DIR),
            command=self._browse_output_dir,
            font=self.gui_font,
        )
        self.browse_dir_btn.place(x=420, y=28, width=100, height=22)

        # File naming
        tk.Label(
            options_label_frame,
            text=self._tr(TranslationKeys.TRANSLATION_TEXT_BATCH_NAMING) + ":",
            font=self.gui_font,
            anchor="w",
        ).place(x=5, y=55, width=90, height=20)

        self.naming_var = tk.StringVar(value="original")
        self.naming_combo = ttk.Combobox(
            options_label_frame,
            values=[
                self._tr(TranslationKeys.TRANSLATION_TEXT_BATCH_NAMING_ORIGINAL),
                self._tr(TranslationKeys.TRANSLATION_TEXT_BATCH_NAMING_NUMBERED),
                self._tr(TranslationKeys.TRANSLATION_TEXT_BATCH_NAMING_PREFIX),
            ],
            textvariable=tk.StringVar(
                value=self._tr(TranslationKeys.TRANSLATION_TEXT_BATCH_NAMING_ORIGINAL)
            ),
            font=self.gui_font,
            state="readonly",
            width=18,
        )
        self.naming_combo.place(x=100, y=55, width=140, height=20)
        self.naming_combo.bind("<<ComboboxSelected>>", self._on_naming_changed)

        # Prefix entry (initially hidden)
        self.prefix_label = tk.Label(
            options_label_frame,
            text=self._tr(TranslationKeys.TRANSLATION_TEXT_BATCH_PREFIX) + ":",
            font=self.gui_font,
            anchor="w",
        )
        self.prefix_label.place(x=250, y=55, width=50, height=20)
        self.prefix_label.place_forget()

        self.prefix_var = tk.StringVar(value="export")
        self.prefix_entry = tk.Entry(
            options_label_frame, textvariable=self.prefix_var, font=self.gui_font
        )
        self.prefix_entry.place(x=305, y=55, width=120, height=20)
        self.prefix_entry.place_forget()

        y_pos += 105

        # ── Progress ─────────────────────────────────────────────────
        progress_label_frame = tk.LabelFrame(
            main_frame,
            text=self._tr(TranslationKeys.TRANSLATION_TEXT_BATCH_PROGRESS),
            font=self.gui_font,
        )
        progress_label_frame.place(x=5, y=y_pos, width=530, height=40)

        self.progress_var = tk.DoubleVar(value=0.0)
        self.progress_bar = ttk.Progressbar(
            progress_label_frame, variable=self.progress_var, maximum=100.0, length=400
        )
        self.progress_bar.place(x=5, y=10, width=420, height=20)

        self.progress_text_var = tk.StringVar(value="0%")
        self.progress_text_label = tk.Label(
            progress_label_frame, textvariable=self.progress_text_var, font=self.gui_font, anchor="w"
        )
        self.progress_text_label.place(x=435, y=10, width=85, height=20)

        y_pos += 45

        # ── Log ──────────────────────────────────────────────────────
        log_label_frame = tk.LabelFrame(
            main_frame,
            text=self._tr(TranslationKeys.TRANSLATION_TEXT_BATCH_LOG),
            font=self.gui_font,
        )
        log_label_frame.place(x=5, y=y_pos, width=530, height=170)

        self.log_text = ScrolledText(
            log_label_frame, font=("Consolas", 8), state="disabled", wrap=tk.WORD
        )
        self.log_text.place(x=5, y=5, width=515, height=155)

        y_pos += 175

        # ── Buttons ──────────────────────────────────────────────────
        self.start_btn = tk.Button(
            main_frame,
            text=self._tr(TranslationKeys.TRANSLATION_TEXT_BATCH_START),
            command=self._start_batch,
            font=("Arial", 9, "bold"),
            width=12,
        )
        self.start_btn.place(x=340, y=y_pos, width=100, height=28)

        self.cancel_btn = tk.Button(
            main_frame,
            text=self._tr(TranslationKeys.TRANSLATION_TEXT_BATCH_CANCEL),
            command=self._cancel_or_close,
            font=("Arial", 9),
            width=12,
        )
        self.cancel_btn.place(x=445, y=y_pos, width=100, height=28)

    # ── Callbacks ────────────────────────────────────────────────────

    def _browse_files(self):
        paths = filedialog.askopenfilenames(
            title=self._tr(TranslationKeys.TRANSLATION_TEXT_BATCH_BROWSE_FILES),
            initialdir=self.gui.current_open_file_directory_path or "",
        )
        if paths:
            self.file_paths = list(paths)
            self.file_listbox.delete(0, tk.END)
            for p in self.file_paths:
                self.file_listbox.insert(tk.END, os.path.basename(p))
            self.files_count_var.set(
                f"{len(self.file_paths)} {self._tr(TranslationKeys.TRANSLATION_TEXT_BATCH_FILES_SELECTED)}"
            )
            # Remember directory
            try:
                self.gui.current_open_file_directory_path = os.path.dirname(self.file_paths[0])
            except Exception:
                pass

    def _browse_output_dir(self):
        dir_path = filedialog.askdirectory(
            title=self._tr(TranslationKeys.TRANSLATION_TEXT_BATCH_OUTPUT_DIR),
            initialdir=self.gui.current_save_as_directory_path or "",
        )
        if dir_path:
            self.output_dir_var.set(dir_path)

    def _on_naming_changed(self, event=None):
        selected = self.naming_combo.get()
        prefix_text = self._tr(TranslationKeys.TRANSLATION_TEXT_BATCH_NAMING_PREFIX)
        if selected == prefix_text:
            self.prefix_label.place(x=250, y=55, width=50, height=20)
            self.prefix_entry.place(x=305, y=55, width=120, height=20)
        else:
            self.prefix_label.place_forget()
            self.prefix_entry.place_forget()

    def _get_naming_pattern(self) -> str:
        """Map the combobox display text back to an internal naming key."""
        selected = self.naming_combo.get()
        if selected == self._tr(TranslationKeys.TRANSLATION_TEXT_BATCH_NAMING_NUMBERED):
            return "numbered"
        elif selected == self._tr(TranslationKeys.TRANSLATION_TEXT_BATCH_NAMING_PREFIX):
            return "prefix"
        return "original"

    def _log(self, text: str):
        """Append a line to the log text widget (must be called on main thread)."""
        self.log_text.config(state="normal")
        self.log_text.insert(tk.END, text + "\n")
        self.log_text.see(tk.END)
        self.log_text.config(state="disabled")

    def _start_batch(self):
        # Validation
        if not self.file_paths:
            messagebox.showwarning(
                "Warning", self._tr(TranslationKeys.TRANSLATION_TEXT_BATCH_NO_FILES)
            )
            return
        if not self.output_dir_var.get():
            messagebox.showwarning(
                "Warning", self._tr(TranslationKeys.TRANSLATION_TEXT_BATCH_NO_OUTPUT_DIR)
            )
            return

        # Lock UI
        self.is_processing = True
        self.start_btn.config(state="disabled")
        self.browse_files_btn.config(state="disabled")
        self.browse_dir_btn.config(state="disabled")
        self.output_format_combo.config(state="disabled")
        self.naming_combo.config(state="disabled")
        self.prefix_entry.config(state="disabled")
        self.cancel_btn.config(
            text=self._tr(TranslationKeys.TRANSLATION_TEXT_BATCH_CANCEL)
        )

        # Clear log and progress
        self.log_text.config(state="normal")
        self.log_text.delete("1.0", tk.END)
        self.log_text.config(state="disabled")
        self.progress_var.set(0.0)
        self.progress_text_var.set("0%")

        # Snapshot current GUI params
        self.gui.get_gui_params_from_gui_elements()
        params_snapshot = self.gui.gui_params

        self.batch_processor = BatchProcessor(
            source_gui_params=params_snapshot,
            file_paths=self.file_paths,
            output_dir=self.output_dir_var.get(),
            output_format=self.output_format_var.get().lower(),
            naming_pattern=self._get_naming_pattern(),
            custom_prefix=self.prefix_var.get(),
            progress_callback=self._on_progress,
            completion_callback=self._on_completion,
        )
        self.batch_processor.start()

    def _cancel_or_close(self):
        if self.is_processing:
            if self.batch_processor:
                self.batch_processor.cancel()
        else:
            self.window.destroy()

    # ── Thread-safe callbacks (called from background thread) ────────

    def _on_progress(self, current: int, total: int, result: BatchFileResult):
        """Called from background thread; marshal to main thread."""
        self.window.after(0, self._update_progress_ui, current, total, result)

    def _on_completion(self, results: List[BatchFileResult]):
        """Called from background thread; marshal to main thread."""
        self.window.after(0, self._on_completion_ui, results)

    # ── UI update methods (run on main thread) ───────────────────────

    def _update_progress_ui(self, current: int, total: int, result: BatchFileResult):
        pct = (current / total) * 100.0 if total > 0 else 0.0
        self.progress_var.set(pct)
        self.progress_text_var.set(f"{current}/{total} ({pct:.0f}%)")

        file_name = os.path.basename(result.file_path)
        if result.status == "success":
            status_tag = self._tr(TranslationKeys.TRANSLATION_TEXT_BATCH_STATUS_OK)
            self._log(f"[{status_tag}] {file_name} -> {result.message}")
        elif result.status == "failed":
            status_tag = self._tr(TranslationKeys.TRANSLATION_TEXT_BATCH_STATUS_FAIL)
            self._log(f"[{status_tag}] {file_name}: {result.message}")
        elif result.status == "cancelled":
            status_tag = self._tr(TranslationKeys.TRANSLATION_TEXT_BATCH_STATUS_CANCELLED)
            self._log(f"[{status_tag}] {file_name}")

    def _on_completion_ui(self, results: List[BatchFileResult]):
        self.is_processing = False
        self.start_btn.config(state="normal")
        self.browse_files_btn.config(state="normal")
        self.browse_dir_btn.config(state="normal")
        self.output_format_combo.config(state="readonly")
        self.naming_combo.config(state="readonly")
        self.prefix_entry.config(state="normal")

        self.cancel_btn.config(
            text=self._tr(TranslationKeys.TRANSLATION_TEXT_BATCH_CLOSE)
        )

        success_count = sum(1 for r in results if r.status == "success")
        fail_count = sum(1 for r in results if r.status == "failed")
        cancel_count = sum(1 for r in results if r.status == "cancelled")

        summary = (
            f"{self._tr(TranslationKeys.TRANSLATION_TEXT_BATCH_COMPLETE)}: "
            f"{success_count} {self._tr(TranslationKeys.TRANSLATION_TEXT_BATCH_STATUS_OK)}, "
            f"{fail_count} {self._tr(TranslationKeys.TRANSLATION_TEXT_BATCH_STATUS_FAIL)}, "
            f"{cancel_count} {self._tr(TranslationKeys.TRANSLATION_TEXT_BATCH_STATUS_CANCELLED)}"
        )
        self._log("")
        self._log(summary)

        messagebox.showinfo("Info", summary)
