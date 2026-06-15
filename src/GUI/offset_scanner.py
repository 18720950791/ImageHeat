"""
Copyright © 2024-2025  Bartłomiej Duda
License: GPL-3.0 License

Offset scanner engine for ImageHeat.
Scans a range of byte offsets, decodes each candidate using the current
texture parameters, and produces thumbnails for visual selection.
"""

import copy
import threading
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from PIL import Image
from reversebox.common.logger import get_logger
from reversebox.image.common import (
    convert_bpp_to_bytes_per_pixel,
    get_bpp_for_image_format,
)
from reversebox.image.image_formats import ImageFormats

from src.GUI.gui_params import GuiParams
from src.Image.heatimage import HeatImage

logger = get_logger(__name__)

THUMBNAIL_SIZE = 64


@dataclass
class ScanCandidate:
    """Represents one candidate offset in the scan results."""

    offset: int
    thumbnail: Optional[Image.Image] = None
    is_valid: bool = False
    error_msg: str = ""


@dataclass
class ScanConfig:
    """Configuration for an offset scan."""

    start_offset: int = 0
    end_offset: int = 0
    step: int = 1
    alignment: int = 0  # 0 = no alignment
    max_results: int = 50


@dataclass
class ScanSummary:
    """Summary statistics after a scan completes."""

    total_scanned: int = 0
    valid_count: int = 0
    skipped_count: int = 0
    cancelled: bool = False


class OffsetScanner:
    """
    Scans a range of byte offsets within loaded binary data,
    decoding each candidate with the current texture parameters
    and generating thumbnail images.
    """

    def __init__(
        self,
        loaded_image_data: bytes,
        base_gui_params: GuiParams,
        scan_config: ScanConfig,
    ):
        self.loaded_image_data = loaded_image_data
        self.base_gui_params = base_gui_params
        self.scan_config = scan_config
        self.summary = ScanSummary()

    def _calculate_data_size(self) -> int:
        """Calculate the expected encoded data size for the current image parameters."""
        try:
            image_format = ImageFormats[self.base_gui_params.pixel_format]
            bpp = get_bpp_for_image_format(image_format)
            bytes_per_pixel = convert_bpp_to_bytes_per_pixel(bpp)
            return self.base_gui_params.img_width * self.base_gui_params.img_height * bytes_per_pixel
        except Exception as error:
            logger.warning(f"Could not calculate data size: {error}")
            # fallback: use current end - start offset
            return max(
                0,
                self.base_gui_params.img_end_offset - self.base_gui_params.img_start_offset,
            )

    def _align_offset(self, offset: int) -> int:
        """Align an offset to the configured alignment boundary."""
        alignment = self.scan_config.alignment
        if alignment <= 0:
            return offset
        return (offset // alignment) * alignment

    def _decode_candidate(self, offset: int, data_size: int) -> ScanCandidate:
        """
        Attempt to decode a single candidate at the given offset.
        Returns a ScanCandidate with thumbnail on success, or error info on failure.
        """
        candidate = ScanCandidate(offset=offset)

        # bounds check
        if offset < 0 or offset + data_size > len(self.loaded_image_data):
            candidate.error_msg = "Out of bounds"
            return candidate

        # create a fresh GuiParams copy for this candidate
        candidate_params = copy.deepcopy(self.base_gui_params)
        candidate_params.img_start_offset = offset
        candidate_params.img_end_offset = offset + data_size

        try:
            heat_img = HeatImage(candidate_params)
            # manually set loaded data so _image_read slices from it
            heat_img.loaded_image_data = self.loaded_image_data
            heat_img.is_data_loaded_from_file = True
            heat_img.image_reload()

            if heat_img.is_preview_error or not heat_img.decoded_image_data:
                candidate.error_msg = "Decode error"
                return candidate

            # generate thumbnail from decoded RGBA data
            img_width = candidate_params.img_width
            img_height = candidate_params.img_height
            preview_data_size = img_width * img_height * 4

            if preview_data_size > len(heat_img.decoded_image_data):
                preview_data = heat_img.decoded_image_data
            else:
                preview_data = heat_img.decoded_image_data[:preview_data_size]

            pil_img = Image.frombuffer(
                "RGBA",
                (img_width, img_height),
                preview_data,
                "raw",
                "RGBA",
                0,
                1,
            )

            # resize to thumbnail
            pil_img = pil_img.resize((THUMBNAIL_SIZE, THUMBNAIL_SIZE), Image.LANCZOS)
            candidate.thumbnail = pil_img
            candidate.is_valid = True

        except Exception as error:
            candidate.error_msg = str(error)[:80]
            logger.debug(f"Candidate at offset {offset} failed: {error}")

        return candidate

    def scan(
        self,
        progress_callback: Optional[Callable[[int, int, ScanCandidate], None]] = None,
        cancel_event: Optional[threading.Event] = None,
    ) -> List[ScanCandidate]:
        """
        Execute the offset scan.

        Args:
            progress_callback: Called with (current_index, total_count, candidate)
                               after each candidate is processed.
            cancel_event: If set, the scan stops at the next iteration.

        Returns:
            List of valid ScanCandidate objects (up to max_results).
        """
        config = self.scan_config
        self.summary = ScanSummary()

        if config.step <= 0:
            config.step = 1

        data_size = self._calculate_data_size()
        if data_size <= 0:
            logger.warning("Data size is 0, cannot scan")
            return []

        # build list of candidate offsets
        offsets: List[int] = []
        current = config.start_offset
        while current <= config.end_offset:
            aligned = self._align_offset(current)
            if aligned not in offsets:
                offsets.append(aligned)
            current += config.step

        total = len(offsets)
        results: List[ScanCandidate] = []
        valid_count = 0

        logger.info(f"Starting offset scan: {total} candidates, range "
                     f"[{config.start_offset}..{config.end_offset}], step={config.step}")

        for i, offset in enumerate(offsets):
            # check cancellation
            if cancel_event and cancel_event.is_set():
                self.summary.cancelled = True
                logger.info("Offset scan cancelled by user")
                break

            # check max results
            if valid_count >= config.max_results:
                logger.info(f"Max results ({config.max_results}) reached")
                break

            candidate = self._decode_candidate(offset, data_size)
            self.summary.total_scanned += 1

            if candidate.is_valid:
                valid_count += 1
                self.summary.valid_count += 1
                results.append(candidate)
            else:
                self.summary.skipped_count += 1

            # report progress
            if progress_callback:
                try:
                    progress_callback(i + 1, total, candidate)
                except Exception:
                    pass

        logger.info(
            f"Scan finished: scanned={self.summary.total_scanned}, "
            f"valid={self.summary.valid_count}, skipped={self.summary.skipped_count}, "
            f"cancelled={self.summary.cancelled}"
        )

        return results
