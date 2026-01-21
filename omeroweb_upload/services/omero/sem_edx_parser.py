"""
SEM EDX EMSA/MAS format parser and OMERO Table creator.

This module parses SEM EDX spectrum files in EMSA/MAS format and creates
one OMERO Table containing the spectrum X,Y data.
"""
import logging
import re
import time
from bisect import bisect_left
from pathlib import Path
from typing import Dict, List, Tuple, Any, Optional

import matplotlib

matplotlib.use("Agg")

from matplotlib import pyplot as plt
from matplotlib.patches import FancyBboxPatch
import numpy as np

logger = logging.getLogger(__name__)


def parse_emsa_file(txt_path: Path) -> Dict[str, Any]:
    """
    Parse an EMSA/MAS format SEM EDX spectrum file.
    
    Args:
        txt_path: Path to the .txt file
        
    Returns:
        Dictionary containing:
        - title: str - The spectrum title from #TITLE
        - metadata: dict - All #KEY: value pairs
        - elements: list - Parsed ##OXINSTLABEL entries
        - spectrum: list - (x, y) coordinate pairs
    """
    try:
        content = txt_path.read_text(encoding='utf-8', errors='ignore')
    except Exception as exc:
        logger.error("Failed to read EMSA file %s: %s", txt_path, exc)
        return {
            'title': '',
            'metadata': {},
            'elements': [],
            'spectrum': []
        }
    
    lines = content.split('\n')
    title = ''
    metadata = {}
    elements = []
    spectrum = []
    in_spectrum = False
    
    for line in lines:
        line = line.strip()
        if not line:
            continue

        normalized = line.lstrip('#').strip()
        normalized_upper = normalized.upper()
        
        # Check if we've entered the spectrum data section
        if normalized_upper.startswith('SPECTRUM'):
            in_spectrum = True
            # Also capture this as metadata
            parts = line.split(':', 1)
            if len(parts) == 2:
                key = parts[0].replace('#', '').strip()
                value = parts[1].strip()
                metadata[key] = value
            continue
        
        # Check for end of data
        if normalized_upper.startswith('ENDOFDATA'):
            break
        
        # If we're in the spectrum section, parse X,Y pairs
        if in_spectrum:
            if line.startswith('#'):
                continue
            # Parse X, Y pairs (format: "0.01000, 1057.0" or "0.01000 1057.0")
            parts = [p for p in re.split(r'[,\s]+', line) if p]
            if len(parts) >= 2:
                for idx in range(0, len(parts) - 1, 2):
                    try:
                        x = float(parts[idx])
                        y = float(parts[idx + 1])
                        spectrum.append((x, y))
                    except ValueError:
                        continue
            continue
        
        # Parse metadata lines (format: "#KEY : value")
        if line.startswith('#') and ':' in line:
            # Special handling for ##OXINSTLABEL
            if line.startswith('##OXINSTLABEL'):
                # Format: "##OXINSTLABEL: Z, energy, symbol"
                # Example: "##OXINSTLABEL: 29, 8.048, Cu"
                parts = line.split(':', 1)
                if len(parts) == 2:
                    label_data = parts[1].strip()
                    label_parts = [p.strip() for p in label_data.split(',')]
                    if len(label_parts) >= 3:
                        try:
                            atomic_number = int(label_parts[0])
                            energy = float(label_parts[1])
                            symbol = label_parts[2]
                            elements.append({
                                'atomic_number': atomic_number,
                                'energy_kev': energy,
                                'symbol': symbol
                            })
                        except (ValueError, IndexError):
                            continue
            else:
                # Regular metadata
                parts = line.split(':', 1)
                if len(parts) == 2:
                    key = parts[0].replace('#', '').strip()
                    value = parts[1].strip()
                    
                    # Store the title separately
                    if key == 'TITLE':
                        title = value
                    
                    # Handle duplicate keys by appending numbers
                    original_key = key
                    counter = 1
                    while key in metadata:
                        key = f"{original_key}_{counter}"
                        counter += 1
                    
                    metadata[key] = value
    
    return {
        'title': title,
        'metadata': metadata,
        'elements': elements,
        'spectrum': spectrum
    }


def _nearest_spectrum_point(
    spectrum: List[Tuple[float, float]],
    energy_kev: float,
) -> Optional[Tuple[float, float]]:
    if not spectrum:
        return None
    energies = [point[0] for point in spectrum]
    idx = bisect_left(energies, energy_kev)
    if idx == 0:
        return spectrum[0]
    if idx >= len(spectrum):
        return spectrum[-1]
    before = spectrum[idx - 1]
    after = spectrum[idx]
    if abs(before[0] - energy_kev) <= abs(after[0] - energy_kev):
        return before
    return after


class BBox:
    """Simple bounding box class for collision detection."""
    def __init__(self, x0, y0, x1, y1):
        self.x0 = x0
        self.y0 = y0
        self.x1 = x1
        self.y1 = y1
        
    @property
    def width(self):
        return self.x1 - self.x0
    
    @property
    def height(self):
        return self.y1 - self.y0
    
    @property
    def center_x(self):
        return (self.x0 + self.x1) / 2
    
    @property
    def center_y(self):
        return (self.y0 + self.y1) / 2
    
    def overlaps(self, other):
        """Check if this bbox overlaps with another."""
        return not (self.x1 < other.x0 or self.x0 > other.x1 or 
                   self.y1 < other.y0 or self.y0 > other.y1)
    
    def translate(self, dx, dy):
        """Return a new bbox translated by dx, dy."""
        return BBox(self.x0 + dx, self.y0 + dy, self.x1 + dx, self.y1 + dy)


# COMPLETE REWRITE - Research-based greedy algorithm
class BBox:
    def __init__(self, x0, y0, x1, y1):
        self.x0 = x0
        self.y0 = y0
        self.x1 = x1
        self.y1 = y1
    
    def overlaps(self, other):
        return not (self.x1 <= other.x0 or self.x0 >= other.x1 or 
                   self.y1 <= other.y0 or self.y0 >= other.y1)


def lines_cross(x1, y1, x2, y2, x3, y3, x4, y4):
    """Check if line (x1,y1)-(x2,y2) crosses line (x3,y3)-(x4,y4)"""
    def ccw(ax, ay, bx, by, cx, cy):
        return (cy - ay) * (bx - ax) > (by - ay) * (cx - ax)
    
    return (ccw(x1, y1, x3, y3, x4, y4) != ccw(x2, y2, x3, y3, x4, y4) and
            ccw(x1, y1, x2, y2, x3, y3) != ccw(x1, y1, x2, y2, x4, y4))


def smart_label_placement_v2(
    labels_data: List[Tuple[float, float, str]],
    axes_bbox: BBox,
    fig,
    ax,
    renderer,
    fixed_offset_pixels: float = 30,
) -> List[Tuple[float, float, str, float, float, List[float]]]:
    """
    Research-based algorithm:
    1. Sort by Y coordinate (tallest peaks first)
    2. Place greedily without line crossings
    3. Hard bounds enforcement
    """
    if not labels_data:
        return []
    
    # Merge duplicates
    from collections import defaultdict
    symbol_groups = defaultdict(list)
    for energy, spectrum_y, symbol in labels_data:
        symbol_groups[symbol].append((energy, spectrum_y))
    
    merged_labels = []
    for symbol, peaks in symbol_groups.items():
        peaks.sort(key=lambda x: x[0])
        groups = []
        current_group = [peaks[0]]
        
        for i in range(1, len(peaks)):
            if peaks[i][0] - current_group[-1][0] < 0.5:
                current_group.append(peaks[i])
            else:
                groups.append(current_group)
                current_group = [peaks[i]]
        groups.append(current_group)
        
        for group in groups:
            energies = [p[0] for p in group]
            center_energy = sum(energies) / len(energies)
            max_y = max(p[1] for p in group)
            merged_labels.append((center_energy, max_y, symbol, energies))
    
    # KEY: Sort by Y coordinate (tallest first)
    merged_labels.sort(key=lambda x: x[1], reverse=True)
    
    # Measure labels
    label_specs = []
    for center_energy, spectrum_y, symbol, peak_energies in merged_labels:
        x_peak_disp, y_peak_disp = ax.transData.transform((center_energy, spectrum_y))
        
        temp = ax.text(0, 0, symbol, fontsize=7.5,
                      bbox=dict(boxstyle='round,pad=0.35', facecolor='#b8f0b0'),
                      ha='center', va='center', alpha=0)
        fig.canvas.draw()
        bbox = temp.get_window_extent(renderer=renderer)
        temp.remove()
        
        label_specs.append({
            'energy': center_energy,
            'spectrum_y': spectrum_y,
            'symbol': symbol,
            'peak_energies': peak_energies,
            'x_peak': x_peak_disp,
            'y_peak': y_peak_disp,
            'width': bbox.width + 8,
            'height': bbox.height + 8
        })
    
    # Greedy placement
    placed = []
    MIN_CLEARANCE = 25  # Minimum pixels above peak
    MARGIN = 10
    
    for spec in label_specs:
        x_peak = spec['x_peak']
        y_peak = spec['y_peak']
        w = spec['width']
        h = spec['height']
        
        # Hard bounds
        min_x = axes_bbox.x0 + MARGIN + w/2
        max_x = axes_bbox.x1 - MARGIN - w/2
        min_y = y_peak + MIN_CLEARANCE + h/2
        max_y = axes_bbox.y1 - MARGIN - h/2
        
        # Ensure bounds are valid
        if min_y > max_y or min_x > max_x:
            print(f"WARNING: {spec['symbol']} cannot fit - bounds too tight")
            continue
        
        # Try positions: start at fixed offset, spiral out
        best_pos = None
        
        for y_try in range(int(min_y), int(max_y) + 1, 5):
            for x_offset in [0, -15, 15, -30, 30, -45, 45]:
                x_try = x_peak + x_offset
                
                # Check bounds
                if x_try < min_x or x_try > max_x:
                    continue
                if y_try < min_y or y_try > max_y:
                    continue
                
                # Check bbox overlap
                test_bbox = BBox(x_try - w/2, y_try - h/2, x_try + w/2, y_try + h/2)
                
                has_overlap = False
                for p in placed:
                    if test_bbox.overlaps(p['bbox']):
                        has_overlap = True
                        break
                
                if has_overlap:
                    continue
                
                # Check line crossing
                has_crossing = False
                for peak_e in spec['peak_energies']:
                    px, py = ax.transData.transform((peak_e, spec['spectrum_y']))
                    
                    for p in placed:
                        for prev_peak_e in p['peak_energies']:
                            ppx, ppy = ax.transData.transform((prev_peak_e, p['spectrum_y']))
                            
                            if lines_cross(px, py, x_try, y_try, 
                                         ppx, ppy, p['x'], p['y']):
                                has_crossing = True
                                break
                        if has_crossing:
                            break
                    if has_crossing:
                        break
                
                if not has_crossing:
                    best_pos = (x_try, y_try)
                    break
            
            if best_pos:
                break
        
        # If no position found, force placement at peak
        if not best_pos:
            x_final = max(min_x, min(max_x, x_peak))
            y_final = max(min_y, min(max_y, y_peak + fixed_offset_pixels))
            print(f"WARNING: {spec['symbol']} forced placement (no valid position)")
        else:
            x_final, y_final = best_pos
        
        final_bbox = BBox(x_final - w/2, y_final - h/2, x_final + w/2, y_final + h/2)
        
        placed.append({
            'energy': spec['energy'],
            'spectrum_y': spec['spectrum_y'],
            'symbol': spec['symbol'],
            'peak_energies': spec['peak_energies'],
            'x': x_final,
            'y': y_final,
            'bbox': final_bbox
        })
    
    # Verify no overlaps
    for i, p1 in enumerate(placed):
        for j, p2 in enumerate(placed):
            if i >= j:
                continue
            if p1['bbox'].overlaps(p2['bbox']):
                print(f"ERROR: Overlap {p1['symbol']} vs {p2['symbol']}")
    
    # Return
    return [(p['energy'], p['spectrum_y'], p['symbol'], p['x'], p['y'], p['peak_energies']) 
            for p in placed]



def create_edx_spectrum_plot(
    txt_path: Path,
    output_path: Optional[Path] = None,
) -> Optional[Path]:
    parsed = parse_emsa_file(txt_path)
    spectrum = parsed.get("spectrum") or []
    if not spectrum:
        logger.warning("No spectrum data available to plot for %s", txt_path.name)
        return None

    if output_path is None:
        output_path = txt_path.with_name(f"{txt_path.stem}_edx.png")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    energies = [point[0] for point in spectrum]
    counts = [point[1] for point in spectrum]
    x_min = min(energies)
    x_max = max(energies)
    y_max = max(counts) if counts else 1.0
    y_max = y_max if y_max > 0 else 1.0

    # Create figure with proper margins for axis labels
    fig, ax = plt.subplots(figsize=(8.5, 5.0), dpi=150)
    fig.patch.set_facecolor("#1f4d7a")
    ax.set_facecolor("#1f4d7a")

    spectrum_color = "#ffe600"
    label_text_color = "#0b3d1a"
    label_fill_color = "#b8f0b0"
    label_edge_color = "#ffffff"
    label_line_color = "#ffffff"

    # Plot spectrum
    ax.plot(energies, counts, color=spectrum_color, linewidth=1.4)
    ax.fill_between(energies, counts, 0, color=spectrum_color, alpha=0.38)
    ax.set_xlim(x_min, x_max)
    ax.set_ylim(0, y_max * 1.05)

    # Set axis labels with proper spacing
    ax.set_xlabel("keV", color="white", fontsize=10, labelpad=2)
    ax.set_ylabel("cps/eV", color="white", fontsize=10, labelpad=2)
    ax.tick_params(colors="white", labelsize=8, pad=2)
    
    for spine in ax.spines.values():
        spine.set_color("white")

    # Collect element labels
    element_labels = []
    for element in parsed.get("elements", []):
        try:
            energy = float(element.get("energy_kev"))
        except (TypeError, ValueError):
            continue
        symbol = element.get("symbol") or ""
        if not symbol:
            continue
        if energy < x_min or energy > x_max:
            continue
        element_labels.append((energy, symbol))

    # Prepare labels data with spectrum y positions
    labels_data = []
    for energy, symbol in element_labels:
        nearest = _nearest_spectrum_point(spectrum, energy)
        if nearest:
            _, spectrum_y = nearest
            labels_data.append((energy, spectrum_y, symbol))
    
    # Adjust subplot margins BEFORE calculating positions
    # Small margins to maximize plot area while ensuring axis labels are visible
    fig.subplots_adjust(left=0.08, right=0.98, top=0.97, bottom=0.10)
    
    # Initial rendering to get axes bbox
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    axes_bbox_raw = ax.get_window_extent(renderer=renderer)
    axes_bbox = BBox(axes_bbox_raw.x0, axes_bbox_raw.y0, axes_bbox_raw.x1, axes_bbox_raw.y1)
    
    # Compute smart label positions - EXACTLY 10 pixels from peak to bottom of box
    final_positions = smart_label_placement_v2(
        labels_data,
        axes_bbox,
        fig,
        ax,
        renderer,
        fixed_offset_pixels=25  # 25 pixels above peak
    )
    
    # Draw labels and connector lines with minimal crossing
    for center_energy, spectrum_y, symbol, label_x, label_y, peak_energies in final_positions:
        # Draw connector lines from EACH peak to the label
        for peak_energy in peak_energies:
            # Get the point on the spectrum at this peak
            nearest = _nearest_spectrum_point(spectrum, peak_energy)
            if nearest:
                peak_x, peak_y = nearest
                
                # Draw straight vertical line from peak to label
                annotation = ax.annotate(
                    '',  # No text on the line itself
                    xy=(peak_x, peak_y),
                    xytext=(label_x, label_y),
                    xycoords='data',
                    textcoords='figure pixels',
                    arrowprops=dict(
                        arrowstyle='-',
                        color=label_line_color,
                        linewidth=0.6,
                        alpha=0.8,
                    ),
                )
        
        # Draw the label box (once for all peaks)
        annotation = ax.annotate(
            symbol,
            xy=(center_energy, spectrum_y),
            xytext=(label_x, label_y),
            xycoords='data',
            textcoords='figure pixels',
            fontsize=7.5,
            color=label_text_color,
            bbox=dict(
                boxstyle='round,pad=0.35',
                facecolor=label_fill_color,
                edgecolor=label_edge_color,
                linewidth=0.8,
            ),
            ha='center',
            va='center',
        )
    
    # Save the figure
    fig.savefig(output_path, format="png", facecolor=fig.get_facecolor())
    plt.close(fig)

    logger.info("Created SEM EDX spectrum plot %s", output_path.name)
    return output_path


def build_spectrum_columns(
    image_id: int,
    spectrum: List[Tuple[float, float]],
) -> List[Any]:
    from omero.grid import DoubleColumn, LongColumn

    columns = [
        LongColumn('Image', '', []),
        DoubleColumn('Energy_keV', '', []),
        DoubleColumn('Counts', '', [])
    ]

    for x, y in spectrum:
        columns[0].values.append(image_id)
        columns[1].values.append(x)
        columns[2].values.append(y)

    return columns


def create_spectrum_table(
    conn,
    image_id: int,
    spectrum: List[Tuple[float, float]],
    txt_filename: str,
    columns: Optional[List[Any]] = None,
) -> Optional[int]:
    """
    Create an OMERO Table containing spectrum X,Y data.
    
    Args:
        conn: OMERO BlitzGateway connection
        image_id: ID of the image to attach the table to
        spectrum: List of (x, y) tuples
        txt_filename: Name of the source txt file (for table name)
        
    Returns:
        Table file annotation ID if successful, None otherwise
    """
    if not spectrum:
        logger.info("No spectrum data to create table for image %d", image_id)
        return None

    logger.info(
        "SEM EDX spectrum received for image %d: %d data points (from %s)",
        image_id,
        len(spectrum),
        txt_filename,
    )
    
    try:
        from omero.grid import DoubleColumn, LongColumn
        from omero.model import OriginalFileI
        from omero.rtypes import rstring
        
        if columns is None:
            columns = build_spectrum_columns(image_id, spectrum)
        
        # Create the table
        resources = conn.c.sf.sharedResources()
        repository_id = resources.repositories().descriptions[0].getId().getValue()
        
        # Table name is just the filename without .txt extension
        base_name = Path(txt_filename).stem
        table_name = f"{base_name}.h5"
        table = resources.newTable(repository_id, table_name)
        
        if table is None:
            logger.error("Failed to create spectrum table for image %d", image_id)
            return None
        
        try:
            logger.info(
                "Initializing OMERO table '%s' with %d rows (Energy_keV=%d, Counts=%d)",
                table_name,
                len(spectrum),
                len(columns[0].values),
                len(columns[1].values),
            )

            # IMPORTANT:
            # initialize() defines ONLY the schema; values are ignored.
            # addData() must receive the populated columns.
            from omero.grid import DoubleColumn, LongColumn

            init_columns = [
                LongColumn('Image', '', []),
                DoubleColumn('Energy_keV', '', []),
                DoubleColumn('Counts', '', [])
            ]

            table.initialize(init_columns)
            table.addData(columns)

            # Get the OriginalFile ID and close table
            orig_file_obj = table.getOriginalFile()
            orig_file_id = orig_file_obj.getId().getValue()
            table.close()

            # Create FileAnnotation for the table (THIS is how OMERO represents tables)
            from omero.model import FileAnnotationI, DatasetAnnotationLinkI, ImageAnnotationLinkI, OriginalFileI
            from omero.rtypes import rstring

            image = conn.getObject("Image", image_id)
            if not image:
                logger.error("Image %d not found; cannot attach SEM EDX table", image_id)
                return None

            # IMPORTANT:
            # Do NOT re-save/modify the OriginalFile object returned by table.getOriginalFile().
            # Reference it by ID only, otherwise the server may attempt to change its update-event
            # and throw OptimisticLockException (exactly what you're seeing).
            ann = FileAnnotationI()
            ann.setFile(OriginalFileI(orig_file_id, False))
            ann.setNs(rstring("openmicroscopy.org/omero/client/table"))
            ann.setDescription(rstring(f"SEM EDX spectrum data from {txt_filename}"))

            ann = conn.getUpdateService().saveAndReturnObject(ann)

            # OMERO.web Table rendering works reliably when the "table file annotation" is attached
            # to a Dataset (or Project). The Image view then shows row values when the table has a
            # column named "Image" that references image IDs (we create that column above).
            parents = list(image.listParents())
            dataset = parents[0] if parents else None

            if dataset is not None:
                link = DatasetAnnotationLinkI()
                link.setParent(dataset._obj)
            else:
                # Fallback: no dataset parent, attach to the Image so it's still accessible
                link = ImageAnnotationLinkI()
                link.setParent(image._obj)

            link.setChild(ann)
            conn.getUpdateService().saveObject(link)

            logger.info(
                "Created spectrum table '%s' for image %d (%d rows)",
                table_name,
                image_id,
                len(spectrum),
            )
            return ann.getId().getValue()
            
        except Exception:
            logger.exception("Failed to populate table for image %d", image_id)
            try:
                table.close()
            except Exception:
                pass
            return None
            
    except Exception as exc:
        logger.error("Failed to create spectrum table for image %d: %s", image_id, exc)
        return None


def attach_sem_edx_tables(
    conn,
    image_id: int,
    txt_path: Path,
    persist_table: bool = True,
) -> Optional[int]:
    """
    Parse SEM EDX txt file and create OMERO Table with spectrum data attached to the image.
    
    This is the main function to call from the upload workflow.
    
    Args:
        conn: OMERO BlitzGateway connection
        image_id: ID of the image to attach table to
        txt_path: Path to the SEM EDX txt file
        
    Returns:
        File annotation ID if successful, None otherwise
    """
    logger.info("Parsing SEM EDX file %s for image %d", txt_path.name, image_id)
    
    # Parse the file (keep all parsing logic for future use)
    parsed = parse_emsa_file(txt_path)
    
    # Create spectrum table ONLY
    if parsed['spectrum']:
        columns = build_spectrum_columns(image_id, parsed['spectrum'])
        if not persist_table:
            logger.info(
                "SEM EDX table creation skipped for image %d (settings disabled) from %s",
                image_id,
                txt_path.name,
            )
            return None

        table_id = create_spectrum_table(
            conn, image_id, parsed['spectrum'], txt_path.name, columns=columns
        )
        if table_id:
            logger.info("Created spectrum table for image %d from %s", 
                       image_id, txt_path.name)
            return table_id
        else:
            logger.error("Failed to create spectrum table for image %d from %s",
                        image_id, txt_path.name)
            return None
    else:
        logger.warning("No spectrum data found in %s", txt_path.name)
        return None
