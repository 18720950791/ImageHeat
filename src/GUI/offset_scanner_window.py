"""
Copyright © 2024-2025  Bartłomiej Duda
License: GPL-3.0 License

Offset scanner dialog window for ImageHeat.
Provides a Toplevel dialog where users can configure and run offset scans,
view thumbnail results in a scrollable grid, and click to apply an offset.
"""

import sys
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable, List, Optional

from PIL import ImageTk
from reversebox.common.logger import get_logger

from src.GUI.gui_params import GuiParams
from src.GUI.offset_scanner import (
    OffsetScanner,
    ScanCandidate,
    ScanConfig,
    THUMBNAIL_SIZE,
)
from src.Image.constants import TranslationKeys

logger = get_logger(__name__)

# layout constants
GRID_COLUMNS = 6
CELL_WIDTH = THUMBNAIL_SIZE + 16
CELL_HEIGHT = THUMBNAIL_SIZE + 30
WINDOW_MIN_WIDTH = 700
WINDOW_MIN_HEIGHT = 550


class OffsetScannerWindow(tk.Toplevel):
    """
    A Toplevel dialog window for scanning candidate image offsets
    and displaying results as a clickable thumbnail grid.
    """

    def __init__(
        self,
        master: tk.Tk,
        loaded_image_data: bytes,
        gui_params: GuiParams,
        total_file_size: int,
        apply_callback: Callable[[int], None],
        get_translation_text: Callable[[str], str],
    ):
        super().__init__(master)
        self.master_ref = master
        self.loaded_image_data = loaded_image_data
        self.gui_params = gui_params
        self.total_file_size = total_file_size
        self.apply_callback = apply_callback
        self.get_translation_text = get_translation_text

        # state
        self._cancel_event = threading.Event()
        self._scan_thread: Optional[threading.Thread] = None
        self._is_scanning = False
        self._thumbnail_refs: List[ImageTk.PhotoImage] = []  # prevent GC
        self._results: List[ScanCandidate] = []

        # window setup
        self.title(self.get_translation_text(TranslationKeys.TRANSLATION_TEXT_SCANNER_TITLE))
        self.minsize(WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT)
        self.geometry(f"{WINDOW_MIN_WIDTH}x{WINDOW_MIN_HEIGHT}")
        self.transient(master)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self._build_ui()
        self._center_on_parent()

    def _center_on_parent(self):
        """Center this window on the parent."""
        self.update_idletasks()
        pw = self.master_ref.winfo_width()
        ph = self.master_ref.winfo_height()
        px = self.master_ref.winfo_x()
        py = self.master_ref.winfo_y()
        w = self.winfo_width()
        h = self.winfo_height()
        x = px + (pw - w) // 2
        y = py + (ph - h) // 2
        self.geometry(f"+{x}+{y}")

    def _build_ui(self):
        """Build the complete dialog UI."""
        tr = self.get_translation_text

        # ── input frame ──
        input_frame = tk.LabelFrame(
            self, text="Scan Parameters", font=("Arial", 9)
        )
        input_frame.pack(fill="x", padx=8, pady=(8, 4))

        # row 1: start, end, step
        row1 = tk.Frame(input_frame)
        row1.pack(fill="x", padx=4, pady=2)

        tk.Label(row1, text=tr(TranslationKeys.TRANSLATION_TEXT_SCANNER_START_OFFSET),
                 font=("Arial", 8)).pack(side="left", padx=(0, 2))
        self.start_offset_var = tk.StringVar(value="0")
        self.start_offset_spin = tk.Spinbox(
            row1, textvariable=self.start_offset_var, from_=0, to=sys.maxsize,
            width=14, font=("Arial", 8),
        )
        self.start_offset_spin.pack(side="left", padx=(0, 8))

        tk.Label(row1, text=tr(TranslationKeys.TRANSLATION_TEXT_SCANNER_END_OFFSET),
                 font=("Arial", 8)).pack(side="left", padx=(0, 2))
        self.end_offset_var = tk.StringVar(value=str(min(self.total_file_size, 100000)))
        self.end_offset_spin = tk.Spinbox(
            row1, textvariable=self.end_offset_var, from_=0, to=sys.maxsize,
            width=14, font=("Arial", 8),
        )
        self.end_offset_spin.pack(side="left", padx=(0, 8))

        tk.Label(row1, text=tr(TranslationKeys.TRANSLATION_TEXT_SCANNER_STEP),
                 font=("Arial", 8)).pack(side="left", padx=(0, 2))
        self.step_var = tk.StringVar(value="256")
        self.step_spin = tk.Spinbox(
            row1, textvariable=self.step_var, from_=1, to=sys.maxsize,
            width=10, font=("Arial", 8),
        )
        self.step_spin.pack(side="left", padx=(0, 8))

        # row 2: alignment, max results
        row2 = tk.Frame(input_frame)
        row2.pack(fill="x", padx=4, pady=2)

        tk.Label(row2, text=tr(TranslationKeys.TRANSLATION_TEXT_SCANNER_ALIGNMENT),
                 font=("Arial", 8)).pack(side="left", padx=(0, 2))
        self.alignment_var = tk.StringVar(value="None")
        self.alignment_combo = ttk.Combobox(
            row2, textvariable=self.alignment_var, state="readonly",
            values=["None", "4", "8", "16", "32", "64", "128", "256", "512", "1024", "4096"],
            width=8, font=("Arial", 8),
        )
        self.alignment_combo.pack(side="left", padx=(0, 8))

        tk.Label(row2, text=tr(TranslationKeys.TRANSLATION_TEXT_SCANNER_MAX_RESULTS),
                 font=("Arial", 8)).pack(side="left", padx=(0, 2))
        self.max_results_var = tk.StringVar(value="50")
        self.max_results_spin = tk.Spinbox(
            row2, textvariable=self.max_results_var, from_=1, to=1000,
            width=6, font=("Arial", 8),
        )
        self.max_results_spin.pack(side="left")

        # ── control frame ──
        ctrl_frame = tk.Frame(self)
        ctrl_frame.pack(fill="x", padx=8, pady=4)

        self.start_btn = tk.Button(
            ctrl_frame, text=tr(TranslationKeys.TRANSLATION_TEXT_SCANNER_START_BTN),
            command=self._on_start_click, font=("Arial", 9), width=14,
        )
        self.start_btn.pack(side="left", padx=(0, 4))

        self.cancel_btn = tk.Button(
            ctrl_frame, text=tr(TranslationKeys.TRANSLATION_TEXT_SCANNER_CANCEL_BTN),
            command=self._on_cancel_click, font=("Arial", 9), width=10,
            state="disabled",
        )
        self.cancel_btn.pack(side="left", padx=(0, 8))

        self.progress_var = tk.DoubleVar(value=0)
        self.progress_bar = ttk.Progressbar(
            ctrl_frame, variable=self.progress_var, maximum=100, length=200,
        )
        self.progress_bar.pack(side="left", padx=(0, 8), fill="x", expand=True)

        self.status_label = tk.Label(
            ctrl_frame, text="", font=("Arial", 8), anchor="w",
        )
        self.status_label.pack(side="left", fill="x", expand=True)

        # ── summary frame ──
        self.summary_frame = tk.Frame(self)
        self.summary_frame.pack(fill="x", padx=8, pady=(0, 2))
        self.summary_label = tk.Label(
            self.summary_frame, text="", font=("Arial", 8), anchor="w", fg="#333333",
        )
        self.summary_label.pack(side="left")

        # ── results frame (scrollable thumbnail grid) ──
        results_labelframe = tk.LabelFrame(
            self, text=tr(TranslationKeys.TRANSLATION_TEXT_SCANNER_RESULTS),
            font=("Arial", 9),
        )
        results_labelframe.pack(fill="both", expand=True, padx=8, pady=(2, 8))

        self.grid_canvas = tk.Canvas(results_labelframe, bg="#e0e0e0", highlightthickness=0)
        self.grid_scrollbar = ttk.Scrollbar(
            results_labelframe, orient="vertical", command=self.grid_canvas.yview,
        )
        self.grid_canvas.configure(yscrollcommand=self.grid_scrollbar.set)

        self.grid_scrollbar.pack(side="right", fill="y")
        self.grid_canvas.pack(side="left", fill="both", expand=True)

        # inner frame inside canvas
        self.grid_inner_frame = tk.Frame(self.grid_canvas, bg="#e0e0e0")
        self.grid_inner_window = self.grid_canvas.create_window(
            (0, 0), window=self.grid_inner_frame, anchor="nw",
        )

        self.grid_inner_frame.bind("<Configure>", self._on_grid_frame_configure)
        self.grid_canvas.bind("<Configure>", self._on_grid_canvas_configure)

        # mouse wheel scrolling
        self.grid_canvas.bind_all("<MouseWheel>", self._on_mousewheel)

    # ── canvas scroll helpers ──

    def _on_grid_frame_configure(self, event):
        self.grid_canvas.configure(scrollregion=self.grid_canvas.bbox("all"))

    def _on_grid_canvas_configure(self, event):
        canvas_width = event.width
        self.grid_canvas.itemconfig(self.grid_inner_window, width=canvas_width)

    def _on_mousewheel(self, event):
        # only scroll if this window is active
        if self.winfo_exists():
            self.grid_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    # ── spinbox value helpers ──

    def _get_spinbox_value(self, var: tk.StringVar) -> int:
        val = var.get().strip()
        if val == "":
            return 0
        if val.lower().startswith("0x"):
            return int(val, 16)
        return int(val)

    def _get_alignment_value(self) -> int:
        val = self.alignment_var.get()
        if val == "None" or val == "":
            return 0
        return int(val)

    # ── scan control ──

    def _on_start_click(self):
        """Start the offset scan in a background thread."""
        try:
            start = self._get_spinbox_value(self.start_offset_var)
            end = self._get_spinbox_value(self.end_offset_var)
            step = self._get_spinbox_value(self.step_var)
            alignment = self._get_alignment_value()
            max_results = self._get_spinbox_value(self.max_results_var)
        except (ValueError, TypeError) as e:
            messagebox.showwarning("Invalid Input", str(e))
            return

        if step <= 0:
            step = 1
        if max_results <= 0:
            max_results = 50
        if start > end:
            messagebox.showwarning("Invalid Range", "Start offset must be <= end offset.")
            return

        # clear previous results
        self._clear_results()
        self._results = []
        self._cancel_event.clear()

        config = ScanConfig(
            start_offset=start,
            end_offset=end,
            step=step,
            alignment=alignment,
            max_results=max_results,
        )

        scanner = OffsetScanner(self.loaded_image_data, self.gui_params, config)

        # update UI state
        self._is_scanning = True
        self.start_btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")
        self.progress_var.set(0)
        self.status_label.configure(
            text=self.get_translation_text(TranslationKeys.TRANSLATION_TEXT_SCANNER_SCANNING)
        )
        self.summary_label.configure(text="")

        # launch scan thread
        self._scan_thread = threading.Thread(
            target=self._run_scan,
            args=(scanner, config.max_results),
            daemon=True,
        )
        self._scan_thread.start()

    def _on_cancel_click(self):
        """Signal the scan thread to cancel."""
        self._cancel_event.set()
        self.cancel_btn.configure(state="disabled")

    def _run_scan(self, scanner: OffsetScanner, max_results: int):
        """Run the scan in a background thread."""

        def progress_cb(current: int, total: int, candidate: ScanCandidate):
            """Thread-safe progress callback — schedules UI update on main thread."""
            if self.winfo_exists():
                self.master_ref.after(0, self._update_progress, current, total, candidate)

        results = scanner.scan(
            progress_callback=progress_cb,
            cancel_event=self._cancel_event,
        )

        # schedule completion handler on main thread
        if self.winfo_exists():
            self.master_ref.after(0, self._on_scan_complete, scanner, results)

    # ── UI update callbacks (called on main thread via master.after) ──

    def _update_progress(self, current: int, total: int, candidate: ScanCandidate):
        """Update progress bar and add thumbnail to grid if valid."""
        if not self.winfo_exists():
            return

        pct = (current / total * 100) if total > 0 else 0
        self.progress_var.set(pct)
        self.status_label.configure(text=f"{current}/{total}")

        if candidate.is_valid and candidate.thumbnail:
            self._results.append(candidate)
            self._add_thumbnail_to_grid(candidate, len(self._results) - 1)

    def _on_scan_complete(self, scanner: OffsetScanner, results: List[ScanCandidate]):
        """Handle scan completion on the main thread."""
        self._is_scanning = False
        self.start_btn.configure(state="normal")
        self.cancel_btn.configure(state="disabled")
        self.progress_var.set(100)

        summary = scanner.summary
        tr = self.get_translation_text

        status_text = tr(TranslationKeys.TRANSLATION_TEXT_SCANNER_COMPLETE)
        if summary.cancelled:
            status_text += " (cancelled)"
        self.status_label.configure(text=status_text)

        summary_text = (
            f"{tr(TranslationKeys.TRANSLATION_TEXT_SCANNER_SUMMARY_SCANNED)}: {summary.total_scanned}  |  "
            f"{tr(TranslationKeys.TRANSLATION_TEXT_SCANNER_SUMMARY_VALID)}: {summary.valid_count}  |  "
            f"{tr(TranslationKeys.TRANSLATION_TEXT_SCANNER_SUMMARY_SKIPPED)}: {summary.skipped_count}"
        )
        self.summary_label.configure(text=summary_text)

    # ── thumbnail grid ──

    def _clear_results(self):
        """Remove all thumbnails from the grid."""
        for widget in self.grid_inner_frame.winfo_children():
            widget.destroy()
        self._thumbnail_refs.clear()

    def _add_thumbnail_to_grid(self, candidate: ScanCandidate, index: int):
        """Add a single thumbnail cell to the grid."""
        row = index // GRID_COLUMNS
        col = index % GRID_COLUMNS

        cell_frame = tk.Frame(self.grid_inner_frame, bg="#e0e0e0", cursor="hand2")
        cell_frame.grid(row=row, column=col, padx=3, pady=3, sticky="nsew")

        # thumbnail image
        if candidate.thumbnail:
            ph_img = ImageTk.PhotoImage(candidate.thumbnail)
            self._thumbnail_refs.append(ph_img)

            img_label = tk.Label(cell_frame, image=ph_img, bg="#e0e0e0", cursor="hand2")
            img_label.pack(pady=(2, 0))
            img_label.bind("<Button-1>", lambda e, off=candidate.offset: self._on_thumbnail_click(off))

        # offset text
        offset_hex = f"0x{candidate.offset:X}"
        offset_text = f"{offset_hex}\n({candidate.offset})"
        text_label = tk.Label(
            cell_frame, text=offset_text, font=("Arial", 7),
            bg="#e0e0e0", cursor="hand2",
        )
        text_label.pack(pady=(0, 2))
        text_label.bind("<Button-1>", lambda e, off=candidate.offset: self._on_thumbnail_click(off))

    def _on_thumbnail_click(self, offset: int):
        """Handle click on a thumbnail — apply offset and close dialog."""
        logger.info(f"Offset scanner: applying offset {offset} (0x{offset:X})")
        self._cleanup()
        self.apply_callback(offset)
        self.destroy()

    # ── cleanup ──

    def _on_close(self):
        """Handle window close."""
        if self._is_scanning:
            self._cancel_event.set()
        self._cleanup()
        self.destroy()

    def _cleanup(self):
        """Unbind mousewheel and clean up."""
        try:
            self.grid_canvas.unbind_all("<MouseWheel>")
        except Exception:
            pass
