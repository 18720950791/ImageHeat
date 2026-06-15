"""
Copyright © 2026  Bartłomiej Duda
License: GPL-3.0 License
"""

import copy
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import List, Optional

import center_tk_window
from PIL import Image, ImageTk
from PIL.Image import Resampling
from reversebox.common.logger import get_logger
from reversebox.image.image_formats import ImageFormats

from src.GUI.gui_params import GuiParams
from src.Image.constants import TranslationKeys
from src.Image.heatimage import HeatImage

logger = get_logger(__name__)

# bpp lookup is optional - we degrade gracefully if reversebox can't resolve it
try:
    from reversebox.image.common import get_bpp_for_image_format
except Exception:  # pragma: no cover - defensive import
    get_bpp_for_image_format = None


class OffsetScannerWindow:
    """
    Tool window that scans a range of candidate image offsets using the
    currently selected texture parameters and shows decoded thumbnails in a
    grid. Clicking a thumbnail applies that offset to the main preview.

    The scan runs in a background daemon thread, can be cancelled at any time,
    stops after a configurable number of results, and skips (while counting)
    any candidate that would read out of bounds or that fails to decode.
    """

    COLUMNS: int = 4
    THUMB_BOX: int = 110  # max thumbnail edge length in pixels
    WINDOW_WIDTH: int = 560
    WINDOW_HEIGHT: int = 600
    DEFAULT_MAX_RESULTS: int = 64
    ALIGNMENT_VALUES = ["1", "2", "4", "8", "16", "32", "64", "128", "256"]

    def __init__(self, gui_object):
        self.gui_object = gui_object
        self.master = gui_object.master

        # refresh gui_params so we scan with the parameters currently on screen
        self.gui_object.get_gui_params_from_gui_elements()

        # scan state
        self._cancel_event: threading.Event = threading.Event()
        self._scan_thread: Optional[threading.Thread] = None
        self._is_scanning: bool = False
        self._last_span: int = 0
        self._thumb_refs: List[ImageTk.PhotoImage] = []  # keep refs (avoid GC)
        self._result_widgets: List[tk.Widget] = []
        self._result_count: int = 0

        self._build_window()
        self._prefill_defaults()

    # ------------------------------------------------------------------ #
    #                               helpers                              #
    # ------------------------------------------------------------------ #

    def _t(self, translation_id: str) -> str:
        return self.gui_object.get_translation_text(translation_id)

    @staticmethod
    def _parse_int(value: str, default: Optional[int] = None) -> Optional[int]:
        value = (value or "").strip()
        if value == "":
            return default
        if value.lower().startswith("0x"):
            return int(value, 16)
        return int(value)

    def _bits_per_pixel(self) -> int:
        if get_bpp_for_image_format is None:
            return 32
        try:
            image_format: ImageFormats = ImageFormats[self.gui_object.gui_params.pixel_format]
            return max(1, get_bpp_for_image_format(image_format))
        except Exception:
            return 32

    def _full_image_byte_size(self, width: int, height: int) -> int:
        bpp: int = self._bits_per_pixel()
        return max(1, (width * height * bpp) // 8)

    def window_exists(self) -> bool:
        try:
            return bool(self.scanner_window.winfo_exists())
        except Exception:
            return False

    # ------------------------------------------------------------------ #
    #                            window building                         #
    # ------------------------------------------------------------------ #

    def _build_window(self) -> None:
        gui_font = self.gui_object.gui_font

        self.scanner_window = tk.Toplevel(width=self.WINDOW_WIDTH, height=self.WINDOW_HEIGHT)
        self.scanner_window.wm_title(self._t(TranslationKeys.TRANSLATION_TEXT_SCANNER_WINDOW_TITLE))
        self.scanner_window.minsize(self.WINDOW_WIDTH, self.WINDOW_HEIGHT)
        self.scanner_window.protocol("WM_DELETE_WINDOW", self._on_close)

        # ---- parameters frame ----
        self.params_frame = tk.LabelFrame(
            self.scanner_window,
            text=self._t(TranslationKeys.TRANSLATION_TEXT_SCANNER_PARAMS_FRAME),
            font=gui_font,
        )
        self.params_frame.pack(side="top", fill="x", padx=5, pady=5)

        # start offset
        tk.Label(
            self.params_frame, text=self._t(TranslationKeys.TRANSLATION_TEXT_SCANNER_START),
            anchor="w", font=gui_font,
        ).grid(row=0, column=0, sticky="w", padx=4, pady=3)
        self.start_var = tk.StringVar()
        tk.Entry(self.params_frame, textvariable=self.start_var, font=gui_font, width=16).grid(
            row=0, column=1, sticky="w", padx=4, pady=3
        )

        # end offset
        tk.Label(
            self.params_frame, text=self._t(TranslationKeys.TRANSLATION_TEXT_SCANNER_END),
            anchor="w", font=gui_font,
        ).grid(row=0, column=2, sticky="w", padx=4, pady=3)
        self.end_var = tk.StringVar()
        tk.Entry(self.params_frame, textvariable=self.end_var, font=gui_font, width=16).grid(
            row=0, column=3, sticky="w", padx=4, pady=3
        )

        # step
        tk.Label(
            self.params_frame, text=self._t(TranslationKeys.TRANSLATION_TEXT_SCANNER_STEP),
            anchor="w", font=gui_font,
        ).grid(row=1, column=0, sticky="w", padx=4, pady=3)
        self.step_var = tk.StringVar()
        tk.Entry(self.params_frame, textvariable=self.step_var, font=gui_font, width=16).grid(
            row=1, column=1, sticky="w", padx=4, pady=3
        )

        # alignment
        tk.Label(
            self.params_frame, text=self._t(TranslationKeys.TRANSLATION_TEXT_SCANNER_ALIGNMENT),
            anchor="w", font=gui_font,
        ).grid(row=1, column=2, sticky="w", padx=4, pady=3)
        self.alignment_combobox = ttk.Combobox(
            self.params_frame, values=self.ALIGNMENT_VALUES, font=gui_font, state="readonly", width=13
        )
        self.alignment_combobox.grid(row=1, column=3, sticky="w", padx=4, pady=3)

        # max results
        tk.Label(
            self.params_frame, text=self._t(TranslationKeys.TRANSLATION_TEXT_SCANNER_MAX_RESULTS),
            anchor="w", font=gui_font,
        ).grid(row=2, column=0, sticky="w", padx=4, pady=3)
        self.max_results_var = tk.StringVar()
        tk.Entry(self.params_frame, textvariable=self.max_results_var, font=gui_font, width=16).grid(
            row=2, column=1, sticky="w", padx=4, pady=3
        )

        # buttons
        button_frame = tk.Frame(self.params_frame)
        button_frame.grid(row=3, column=0, columnspan=4, sticky="w", padx=4, pady=5)
        self.scan_button = tk.Button(
            button_frame, text=self._t(TranslationKeys.TRANSLATION_TEXT_SCANNER_SCAN),
            font=gui_font, width=10, command=self._start_scan,
        )
        self.scan_button.pack(side="left", padx=2)
        self.cancel_button = tk.Button(
            button_frame, text=self._t(TranslationKeys.TRANSLATION_TEXT_SCANNER_CANCEL),
            font=gui_font, width=10, command=self._cancel_scan, state="disabled",
        )
        self.cancel_button.pack(side="left", padx=2)
        self.close_button = tk.Button(
            button_frame, text=self._t(TranslationKeys.TRANSLATION_TEXT_SCANNER_CLOSE),
            font=gui_font, width=10, command=self._on_close,
        )
        self.close_button.pack(side="left", padx=2)

        # ---- status label ----
        self.status_var = tk.StringVar(value=self._t(TranslationKeys.TRANSLATION_TEXT_SCANNER_STATUS_READY))
        self.status_label = tk.Label(
            self.scanner_window, textvariable=self.status_var, anchor="w", font=gui_font
        )
        self.status_label.pack(side="top", fill="x", padx=8, pady=(0, 3))

        # ---- results frame (scrollable thumbnail grid) ----
        self.results_frame = tk.LabelFrame(
            self.scanner_window,
            text=self._t(TranslationKeys.TRANSLATION_TEXT_SCANNER_RESULTS_FRAME),
            font=gui_font,
        )
        self.results_frame.pack(side="top", fill="both", expand=True, padx=5, pady=5)

        self.results_canvas = tk.Canvas(self.results_frame, bg="#f0f0f0", highlightthickness=0)
        self.results_canvas.pack(side="left", fill="both", expand=True)

        self.results_scrollbar = tk.Scrollbar(
            self.results_frame, orient="vertical", command=self.results_canvas.yview
        )
        self.results_scrollbar.pack(side="right", fill="y")
        self.results_canvas.configure(yscrollcommand=self.results_scrollbar.set)

        self.results_inner = tk.Frame(self.results_canvas, bg="#f0f0f0")
        self.results_canvas.create_window((0, 0), window=self.results_inner, anchor="nw")
        self.results_inner.bind(
            "<Configure>",
            lambda event: self.results_canvas.configure(scrollregion=self.results_canvas.bbox("all")),
        )

        # mouse wheel scroll only while pointer is over the results area, so the
        # main window's wheel-to-zoom binding is left untouched
        self.results_canvas.bind("<Enter>", self._bind_mousewheel)
        self.results_canvas.bind("<Leave>", self._unbind_mousewheel)

        self.scanner_window.lift()
        self.scanner_window.focus_force()
        center_tk_window.center_on_screen(self.scanner_window)

    def _prefill_defaults(self) -> None:
        gui_params: GuiParams = self.gui_object.gui_params
        total_size: int = int(gui_params.total_file_size or 0)
        start_offset: int = int(gui_params.img_start_offset or 0)
        width: int = int(gui_params.img_width or 0)

        # default step = one row of pixels (lands candidates on row boundaries),
        # falling back to 16 bytes if width/bpp can't be resolved
        bpp: int = self._bits_per_pixel()
        row_bytes: int = (width * bpp) // 8
        default_step: int = row_bytes if row_bytes > 0 else 16

        self.start_var.set(str(start_offset))
        self.end_var.set(str(total_size))
        self.step_var.set(str(default_step))
        self.alignment_combobox.set("4")
        self.max_results_var.set(str(self.DEFAULT_MAX_RESULTS))

    # ------------------------------------------------------------------ #
    #                            scan control                            #
    # ------------------------------------------------------------------ #

    def _start_scan(self) -> None:
        if self._is_scanning:
            return

        opened_image = self.gui_object.opened_image
        if opened_image is None or not opened_image.loaded_image_data:
            messagebox.showwarning("Warning", self._t(TranslationKeys.TRANSLATION_TEXT_SCANNER_NO_FILE))
            return

        # refresh params so we use exactly what's currently configured
        self.gui_object.get_gui_params_from_gui_elements()
        gui_params: GuiParams = self.gui_object.gui_params

        width: int = int(gui_params.img_width or 0)
        height: int = int(gui_params.img_height or 0)
        if width <= 0 or height <= 0:
            messagebox.showwarning(
                "Warning", self._t(TranslationKeys.TRANSLATION_TEXT_SCANNER_INVALID_DIMENSIONS)
            )
            return

        try:
            start_offset: int = self._parse_int(self.start_var.get(), 0)
            end_offset: int = self._parse_int(self.end_var.get(), 0)
            step: int = self._parse_int(self.step_var.get(), 0)
            alignment: int = int(self.alignment_combobox.get())
            max_results: int = self._parse_int(self.max_results_var.get(), 0)
        except (ValueError, TypeError):
            messagebox.showwarning("Warning", self._t(TranslationKeys.TRANSLATION_TEXT_SCANNER_INVALID_PARAMS))
            return

        if start_offset < 0 or end_offset < start_offset or step < 1 or alignment < 1 or max_results < 1:
            messagebox.showwarning("Warning", self._t(TranslationKeys.TRANSLATION_TEXT_SCANNER_INVALID_PARAMS))
            return

        loaded_data: bytes = opened_image.loaded_image_data
        total_size: int = len(loaded_data)

        # span of bytes to decode per candidate = the span currently being viewed;
        # fall back to a full width*height image if start==end
        span: int = int(gui_params.img_end_offset) - int(gui_params.img_start_offset)
        if span <= 0:
            span = self._full_image_byte_size(width, height)
        self._last_span = span

        # snapshot params for the worker thread (decoding mutates gui_params for
        # some swizzle modes, so each candidate gets its own copy)
        base_params: GuiParams = copy.copy(gui_params)

        # reset UI for a fresh scan
        self._clear_results()
        self._cancel_event = threading.Event()
        self._is_scanning = True
        self.scan_button.config(state="disabled")
        self.cancel_button.config(state="normal")
        self.status_var.set(self._t(TranslationKeys.TRANSLATION_TEXT_SCANNER_STATUS_SCANNING))

        self._scan_thread = threading.Thread(
            target=self._scan_worker,
            args=(loaded_data, base_params, total_size, width, height, span,
                  start_offset, end_offset, step, alignment, max_results),
            daemon=True,
        )
        self._scan_thread.start()

    def _cancel_scan(self) -> None:
        self._cancel_event.set()

    def _on_close(self) -> None:
        self._cancel_event.set()
        if getattr(self.gui_object, "offset_scanner_instance", None) is self:
            self.gui_object.offset_scanner_instance = None
        try:
            self._unbind_mousewheel(None)
        except Exception:
            pass
        self.scanner_window.destroy()

    # ------------------------------------------------------------------ #
    #                          worker (background)                       #
    # ------------------------------------------------------------------ #

    def _scan_worker(self, loaded_data, base_params, total_size, width, height, span,
                     start_offset, end_offset, step, alignment, max_results) -> None:
        scanned = found = skipped_oob = skipped_bad = 0
        last_aligned: Optional[int] = None
        limit_reached: bool = False

        current_offset: int = start_offset
        while current_offset <= end_offset:
            if self._cancel_event.is_set():
                break

            aligned_offset: int = (current_offset // alignment) * alignment
            current_offset += step

            # floored alignment is monotonic, so duplicates are always adjacent
            if aligned_offset == last_aligned:
                continue
            last_aligned = aligned_offset

            scanned += 1

            # out-of-bounds read -> skip and count
            if aligned_offset < 0 or aligned_offset + span > total_size:
                skipped_oob += 1
                continue

            thumbnail: Optional[Image.Image] = self._decode_candidate(
                loaded_data, base_params, aligned_offset, span, width, height
            )
            if thumbnail is None:
                skipped_bad += 1
                continue

            found += 1
            self.master.after(0, self._add_result, aligned_offset, thumbnail)
            self.master.after(0, self._update_progress, scanned, found, skipped_oob, skipped_bad)

            if found >= max_results:
                limit_reached = True
                break

        cancelled: bool = self._cancel_event.is_set()
        self.master.after(
            0, self._finish_scan, scanned, found, skipped_oob, skipped_bad, limit_reached, cancelled
        )

    def _decode_candidate(self, loaded_data, base_params, offset, span, width, height) -> Optional[Image.Image]:
        try:
            candidate_params: GuiParams = copy.copy(base_params)
            candidate_params.img_start_offset = offset
            candidate_params.img_end_offset = offset + span

            heat_image = HeatImage(candidate_params)
            heat_image.loaded_image_data = loaded_data
            heat_image.is_data_loaded_from_file = True
            heat_image.image_reload()

            if heat_image.is_preview_error or not heat_image.decoded_image_data:
                return None

            return self._build_thumbnail(heat_image.decoded_image_data, width, height)
        except Exception as error:
            logger.info(f"[SCANNER] Candidate at offset {offset} could not be decoded. Error: {error}")
            return None

    def _build_thumbnail(self, decoded_data: bytes, width: int, height: int) -> Optional[Image.Image]:
        if width <= 0 or height <= 0:
            return None

        needed: int = width * height * 4
        if needed <= 0:
            return None

        data: bytes = bytes(decoded_data)
        if len(data) < needed:
            data = data + b"\x00" * (needed - len(data))
        elif len(data) > needed:
            data = data[:needed]

        rgba_image = Image.frombuffer("RGBA", (width, height), data, "raw", "RGBA", 0, 1)

        scale: float = min(self.THUMB_BOX / width, self.THUMB_BOX / height)
        thumb_width: int = max(1, round(width * scale))
        thumb_height: int = max(1, round(height * scale))
        rgba_image = rgba_image.resize((thumb_width, thumb_height), Resampling.NEAREST)

        # composite over a neutral gray so transparent textures stay visible
        background = Image.new("RGB", (thumb_width, thumb_height), (89, 89, 89))
        background.paste(rgba_image, (0, 0), rgba_image)
        return background

    # ------------------------------------------------------------------ #
    #                        main-thread UI updates                      #
    # ------------------------------------------------------------------ #

    def _add_result(self, offset: int, pil_thumbnail: Image.Image) -> None:
        if not self.window_exists():
            return
        photo_image = ImageTk.PhotoImage(pil_thumbnail)
        self._thumb_refs.append(photo_image)

        index: int = self._result_count
        self._result_count += 1
        row: int = index // self.COLUMNS
        column: int = index % self.COLUMNS

        cell = tk.Frame(self.results_inner, bg="#f0f0f0")
        button = tk.Button(
            cell, image=photo_image, cursor="hand2", relief="solid", borderwidth=1,
            command=lambda captured_offset=offset: self._apply_offset(captured_offset),
        )
        button.pack()
        caption = tk.Label(
            cell, text=f"0x{offset:X}\n{offset}", font=("Arial", 7), bg="#f0f0f0", justify="center"
        )
        caption.pack()
        cell.grid(row=row, column=column, padx=4, pady=4, sticky="n")
        self._result_widgets.append(cell)

        self.results_inner.update_idletasks()
        self.results_canvas.configure(scrollregion=self.results_canvas.bbox("all"))

    def _update_progress(self, scanned: int, found: int, skipped_oob: int, skipped_bad: int) -> None:
        if not self.window_exists():
            return
        prefix: str = self._t(TranslationKeys.TRANSLATION_TEXT_SCANNER_STATUS_SCANNING)
        self.status_var.set(f"{prefix}  {self._summary_text(scanned, found, skipped_oob, skipped_bad)}")

    def _finish_scan(self, scanned, found, skipped_oob, skipped_bad, limit_reached, cancelled) -> None:
        self._is_scanning = False
        if self.window_exists():
            self.scan_button.config(state="normal")
            self.cancel_button.config(state="disabled")

            if cancelled:
                state_text = self._t(TranslationKeys.TRANSLATION_TEXT_SCANNER_STATUS_CANCELLED)
            elif limit_reached:
                state_text = self._t(TranslationKeys.TRANSLATION_TEXT_SCANNER_STATUS_LIMIT)
            else:
                state_text = self._t(TranslationKeys.TRANSLATION_TEXT_SCANNER_STATUS_DONE)

            summary: str = self._summary_text(scanned, found, skipped_oob, skipped_bad)
            self.status_var.set(f"{state_text}  —  {summary}")

    def _summary_text(self, scanned: int, found: int, skipped_oob: int, skipped_bad: int) -> str:
        scanned_label = self._t(TranslationKeys.TRANSLATION_TEXT_SCANNER_SUMMARY_SCANNED)
        found_label = self._t(TranslationKeys.TRANSLATION_TEXT_SCANNER_SUMMARY_FOUND)
        oob_label = self._t(TranslationKeys.TRANSLATION_TEXT_SCANNER_SUMMARY_OOB)
        bad_label = self._t(TranslationKeys.TRANSLATION_TEXT_SCANNER_SUMMARY_UNDECODABLE)
        return (
            f"{scanned_label}: {scanned} | {found_label}: {found} | "
            f"{oob_label}: {skipped_oob} | {bad_label}: {skipped_bad}"
        )

    def _clear_results(self) -> None:
        for widget in self._result_widgets:
            try:
                widget.destroy()
            except Exception:
                pass
        self._result_widgets = []
        self._thumb_refs = []
        self._result_count = 0
        self.results_canvas.configure(scrollregion=(0, 0, 0, 0))
        self.results_canvas.yview_moveto(0)

    def _apply_offset(self, offset: int) -> None:
        total_size: int = int(self.gui_object.gui_params.total_file_size or 0)
        end_offset: int = offset + self._last_span
        if total_size > 0 and end_offset > total_size:
            end_offset = total_size

        self.gui_object.current_start_offset.set(str(offset))
        self.gui_object.current_end_offset.set(str(end_offset))
        self.gui_object.gui_reload_image_on_gui_element_change()

    # ------------------------------------------------------------------ #
    #                           mouse wheel                              #
    # ------------------------------------------------------------------ #

    def _bind_mousewheel(self, _event) -> None:
        self.results_canvas.bind_all("<MouseWheel>", self._on_mousewheel)

    def _unbind_mousewheel(self, _event) -> None:
        self.results_canvas.unbind_all("<MouseWheel>")

    def _on_mousewheel(self, event) -> None:
        self.results_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
