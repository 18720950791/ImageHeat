# ImageHeat Pixel Probe Enhancement Plan

## Context

ImageHeat is a Python/Tkinter texture viewer with a hover-based pixel info display (coordinates, offset, RGBA). Users need a way to **pin multiple pixel probes** on the preview for comparison and export. The coordinate math must correctly reverse all transformations (zoom, flip, rotation), and stale probes must be cleaned up on file switch or re-decode.

## Architecture Overview

All changes are confined to **one file**: `src/GUI/gui_main.py` (~2010 lines), which contains the main GUI class `ImageHeatGUI`.

## Implementation Steps

### 1. Extract coordinate transform into reusable method

Extract the inline coordinate math from `_mouse_motion_handler` (lines 1946-1971) into a new helper:

```python
def _canvas_to_image_coords(self, canvas_x, canvas_y) -> tuple[int, int] | None:
    """Convert canvas coords to original image pixel coords, reversing zoom/flip/rotation.
    Returns None if coords are outside image bounds."""
```

Both `_mouse_motion_handler` and the new click handler will call this.

### 2. Add PixelProbe dataclass and probe state

Add a `PixelProbe` dataclass near the top of the file (after imports):

```python
@dataclass
class PixelProbe:
    id: int                    # unique probe ID (auto-incrementing)
    pixel_x: int               # original image X
    pixel_y: int               # original image Y
    offset: int                # byte offset in encoded data
    encoded_hex: str           # hex of encoded pixel bytes
    rgba: tuple[int, int, int, int]  # decoded RGBA values
    canvas_marker_id: int      # Tk canvas item ID for the marker
```

Add instance variables in `__init__`:
- `self.pixel_probes: list[PixelProbe]` — all active probes
- `self._probe_id_counter: int` — auto-increment counter
- `self._probe_panel_visible: bool` — panel toggle state

### 3. Add click handler to pin probes

Bind `<Button-1>` on `self.preview_instance` (line ~987):

```python
self.preview_instance.bind('<Button-1>', self._canvas_click_handler)
```

`_canvas_click_handler`:
1. Convert event coords → canvas coords → image coords (using `_canvas_to_image_coords`)
2. If already a probe at same `(pixel_x, pixel_y)`, remove it (toggle behavior)
3. Otherwise, compute offset + RGBA from `self.opened_image.encoded_image_data` / `decoded_image_data`
4. Create `PixelProbe`, draw marker on canvas, add to list, update panel

### 4. Draw probe markers on canvas

Each probe is drawn as a small **crosshair + colored circle** at the probe's canvas-space position:
- A 5px radius circle with the pixel's RGBA color as fill and a contrasting outline
- A small label showing the probe ID number

The canvas-space position is computed from image coords by applying transformations in the **forward** direction (the reverse of `_canvas_to_image_coords`). Add:

```python
def _image_to_canvas_coords(self, pixel_x, pixel_y) -> tuple[int, int]:
    """Convert original image pixel coords to canvas coords, applying zoom/flip/rotation."""
```

### 5. Add Pixel Probes panel (UI)

Add a new `LabelFrame` below the existing Controls box (y=365+215=580, or adjust existing positions):

**Panel contents** (using a `ttk.Treeview` for the table):
- Treeview columns: `#`, `X`, `Y`, `Offset`, `Encoded`, `R`, `G`, `B`, `A`
- Each row represents one probe
- Right-click context menu on rows: "Copy X", "Copy Y", "Copy Offset", "Copy Encoded", "Copy RGBA", "Copy Row", "Delete Probe"
- Bottom toolbar with two buttons:
  - **"Copy All"** — copies all probe data as tab-separated text to clipboard
  - **"Export CSV"** — opens `filedialog.asksaveasfilename` and writes all probes to CSV

### 6. Re-draw probes after canvas update

In `_update_canvas_on_main_thread` (line 1887), after drawing the image, call:

```python
self._redraw_all_probes()
```

This re-computes canvas positions for each probe using `_image_to_canvas_coords` and re-creates the canvas markers. Probes whose coords are now out-of-bounds are removed.

### 7. Probe lifecycle management

- **File open** (`open_image_file`, line 1472): Call `self._clear_all_probes()` before creating new `HeatImage`
- **Re-decode** (`gui_reload_image_on_gui_element_change`, line 1455): Call `self._validate_probes()` after re-decode to remove probes outside new image bounds
- **`_clear_all_probes()`**: Delete all canvas markers, clear list, clear treeview
- **`_validate_probes()`**: Remove probes where `pixel_x > img_width` or `pixel_y > img_height`, update panel

## Files Modified

| File | Changes |
|------|---------|
| `src/GUI/gui_main.py` | All changes: dataclass, click handler, coord helpers, probe panel UI, lifecycle management, CSV export |

## Verification

1. Open a texture file, zoom in, click multiple pixels → markers appear with correct coordinates
2. Change zoom level → markers reposition correctly on the preview
3. Toggle vertical/horizontal flip → markers move to correct flipped positions
4. Apply rotation (90/180/270) → markers rotate correctly
5. Right-click a probe row → copy individual fields to clipboard
6. Click "Export CSV" → CSV file with all probe data is saved
7. Open a different file → all probes are cleared
8. Change image dimensions (width/height spinbox) → out-of-bounds probes are removed
9. Click on same pixel twice → probe toggles (add/remove)
10. Compressed format selected → offset and encoded show "n/a" for probes
