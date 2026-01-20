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

    fig, ax = plt.subplots(figsize=(8.5, 5.0), dpi=150)
    fig.patch.set_facecolor("#1f4d7a")
    ax.set_facecolor("#1f4d7a")

    spectrum_color = "#ffe600"
    label_text_color = "#0b3d1a"
    label_fill_color = "#b8f0b0"
    label_edge_color = "#ffffff"
    label_line_color = "#ffffff"

    ax.plot(energies, counts, color=spectrum_color, linewidth=1.4)
    ax.fill_between(energies, counts, 0, color=spectrum_color, alpha=0.38)
    ax.set_xlim(x_min, x_max)
    ax.set_ylim(0, y_max * 1.05)

    ax.set_xlabel("keV", color="white")
    ax.set_ylabel("cps/eV", color="white")
    ax.tick_params(colors="white")
    for spine in ax.spines.values():
        spine.set_color("white")

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

    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    axes_bbox = ax.get_window_extent(renderer=renderer)

    used_labels = set()
    placed_bboxes = []
    for energy, symbol in sorted(element_labels, key=lambda item: item[0]):
        if (energy, symbol) in used_labels:
            continue
        used_labels.add((energy, symbol))
        nearest = _nearest_spectrum_point(spectrum, energy)
        if not nearest:
            continue
        _, y_val = nearest
        annotation = ax.annotate(
            symbol,
            xy=(energy, y_val),
            xytext=(0, 0),
            textcoords="offset points",
            ha="center",
            va="bottom",
            fontsize=8,
            color=label_text_color,
            bbox={
                "boxstyle": "round,pad=0.2",
                "facecolor": label_fill_color,
                "edgecolor": label_edge_color,
                "linewidth": 0.8,
                "alpha": 0.6,
            },
            arrowprops={
                "arrowstyle": "-",
                "color": label_line_color,
                "linewidth": 0.8,
            },
        )

        candidate_offsets = []
        y_ratio = y_val / y_max if y_max else 0
        base_offset = 8 + (1 - y_ratio) * 12
        vertical_steps = [0, 10, 20, 30, 42, 56, 72]
        for level, step in enumerate(vertical_steps):
            y_offset = base_offset + step + (level * 2)
            candidate_offsets.append((0, y_offset))

        tilt_offsets = (-16, 16, -28, 28, -40, 40)
        for level, step in enumerate(vertical_steps[1:]):
            y_offset = base_offset + step + (level * 3)
            for x_offset in tilt_offsets:
                candidate_offsets.append((x_offset, y_offset))

        chosen_bbox = None
        for x_offset, y_offset in candidate_offsets:
            annotation.set_position((x_offset, y_offset))
            bbox = annotation.get_window_extent(renderer=renderer).expanded(1.05, 1.1)
            if bbox.y1 > axes_bbox.y1:
                continue
            if bbox.y0 < axes_bbox.y0:
                continue
            if bbox.x0 < axes_bbox.x0 or bbox.x1 > axes_bbox.x1:
                continue
            if any(bbox.overlaps(existing) for existing in placed_bboxes):
                continue
            chosen_bbox = bbox
            break

        if chosen_bbox is None:
            annotation.set_position(candidate_offsets[-1])
            chosen_bbox = annotation.get_window_extent(renderer=renderer).expanded(1.05, 1.1)
            dx_pixels = 0.0
            dy_pixels = 0.0
            if chosen_bbox.x0 < axes_bbox.x0:
                dx_pixels = axes_bbox.x0 - chosen_bbox.x0
            elif chosen_bbox.x1 > axes_bbox.x1:
                dx_pixels = axes_bbox.x1 - chosen_bbox.x1
            if chosen_bbox.y0 < axes_bbox.y0:
                dy_pixels = axes_bbox.y0 - chosen_bbox.y0
            elif chosen_bbox.y1 > axes_bbox.y1:
                dy_pixels = axes_bbox.y1 - chosen_bbox.y1
            if dx_pixels or dy_pixels:
                points_per_pixel = 72 / fig.dpi
                current_x, current_y = annotation.get_position()
                annotation.set_position(
                    (
                        current_x + dx_pixels * points_per_pixel,
                        current_y + dy_pixels * points_per_pixel,
                    )
                )
                chosen_bbox = annotation.get_window_extent(renderer=renderer).expanded(1.05, 1.1)

        placed_bboxes.append(chosen_bbox)

    fig.tight_layout()
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
