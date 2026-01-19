"""
SEM EDX EMSA/MAS format parser and OMERO Table creator.

This module parses SEM EDX spectrum files in EMSA/MAS format and creates
one OMERO Table containing the spectrum X,Y data.
"""
import logging
import re
import time
from pathlib import Path
from typing import Dict, List, Tuple, Any, Optional

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
