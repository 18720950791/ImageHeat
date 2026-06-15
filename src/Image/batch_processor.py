"""
Copyright © 2024-2026  Bartłomiej Duda
License: GPL-3.0 License
"""

import copy
import math
import os
import threading
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from PIL import Image
from PIL.Image import Transpose
from reversebox.common.logger import get_logger
from reversebox.image.pillow_wrapper import PillowWrapper

from src.GUI.gui_params import GuiParams
from src.Image.constants import get_rotate_id
from src.Image.heatimage import HeatImage

logger = get_logger(__name__)

MAX_END_OFFSET: int = 5242880  # 5 MB


@dataclass
class BatchFileResult:
    file_path: str
    status: str  # "success", "failed", "cancelled"
    message: str = ""
    output_path: Optional[str] = None


class BatchProcessor:
    """
    Processes multiple image files in a background thread,
    decoding each with the same parameters and exporting to the chosen format.
    """

    def __init__(
        self,
        source_gui_params: GuiParams,
        file_paths: List[str],
        output_dir: str,
        output_format: str,
        naming_pattern: str,
        custom_prefix: str,
        progress_callback: Callable[[int, int, BatchFileResult], None],
        completion_callback: Callable[[List[BatchFileResult]], None],
    ):
        self.source_gui_params = source_gui_params
        self.file_paths = file_paths
        self.output_dir = output_dir
        self.output_format = output_format  # "dds", "png", or "bmp"
        self.naming_pattern = naming_pattern  # "original", "numbered", "prefix"
        self.custom_prefix = custom_prefix
        self.progress_callback = progress_callback
        self.completion_callback = completion_callback

        self._cancel_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """Launch the batch processing background thread."""
        self._cancel_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def cancel(self) -> None:
        """Signal the background thread to stop after the current file."""
        self._cancel_event.set()

    @property
    def is_cancelled(self) -> bool:
        return self._cancel_event.is_set()

    def _calculate_dimensions(self, file_size: int) -> tuple:
        """Auto-calculate image dimensions as sqrt(file_size/4), same as single-file open."""
        number_of_pixels = file_size // 4
        pixel_sqrt = int(math.floor(math.sqrt(number_of_pixels)))
        return pixel_sqrt, pixel_sqrt

    def _calculate_end_offset(self, file_size: int) -> int:
        """Auto-calculate end offset, capped at 5MB, same as single-file open."""
        if file_size > MAX_END_OFFSET:
            return MAX_END_OFFSET
        return file_size

    def _build_output_filename(self, original_path: str, index: int) -> str:
        """Generate the output filename based on the naming pattern."""
        base_name = os.path.splitext(os.path.basename(original_path))[0]
        ext = self.output_format.lower()

        if self.naming_pattern == "numbered":
            return f"{base_name}_{index:04d}.{ext}"
        elif self.naming_pattern == "prefix":
            prefix = self.custom_prefix if self.custom_prefix else "export"
            return f"{prefix}_{base_name}.{ext}"
        else:  # "original"
            return f"{base_name}.{ext}"

    def _process_single_file(self, file_path: str, index: int) -> BatchFileResult:
        """Decode and export a single file. Returns a BatchFileResult."""
        try:
            file_size = os.path.getsize(file_path)
            img_width, img_height = self._calculate_dimensions(file_size)
            end_offset = self._calculate_end_offset(file_size)

            # Deep copy gui params and override with this file's settings
            params = copy.deepcopy(self.source_gui_params)
            params.img_file_path = file_path
            params.img_file_name = os.path.basename(file_path)
            params.total_file_size = file_size
            params.img_width = img_width
            params.img_height = img_height
            params.img_start_offset = 0
            params.img_end_offset = end_offset

            # Ensure palette params are set for non-paletted formats
            if params.palette_format is None:
                params.palette_format = "RGB565"
            if params.palette_scale_value is None:
                params.palette_scale_value = 1
            if params.palette_endianess is None:
                params.palette_endianess = "Little Endian"
            if params.palette_loadfrom_value is None:
                params.palette_loadfrom_value = 1

            # Decode
            heat_image = HeatImage(params)
            heat_image.image_reload()

            if heat_image.decoded_image_data is None or len(heat_image.decoded_image_data) == 0:
                return BatchFileResult(
                    file_path=file_path,
                    status="failed",
                    message="Decoded image data is empty",
                )

            if heat_image.is_preview_error:
                return BatchFileResult(
                    file_path=file_path,
                    status="failed",
                    message="Decode error (unsupported format or corrupt data)",
                )

            # Create PIL image from decoded raw RGBA data
            export_pil_img = Image.frombuffer(
                "RGBA",
                (img_width, img_height),
                heat_image.decoded_image_data,
                "raw",
                "RGBA",
                0,
                1,
            )

            # Apply post-processing transformations
            if params.vertical_flip_flag:
                export_pil_img = export_pil_img.transpose(Transpose.FLIP_TOP_BOTTOM)
            if params.horizontal_flip_flag:
                export_pil_img = export_pil_img.transpose(Transpose.FLIP_LEFT_RIGHT)

            rotate_id = get_rotate_id(params.rotate_name)
            if rotate_id == "rotate_90_left":
                export_pil_img = export_pil_img.transpose(Transpose.ROTATE_90)
            elif rotate_id == "rotate_90_right":
                export_pil_img = export_pil_img.transpose(Transpose.ROTATE_270)
            elif rotate_id == "rotate_180":
                export_pil_img = export_pil_img.transpose(Transpose.ROTATE_180)

            # Export
            output_filename = self._build_output_filename(file_path, index)
            output_path = os.path.join(self.output_dir, output_filename)

            pillow_wrapper = PillowWrapper()
            out_data = pillow_wrapper.get_pil_image_file_data_for_export2(
                export_pil_img, pillow_format=self.output_format.upper()
            )

            if not out_data:
                return BatchFileResult(
                    file_path=file_path,
                    status="failed",
                    message="Failed to encode output image data",
                )

            with open(output_path, "wb") as out_file:
                out_file.write(out_data)

            return BatchFileResult(
                file_path=file_path,
                status="success",
                message=f"Exported to {output_filename}",
                output_path=output_path,
            )

        except Exception as e:
            logger.error(f"Batch processing failed for {file_path}: {e}")
            return BatchFileResult(
                file_path=file_path,
                status="failed",
                message=str(e),
            )

    def _run(self) -> None:
        """Main batch processing loop. Runs on a background thread."""
        results: List[BatchFileResult] = []
        total = len(self.file_paths)

        for i, file_path in enumerate(self.file_paths):
            if self._cancel_event.is_set():
                # Mark remaining files as cancelled
                for remaining_path in self.file_paths[i:]:
                    result = BatchFileResult(
                        file_path=remaining_path,
                        status="cancelled",
                        message="Cancelled by user",
                    )
                    results.append(result)
                    self.progress_callback(len(results), total, result)
                break

            result = self._process_single_file(file_path, i)
            results.append(result)
            self.progress_callback(i + 1, total, result)

        self.completion_callback(results)
