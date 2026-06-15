"""
Copyright © 2024-2026  Bartłomiej Duda
License: GPL-3.0 License
"""

import json
import os
from typing import Dict, List, Optional, Tuple

from reversebox.common.logger import get_logger

from src.Image.constants import (
    COMPRESSION_TYPES_NAMES,
    ENDIANESS_TYPES_NAMES,
    PALETTE_FORMATS_NAMES,
    PALETTE_SCALE_TYPES_NAMES,
    PIXEL_FORMATS_NAMES,
    ROTATE_TYPES_NAMES,
    SWIZZLING_TYPES_NAMES,
    ZOOM_RESAMPLING_TYPES_NAMES,
    ZOOM_TYPES_NAMES,
)

logger = get_logger(__name__)

PRESET_FILE_VERSION: int = 1

VIEW_CHANNEL_MODES: List[str] = ["RGBA", "R", "G", "B", "A"]

# string fields validated against a fixed set of valid (display) names
STRING_FIELD_VALUES: Dict[str, list] = {
    "pixel_format": PIXEL_FORMATS_NAMES,
    "endianess_type": ENDIANESS_TYPES_NAMES,
    "swizzling_type": SWIZZLING_TYPES_NAMES,
    "compression_type": COMPRESSION_TYPES_NAMES,
    "palette_format": PALETTE_FORMATS_NAMES,
    "palette_scale_name": PALETTE_SCALE_TYPES_NAMES,
    "palette_endianess": ENDIANESS_TYPES_NAMES,
    "zoom_name": ZOOM_TYPES_NAMES,
    "zoom_resampling_name": ZOOM_RESAMPLING_TYPES_NAMES,
    "rotate_name": ROTATE_TYPES_NAMES,
    "view_channel_mode": VIEW_CHANNEL_MODES,
}

# integer fields that must be non-negative
INT_FIELDS: List[str] = [
    "img_width",
    "img_height",
    "img_start_offset",
    "img_end_offset",
    "palette_offset",
]

# boolean (flag) fields
BOOL_FIELDS: List[str] = [
    "vertical_flip_flag",
    "horizontal_flip_flag",
    "palette_ps2_swizzle_flag",
]

# field with a small fixed set of valid integers
LOADFROM_FIELD: str = "palette_loadfrom_value"
LOADFROM_VALID_VALUES: List[int] = [1, 2]

# full ordered list of fields stored in a preset
ALL_PRESET_FIELDS: List[str] = (
    list(STRING_FIELD_VALUES.keys()) + INT_FIELDS + BOOL_FIELDS + [LOADFROM_FIELD]
)

# human-friendly labels used in validation error messages
FIELD_LABELS: Dict[str, str] = {
    "pixel_format": "Pixel format",
    "endianess_type": "Endianess type",
    "swizzling_type": "Swizzling type",
    "compression_type": "Compression type",
    "palette_format": "Palette format",
    "palette_scale_name": "Palette scale",
    "palette_endianess": "Palette endianess",
    "zoom_name": "Zoom",
    "zoom_resampling_name": "Resampling",
    "rotate_name": "Rotate",
    "view_channel_mode": "Channels",
    "img_width": "Image width",
    "img_height": "Image height",
    "img_start_offset": "Start offset",
    "img_end_offset": "End offset",
    "palette_offset": "Palette offset",
    "vertical_flip_flag": "Vertical flip",
    "horizontal_flip_flag": "Horizontal flip",
    "palette_ps2_swizzle_flag": "PS2 palette swizzle",
    LOADFROM_FIELD: "Palette load from",
}


def _coerce_int(value) -> Optional[int]:
    """Convert a preset value to an int. Returns None if it cannot be a valid integer.

    Accepts real ints and decimal/hex (0x...) strings. Bools are rejected on purpose,
    because they are valid for flag fields but not for numeric fields.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        text = value.strip()
        if text == "":
            return None
        try:
            if text.lower().startswith("0x"):
                return int(text, 16)
            return int(text)
        except ValueError:
            return None
    return None


class PresetManager:
    """Loads, stores and validates named texture-decoding parameter presets.

    Presets are persisted as JSON in the form::

        {"version": 1, "presets": {"<name>": {<field>: <value>, ...}, ...}}

    This class contains no GUI logic; the GUI layer is responsible for capturing the
    current parameters and for applying a validated preset back onto its widgets.
    """

    def __init__(self, presets_file_path: str):
        self.presets_file_path: str = presets_file_path
        self.presets: Dict[str, dict] = {}
        self.load()

    def load(self) -> None:
        if not os.path.exists(self.presets_file_path):
            self.presets = {}
            return
        try:
            with open(self.presets_file_path, "rt", encoding="utf8") as presets_file:
                data = json.loads(presets_file.read())
            raw = data.get("presets", data) if isinstance(data, dict) else {}
            self.presets = {name: preset for name, preset in raw.items() if isinstance(preset, dict)}
        except Exception as error:
            logger.error(f"Couldn't load presets from {self.presets_file_path}. Error: {error}")
            self.presets = {}

    def save(self) -> bool:
        try:
            with open(self.presets_file_path, "wt", encoding="utf8") as presets_file:
                json.dump(
                    {"version": PRESET_FILE_VERSION, "presets": self.presets},
                    presets_file,
                    indent=4,
                    ensure_ascii=False,
                )
            return True
        except Exception as error:
            logger.error(f"Couldn't save presets to {self.presets_file_path}. Error: {error}")
            return False

    def get_names(self) -> List[str]:
        return sorted(self.presets.keys(), key=lambda name: name.lower())

    def get(self, name: str) -> Optional[dict]:
        return self.presets.get(name)

    def exists(self, name: str) -> bool:
        return name in self.presets

    def create(self, name: str, preset_data: dict) -> bool:
        self.presets[name] = preset_data
        return self.save()

    def rename(self, old_name: str, new_name: str) -> bool:
        if old_name not in self.presets:
            return False
        self.presets[new_name] = self.presets.pop(old_name)
        return self.save()

    def delete(self, name: str) -> bool:
        if name not in self.presets:
            return False
        self.presets.pop(name)
        return self.save()

    def validate_and_resolve(self, preset: dict, current_values: dict) -> Tuple[dict, List[str]]:
        """Validate a preset against the known fields and value ranges.

        Missing (or null) fields fall back to ``current_values`` (the current defaults), so
        a partial preset only overrides what it explicitly defines. Any field that is present
        but invalid produces an error message; when at least one error is found the caller
        must not apply anything, so the current valid parameters are preserved.

        Returns a tuple ``(resolved, errors)``. ``resolved`` is only meaningful (complete and
        safe to apply) when ``errors`` is empty.
        """
        resolved: dict = {}
        errors: List[str] = []

        if not isinstance(preset, dict):
            return dict(current_values), ["Preset data is not a valid object."]

        for field in ALL_PRESET_FIELDS:
            label = FIELD_LABELS.get(field, field)

            if field not in preset or preset[field] is None:
                # missing -> keep the current default value
                resolved[field] = current_values.get(field)
                continue

            value = preset[field]

            if field in STRING_FIELD_VALUES:
                valid_values = STRING_FIELD_VALUES[field]
                if not isinstance(value, str) or value not in valid_values:
                    errors.append(f"{label}: '{value}' is not a valid option.")
                else:
                    resolved[field] = value
            elif field in INT_FIELDS:
                int_value = _coerce_int(value)
                if int_value is None or int_value < 0:
                    errors.append(f"{label}: '{value}' must be a non-negative integer.")
                else:
                    resolved[field] = int_value
            elif field in BOOL_FIELDS:
                if not isinstance(value, bool):
                    errors.append(f"{label}: '{value}' must be true or false.")
                else:
                    resolved[field] = value
            elif field == LOADFROM_FIELD:
                int_value = _coerce_int(value)
                if int_value not in LOADFROM_VALID_VALUES:
                    errors.append(f"{label}: '{value}' must be 1 (same file) or 2 (another file).")
                else:
                    resolved[field] = int_value

        return resolved, errors
