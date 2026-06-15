"""
Copyright © 2024-2026  Bartłomiej Duda
License: GPL-3.0 License
"""

import platform
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

import center_tk_window
from reversebox.common.logger import get_logger

from src.Image.constants import (
    SUPPORTED_PALETTE_SCALE_TYPES,
    TranslationKeys,
)
from src.Image.preset_manager import PresetError, PresetManager, PresetValidationResult

logger = get_logger(__name__)

DIALOG_WIDTH = 450
DIALOG_HEIGHT = 420


class PresetManagerDialog:
    def __init__(self, gui_object, preset_manager: PresetManager):
        self.gui = gui_object
        self.preset_manager = preset_manager

        self.dialog = tk.Toplevel(width=DIALOG_WIDTH, height=DIALOG_HEIGHT)
        self.dialog.wm_title(self.gui.get_translation_text(TranslationKeys.TRANSLATION_TEXT_PRESET_DIALOG_TITLE))
        self.dialog.minsize(DIALOG_WIDTH, DIALOG_HEIGHT)
        self.dialog.maxsize(DIALOG_WIDTH, DIALOG_HEIGHT)
        self.dialog.resizable(False, False)
        if platform.uname().system != "Linux":
            self.dialog.wm_attributes("-toolwindow", "True")
        self.dialog.attributes("-topmost", "true")

        self.main_frame = tk.Frame(self.dialog, bg="#f0f0f0")
        self.main_frame.place(x=0, y=0, relwidth=1, relheight=1)

        self._build_ui()
        self._refresh_preset_list()

        self.dialog.lift()
        self.dialog.focus_force()
        center_tk_window.center_on_screen(self.dialog)

    def _build_ui(self):
        # Listbox with scrollbar
        list_frame = tk.Frame(self.main_frame, bg="#f0f0f0")
        list_frame.place(x=10, y=10, width=430, height=180)

        scrollbar = tk.Scrollbar(list_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.preset_listbox = tk.Listbox(
            list_frame,
            selectmode=tk.SINGLE,
            font=("Arial", 9),
            yscrollcommand=scrollbar.set,
        )
        self.preset_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.preset_listbox.yview)
        self.preset_listbox.bind("<<ListboxSelect>>", self._on_select)

        # Buttons
        btn_y = 200
        btn_h = 28
        btn_w = 90

        self.apply_btn = tk.Button(
            self.main_frame,
            text=self.gui.get_translation_text(TranslationKeys.TRANSLATION_TEXT_PRESET_DIALOG_APPLY),
            command=self._apply_selected,
        )
        self.apply_btn.place(x=10, y=btn_y, width=btn_w, height=btn_h)

        self.rename_btn = tk.Button(
            self.main_frame,
            text=self.gui.get_translation_text(TranslationKeys.TRANSLATION_TEXT_PRESET_DIALOG_RENAME),
            command=self._rename_selected,
        )
        self.rename_btn.place(x=110, y=btn_y, width=btn_w, height=btn_h)

        self.delete_btn = tk.Button(
            self.main_frame,
            text=self.gui.get_translation_text(TranslationKeys.TRANSLATION_TEXT_PRESET_DIALOG_DELETE),
            command=self._delete_selected,
        )
        self.delete_btn.place(x=210, y=btn_y, width=btn_w, height=btn_h)

        self.close_btn = tk.Button(
            self.main_frame,
            text=self.gui.get_translation_text(TranslationKeys.TRANSLATION_TEXT_PRESET_DIALOG_CLOSE),
            command=self._close,
        )
        self.close_btn.place(x=310, y=btn_y, width=btn_w, height=btn_h)

        # Preview frame
        preview_y = 240
        preview_h = 170
        self.preview_labelframe = tk.LabelFrame(
            self.main_frame,
            text=self.gui.get_translation_text(TranslationKeys.TRANSLATION_TEXT_PRESET_DIALOG_PREVIEW),
            bg="#f0f0f0",
        )
        self.preview_labelframe.place(x=10, y=preview_y, width=430, height=preview_h)

        self.preview_labels: dict = {}
        preview_fields = [
            ("pixel_format", "Pixel Format", 0, 0),
            ("endianess_type", "Endianess", 0, 1),
            ("swizzling_type", "Swizzling", 1, 0),
            ("compression_type", "Compression", 1, 1),
            ("img_width", "Width", 2, 0),
            ("img_height", "Height", 2, 1),
            ("img_start_offset", "Start Offset", 3, 0),
            ("img_end_offset", "End Offset", 3, 1),
            ("palette_format", "Palette Format", 4, 0),
            ("palette_offset", "Palette Offset", 4, 1),
            ("palette_scale_value", "Palette Scale", 5, 0),
            ("palette_endianess", "Palette Endianess", 5, 1),
            ("palette_ps2_swizzle_flag", "PS2 Pal. Swizzle", 6, 0),
        ]
        for field_key, label_text, row, col in preview_fields:
            label = tk.Label(
                self.preview_labelframe,
                text=f"{label_text}: -",
                font=("Arial", 8),
                bg="#f0f0f0",
                anchor="w",
            )
            label.grid(row=row, column=col, sticky="w", padx=5, pady=1)
            self.preview_labels[field_key] = label

        self._clear_preview()

    def _refresh_preset_list(self):
        self.preset_listbox.delete(0, tk.END)
        presets = self.preset_manager.list_presets()
        for name in presets:
            self.preset_listbox.insert(tk.END, name)

    def _on_select(self, event):
        selection = self.preset_listbox.curselection()
        if not selection:
            self._clear_preview()
            return

        name = self.preset_listbox.get(selection[0])
        try:
            result = self.preset_manager.load_preset(name)
            if result.is_valid and result.preset_data:
                self._update_preview(result.preset_data)
            else:
                self._show_preview_with_errors(result)
        except PresetError as error:
            logger.error(f"Failed to preview preset: {error}")
            self._clear_preview()

    def _update_preview(self, preset_data: dict):
        img = preset_data.get("image", {})
        pal = preset_data.get("palette", {})

        scale_display = str(pal.get("palette_scale_value", 1))
        for st in SUPPORTED_PALETTE_SCALE_TYPES:
            if st.scale_value == pal.get("palette_scale_value", 1):
                scale_display = st.display_name
                break

        values = {
            "pixel_format": img.get("pixel_format", "-"),
            "endianess_type": img.get("endianess_type", "-"),
            "swizzling_type": img.get("swizzling_type", "-"),
            "compression_type": img.get("compression_type", "-"),
            "img_width": str(img.get("img_width", "-")),
            "img_height": str(img.get("img_height", "-")),
            "img_start_offset": str(img.get("img_start_offset", "-")),
            "img_end_offset": str(img.get("img_end_offset", "-")),
            "palette_format": pal.get("palette_format", "-"),
            "palette_offset": str(pal.get("palette_offset", "-")),
            "palette_scale_value": scale_display,
            "palette_endianess": pal.get("palette_endianess", "-"),
            "palette_ps2_swizzle_flag": str(pal.get("palette_ps2_swizzle_flag", False)),
        }
        for field_key, label in self.preview_labels.items():
            display_name = label.cget("text").split(":")[0]
            label.config(text=f"{display_name}: {values.get(field_key, '-')}")

    def _show_preview_with_errors(self, result: PresetValidationResult):
        for field_key, label in self.preview_labels.items():
            display_name = label.cget("text").split(":")[0]
            # Check if this field has an error
            has_error = False
            for error in result.errors:
                if field_key in error.field_path:
                    label.config(text=f"{display_name}: [ERROR]", fg="red")
                    has_error = True
                    break
            if not has_error:
                label.config(fg="black")
                label.config(text=f"{display_name}: -")

    def _clear_preview(self):
        for label in self.preview_labels.values():
            display_name = label.cget("text").split(":")[0]
            label.config(text=f"{display_name}: -", fg="black")

    def _get_selected_name(self) -> str:
        selection = self.preset_listbox.curselection()
        if not selection:
            return ""
        return self.preset_listbox.get(selection[0])

    def _apply_selected(self):
        name = self._get_selected_name()
        if not name:
            messagebox.showinfo(
                self.gui.get_translation_text(TranslationKeys.TRANSLATION_TEXT_PRESET_ERROR_TITLE),
                self.gui.get_translation_text(TranslationKeys.TRANSLATION_TEXT_PRESET_NO_SELECTION),
                parent=self.dialog,
            )
            return

        try:
            result = self.preset_manager.load_preset(name)
        except PresetError as error:
            messagebox.showerror(
                self.gui.get_translation_text(TranslationKeys.TRANSLATION_TEXT_PRESET_ERROR_TITLE),
                str(error),
                parent=self.dialog,
            )
            return

        if not result.is_valid:
            error_lines = [f"  - {e.field_path}: {e.reason} (value: {e.original_value})" for e in result.errors]
            message = self.gui.get_translation_text(TranslationKeys.TRANSLATION_TEXT_PRESET_ERROR_INVALID)
            message += "\n" + "\n".join(error_lines)
            messagebox.showerror(
                self.gui.get_translation_text(TranslationKeys.TRANSLATION_TEXT_PRESET_ERROR_TITLE),
                message,
                parent=self.dialog,
            )
            return

        # Show warnings if any
        if result.warnings:
            warning_text = "\n".join(f"  - {w}" for w in result.warnings)
            messagebox.showwarning(
                self.gui.get_translation_text(TranslationKeys.TRANSLATION_TEXT_PRESET_WARNINGS_TITLE),
                warning_text,
                parent=self.dialog,
            )

        # Apply the preset to GUI
        self.gui._apply_preset_to_gui(result.preset_data)
        self._close()

    def _rename_selected(self):
        name = self._get_selected_name()
        if not name:
            messagebox.showinfo(
                self.gui.get_translation_text(TranslationKeys.TRANSLATION_TEXT_PRESET_ERROR_TITLE),
                self.gui.get_translation_text(TranslationKeys.TRANSLATION_TEXT_PRESET_NO_SELECTION),
                parent=self.dialog,
            )
            return

        new_name = simpledialog.askstring(
            self.gui.get_translation_text(TranslationKeys.TRANSLATION_TEXT_PRESET_RENAME_TITLE),
            self.gui.get_translation_text(TranslationKeys.TRANSLATION_TEXT_PRESET_RENAME_PROMPT),
            initialvalue=name,
            parent=self.dialog,
        )
        if not new_name or new_name.strip() == "":
            return

        try:
            self.preset_manager.rename_preset(name, new_name.strip())
        except PresetError as error:
            messagebox.showerror(
                self.gui.get_translation_text(TranslationKeys.TRANSLATION_TEXT_PRESET_ERROR_TITLE),
                str(error),
                parent=self.dialog,
            )
            return

        self._refresh_preset_list()
        # Select the renamed preset
        presets = self.preset_manager.list_presets()
        sanitized = self.preset_manager.sanitize_filename(new_name.strip())
        if sanitized in presets:
            idx = presets.index(sanitized)
            self.preset_listbox.selection_set(idx)
            self.preset_listbox.see(idx)

    def _delete_selected(self):
        name = self._get_selected_name()
        if not name:
            messagebox.showinfo(
                self.gui.get_translation_text(TranslationKeys.TRANSLATION_TEXT_PRESET_ERROR_TITLE),
                self.gui.get_translation_text(TranslationKeys.TRANSLATION_TEXT_PRESET_NO_SELECTION),
                parent=self.dialog,
            )
            return

        confirm = messagebox.askyesno(
            self.gui.get_translation_text(TranslationKeys.TRANSLATION_TEXT_PRESET_DELETE_CONFIRM_TITLE),
            self.gui.get_translation_text(TranslationKeys.TRANSLATION_TEXT_PRESET_DELETE_CONFIRM_MSG),
            parent=self.dialog,
        )
        if not confirm:
            return

        try:
            self.preset_manager.delete_preset(name)
        except PresetError as error:
            messagebox.showerror(
                self.gui.get_translation_text(TranslationKeys.TRANSLATION_TEXT_PRESET_ERROR_TITLE),
                str(error),
                parent=self.dialog,
            )
            return

        self._refresh_preset_list()
        self._clear_preview()

    def _close(self):
        self.dialog.destroy()
