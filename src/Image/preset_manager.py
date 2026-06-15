"""
Copyright © 2024-2026  Bartłomiej Duda
License: GPL-3.0 License
"""

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, List, Optional

from reversebox.common.logger import get_logger

from src.Image.constants import (
    COMPRESSION_TYPES_NAMES,
    DEFAULT_COMPRESSION_NAME,
    DEFAULT_ENDIANESS_NAME,
    DEFAULT_PALETTE_FORMAT_NAME,
    DEFAULT_PIXEL_FORMAT_NAME,
    DEFAULT_SWIZZLING_NAME,
    ENDIANESS_TYPES_NAMES,
    PALETTE_FORMATS_NAMES,
    PIXEL_FORMATS_NAMES,
    SUPPORTED_PALETTE_SCALE_TYPES,
    SWIZZLING_TYPES_NAMES,
)

logger = get_logger(__name__)

PRESET_VERSION: int = 1
MAX_PRESET_NAME_LENGTH: int = 100
INVALID_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|]')


@dataclass
class PresetValidationError:
    field_path: str
    reason: str
    original_value: Any


@dataclass
class PresetValidationResult:
    is_valid: bool
    errors: List[PresetValidationError] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    preset_data: Optional[dict] = None


class PresetError(Exception):
    pass


class PresetManager:
    def __init__(self, presets_directory: str):
        self.presets_directory = presets_directory
        os.makedirs(self.presets_directory, exist_ok=True)

    def list_presets(self) -> List[str]:
        """Return sorted list of preset names (without .json extension)."""
        names: List[str] = []
        try:
            for filename in os.listdir(self.presets_directory):
                if filename.endswith(".json"):
                    names.append(filename[:-5])  # strip .json
        except OSError as error:
            logger.error(f"Failed to list presets: {error}")
        return sorted(names)

    def preset_exists(self, preset_name: str) -> bool:
        return os.path.isfile(self._preset_path(preset_name))

    def save_preset(self, preset_name: str, gui_params) -> None:
        """Extract preset-eligible fields from gui_params and write to JSON."""
        sanitized = self.sanitize_filename(preset_name)
        if not sanitized:
            raise PresetError("Invalid preset name.")

        data = self._extract_params_to_dict(gui_params)
        path = self._preset_path(sanitized)
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            logger.info(f"Preset saved: {sanitized}")
        except OSError as error:
            raise PresetError(f"Failed to save preset: {error}")

    def load_preset(self, preset_name: str) -> PresetValidationResult:
        """Read JSON, validate all fields, return PresetValidationResult."""
        path = self._preset_path(preset_name)
        if not os.path.isfile(path):
            raise PresetError(f"Preset file not found: {preset_name}")

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as error:
            raise PresetError(f"Failed to read preset file: {error}")

        return self._validate_preset_dict(data)

    def rename_preset(self, old_name: str, new_name: str) -> None:
        """Rename the preset file on disk."""
        sanitized_new = self.sanitize_filename(new_name)
        if not sanitized_new:
            raise PresetError("Invalid preset name.")

        old_path = self._preset_path(old_name)
        new_path = self._preset_path(sanitized_new)

        if not os.path.isfile(old_path):
            raise PresetError(f"Preset not found: {old_name}")
        if os.path.isfile(new_path):
            raise PresetError(f"Preset already exists: {sanitized_new}")

        try:
            os.rename(old_path, new_path)
            logger.info(f"Preset renamed: {old_name} -> {sanitized_new}")
        except OSError as error:
            raise PresetError(f"Failed to rename preset: {error}")

    def delete_preset(self, preset_name: str) -> None:
        """Delete the preset file."""
        path = self._preset_path(preset_name)
        if not os.path.isfile(path):
            raise PresetError(f"Preset not found: {preset_name}")
        try:
            os.remove(path)
            logger.info(f"Preset deleted: {preset_name}")
        except OSError as error:
            raise PresetError(f"Failed to delete preset: {error}")

    def _preset_path(self, preset_name: str) -> str:
        return os.path.join(self.presets_directory, preset_name + ".json")

    @staticmethod
    def sanitize_filename(name: str) -> str:
        """Strip dangerous chars and limit length."""
        if not name:
            return ""
        cleaned = INVALID_FILENAME_CHARS.sub("", name).strip()
        if len(cleaned) > MAX_PRESET_NAME_LENGTH:
            cleaned = cleaned[:MAX_PRESET_NAME_LENGTH]
        return cleaned

    def _extract_params_to_dict(self, gui_params) -> dict:
        """Pull preset-eligible fields from GuiParams into the JSON dict structure."""
        return {
            "preset_version": PRESET_VERSION,
            "image": {
                "pixel_format": gui_params.pixel_format or DEFAULT_PIXEL_FORMAT_NAME,
                "endianess_type": gui_params.endianess_type or DEFAULT_ENDIANESS_NAME,
                "swizzling_type": gui_params.swizzling_type or DEFAULT_SWIZZLING_NAME,
                "compression_type": gui_params.compression_type or DEFAULT_COMPRESSION_NAME,
                "img_start_offset": gui_params.img_start_offset or 0,
                "img_end_offset": gui_params.img_end_offset or 0,
                "img_width": gui_params.img_width or 1,
                "img_height": gui_params.img_height or 1,
            },
            "palette": {
                "palette_format": gui_params.palette_format or DEFAULT_PALETTE_FORMAT_NAME,
                "palette_offset": gui_params.palette_offset or 0,
                "palette_scale_value": gui_params.palette_scale_value or 1,
                "palette_endianess": gui_params.palette_endianess or DEFAULT_ENDIANESS_NAME,
                "palette_ps2_swizzle_flag": gui_params.palette_ps2_swizzle_flag
                if gui_params.palette_ps2_swizzle_flag is not None
                else False,
            },
        }

    def _validate_preset_dict(self, data: dict) -> PresetValidationResult:
        """Validate a raw JSON dict against the preset schema."""
        errors: List[PresetValidationError] = []
        warnings: List[str] = []
        resolved: dict = {"preset_version": PRESET_VERSION, "image": {}, "palette": {}}

        # ── Step 1: Structure checks ──
        if not isinstance(data, dict):
            errors.append(PresetValidationError("root", "Preset data must be a JSON object", type(data).__name__))
            return PresetValidationResult(is_valid=False, errors=errors)

        version = data.get("preset_version")
        if version is None:
            errors.append(PresetValidationError("preset_version", "Missing required field", None))
        elif not isinstance(version, int) or version != PRESET_VERSION:
            errors.append(
                PresetValidationError("preset_version", f"Must be {PRESET_VERSION}", version)
            )

        image_data = data.get("image")
        if image_data is None:
            errors.append(PresetValidationError("image", "Missing required section", None))
            return PresetValidationResult(is_valid=False, errors=errors)
        if not isinstance(image_data, dict):
            errors.append(PresetValidationError("image", "Must be a JSON object", type(image_data).__name__))
            return PresetValidationResult(is_valid=False, errors=errors)

        palette_data = data.get("palette")
        if palette_data is not None and not isinstance(palette_data, dict):
            errors.append(PresetValidationError("palette", "Must be a JSON object", type(palette_data).__name__))
            return PresetValidationResult(is_valid=False, errors=errors)
        if palette_data is None:
            palette_data = {}
            warnings.append("Missing 'palette' section, using defaults for all palette fields.")

        # ── Step 2: Required image fields ──
        self._validate_str_field(
            image_data, "pixel_format", PIXEL_FORMATS_NAMES, DEFAULT_PIXEL_FORMAT_NAME,
            "image.pixel_format", resolved["image"], errors, warnings,
        )
        self._validate_str_field(
            image_data, "endianess_type", ENDIANESS_TYPES_NAMES, DEFAULT_ENDIANESS_NAME,
            "image.endianess_type", resolved["image"], errors, warnings,
        )
        self._validate_str_field(
            image_data, "swizzling_type", SWIZZLING_TYPES_NAMES, DEFAULT_SWIZZLING_NAME,
            "image.swizzling_type", resolved["image"], errors, warnings,
        )
        self._validate_str_field(
            image_data, "compression_type", COMPRESSION_TYPES_NAMES, DEFAULT_COMPRESSION_NAME,
            "image.compression_type", resolved["image"], errors, warnings,
        )
        self._validate_int_field(
            image_data, "img_start_offset", 0, None, 0,
            "image.img_start_offset", resolved["image"], errors, warnings,
        )
        self._validate_int_field(
            image_data, "img_end_offset", 0, None, 0,
            "image.img_end_offset", resolved["image"], errors, warnings,
        )
        self._validate_int_field(
            image_data, "img_width", 1, None, 1,
            "image.img_width", resolved["image"], errors, warnings,
        )
        self._validate_int_field(
            image_data, "img_height", 1, None, 1,
            "image.img_height", resolved["image"], errors, warnings,
        )

        # ── Step 3: Optional palette fields ──
        self._validate_str_field(
            palette_data, "palette_format", PALETTE_FORMATS_NAMES, DEFAULT_PALETTE_FORMAT_NAME,
            "palette.palette_format", resolved["palette"], errors, warnings,
        )
        self._validate_int_field(
            palette_data, "palette_offset", 0, None, 0,
            "palette.palette_offset", resolved["palette"], errors, warnings,
        )
        valid_scale_values = [s.scale_value for s in SUPPORTED_PALETTE_SCALE_TYPES]
        self._validate_int_field(
            palette_data, "palette_scale_value", 1, valid_scale_values, 1,
            "palette.palette_scale_value", resolved["palette"], errors, warnings,
        )
        self._validate_str_field(
            palette_data, "palette_endianess", ENDIANESS_TYPES_NAMES, DEFAULT_ENDIANESS_NAME,
            "palette.palette_endianess", resolved["palette"], errors, warnings,
        )
        self._validate_bool_field(
            palette_data, "palette_ps2_swizzle_flag", False,
            "palette.palette_ps2_swizzle_flag", resolved["palette"], errors, warnings,
        )

        # ── Step 4: Cross-field checks ──
        start_offset = resolved["image"].get("img_start_offset", 0)
        end_offset = resolved["image"].get("img_end_offset", 0)
        if end_offset < start_offset and start_offset > 0:
            warnings.append(
                f"image.img_end_offset ({end_offset}) < image.img_start_offset ({start_offset})"
            )

        is_valid = len(errors) == 0
        return PresetValidationResult(
            is_valid=is_valid,
            errors=errors,
            warnings=warnings,
            preset_data=resolved if is_valid else None,
        )

    @staticmethod
    def _validate_str_field(
        data: dict,
        key: str,
        valid_values: list,
        default: str,
        field_path: str,
        resolved: dict,
        errors: list,
        warnings: list,
    ):
        value = data.get(key)
        if value is None:
            resolved[key] = default
            warnings.append(f"Missing field '{field_path}', using default '{default}'.")
        elif not isinstance(value, str):
            errors.append(PresetValidationError(field_path, f"Must be a string, got {type(value).__name__}", value))
        elif value not in valid_values:
            errors.append(
                PresetValidationError(field_path, f"Value not in supported options", value)
            )
        else:
            resolved[key] = value

    @staticmethod
    def _validate_int_field(
        data: dict,
        key: str,
        min_value: int,
        valid_values: Optional[list],
        default: int,
        field_path: str,
        resolved: dict,
        errors: list,
        warnings: list,
    ):
        value = data.get(key)
        if value is None:
            resolved[key] = default
            warnings.append(f"Missing field '{field_path}', using default {default}.")
        elif isinstance(value, bool) or not isinstance(value, int):
            errors.append(
                PresetValidationError(field_path, f"Must be an integer, got {type(value).__name__}", value)
            )
        elif value < min_value:
            errors.append(
                PresetValidationError(field_path, f"Must be >= {min_value}", value)
            )
        elif valid_values is not None and value not in valid_values:
            errors.append(
                PresetValidationError(field_path, f"Value not in allowed set {valid_values}", value)
            )
        else:
            resolved[key] = value

    @staticmethod
    def _validate_bool_field(
        data: dict,
        key: str,
        default: bool,
        field_path: str,
        resolved: dict,
        errors: list,
        warnings: list,
    ):
        value = data.get(key)
        if value is None:
            resolved[key] = default
            warnings.append(f"Missing field '{field_path}', using default {default}.")
        elif not isinstance(value, bool):
            errors.append(
                PresetValidationError(field_path, f"Must be a boolean, got {type(value).__name__}", value)
            )
        else:
            resolved[key] = value
