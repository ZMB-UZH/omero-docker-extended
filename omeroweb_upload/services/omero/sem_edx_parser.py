"""
SEM EDX EMSA/MAS format parser and OMERO Table creator.

This module parses SEM EDX spectrum files in EMSA/MAS format and creates
OMERO Tables attached to images containing:
1. Metadata table (all #KEY: value pairs)
2. Element labels table (##OXINSTLABEL entries)
3. Spectrum data table (X,Y coordinate pairs)
"""
import logging
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
        line = line.rstrip()
        if not line:
            continue
        
        # Check if we've entered the spectrum data section
        if line.startswith('#SPECTRUM'):
            in_spectrum = True
            # Also capture this as metadata
            parts = line.split(':', 1)
            if len(parts) == 2:
                key = parts[0].replace('#', '').strip()
                value = parts[1].strip()
                metadata[key] = value
            continue
        
        # Check for end of data
        if line.startswith('#ENDOFDATA'):
            break
        
        # If we're in the spectrum section, parse X,Y pairs
        if in_spectrum:
            # Parse X, Y pairs (format: "0.01000, 1057.0")
            parts = line.split(',')
            if len(parts) == 2:
                try:
                    x = float(parts[0].strip())
                    y = float(parts[1].strip())
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


def create_metadata_table(conn, image_id: int, metadata: Dict[str, str], txt_filename: str) -> Optional[int]:
    """
    Create an OMERO Table containing metadata key-value pairs.
    
    Args:
        conn: OMERO BlitzGateway connection
        image_id: ID of the image to attach the table to
        metadata: Dictionary of metadata key-value pairs
        txt_filename: Name of the source txt file (for table name)
        
    Returns:
        Table file annotation ID if successful, None otherwise
    """
    if not metadata:
        logger.info("No metadata to create table for image %d", image_id)
        return None
    
    try:
        from omero.grid import LongColumn, StringColumn
        from omero.model import OriginalFileI, FileAnnotationI
        from omero.rtypes import rstring, rlong
        
        # Sort keys for consistent ordering
        sorted_keys = sorted(metadata.keys())
        
        # Create columns
        columns = [
            StringColumn('Key', '', []),
            StringColumn('Value', '', [])
        ]
        
        # Populate data
        for key in sorted_keys:
            columns[0].values.append(key)
            columns[1].values.append(str(metadata[key]))
        
        # Create the table
        resources = conn.c.sf.sharedResources()
        repository_id = resources.repositories().descriptions[0].getId().getValue()
        
        table_name = f"SEM_EDX_Metadata_{Path(txt_filename).stem}.h5"
        table = resources.newTable(repository_id, table_name)
        
        if table is None:
            logger.error("Failed to create table for image %d", image_id)
            return None
        
        try:
            table.initialize(columns)
            table.addData(columns)
            
            # Get the original file
            orig_file = table.getOriginalFile()
            table.close()
            
            # Create file annotation
            file_ann = FileAnnotationI()
            file_ann.setFile(OriginalFileI(orig_file.getId().getValue(), False))
            file_ann.setNs(rstring("omero.tables.sem_edx.metadata"))
            file_ann.setDescription(rstring(f"SEM EDX metadata from {txt_filename}"))
            
            # Save and link to image
            update_service = conn.getUpdateService()
            file_ann = update_service.saveAndReturnObject(file_ann)
            
            # Link to image
            image = conn.getObject("Image", image_id)
            if image:
                from omero.gateway import FileAnnotationWrapper
                image.linkAnnotation(FileAnnotationWrapper(conn, file_ann))
                logger.info("Created metadata table for image %d (%d rows)", 
                           image_id, len(sorted_keys))
                return file_ann.getId().getValue()
            
        except Exception as exc:
            logger.error("Failed to populate table for image %d: %s", image_id, exc)
            try:
                table.close()
            except:
                pass
            return None
            
    except Exception as exc:
        logger.error("Failed to create metadata table for image %d: %s", image_id, exc)
        return None


def create_elements_table(conn, image_id: int, elements: List[Dict], txt_filename: str) -> Optional[int]:
    """
    Create an OMERO Table containing element label information.
    
    Args:
        conn: OMERO BlitzGateway connection
        image_id: ID of the image to attach the table to
        elements: List of element dictionaries with atomic_number, energy_kev, symbol
        txt_filename: Name of the source txt file (for table name)
        
    Returns:
        Table file annotation ID if successful, None otherwise
    """
    if not elements:
        logger.info("No element labels to create table for image %d", image_id)
        return None
    
    try:
        from omero.grid import LongColumn, DoubleColumn, StringColumn
        from omero.model import OriginalFileI, FileAnnotationI
        from omero.rtypes import rstring, rlong
        
        # Sort by atomic number
        sorted_elements = sorted(elements, key=lambda x: x['atomic_number'])
        
        # Create columns
        columns = [
            StringColumn('Element_Symbol', '', []),
            LongColumn('Atomic_Number', '', []),
            DoubleColumn('Energy_keV', '', [])
        ]
        
        # Populate data
        for elem in sorted_elements:
            columns[0].values.append(elem['symbol'])
            columns[1].values.append(elem['atomic_number'])
            columns[2].values.append(elem['energy_kev'])
        
        # Create the table
        resources = conn.c.sf.sharedResources()
        repository_id = resources.repositories().descriptions[0].getId().getValue()
        
        table_name = f"SEM_EDX_Elements_{Path(txt_filename).stem}.h5"
        table = resources.newTable(repository_id, table_name)
        
        if table is None:
            logger.error("Failed to create elements table for image %d", image_id)
            return None
        
        try:
            table.initialize(columns)
            table.addData(columns)
            
            # Get the original file
            orig_file = table.getOriginalFile()
            table.close()
            
            # Create file annotation
            file_ann = FileAnnotationI()
            file_ann.setFile(OriginalFileI(orig_file.getId().getValue(), False))
            file_ann.setNs(rstring("omero.tables.sem_edx.elements"))
            file_ann.setDescription(rstring(f"SEM EDX element labels from {txt_filename}"))
            
            # Save and link to image
            update_service = conn.getUpdateService()
            file_ann = update_service.saveAndReturnObject(file_ann)
            
            # Link to image
            image = conn.getObject("Image", image_id)
            if image:
                from omero.gateway import FileAnnotationWrapper
                image.linkAnnotation(FileAnnotationWrapper(conn, file_ann))
                logger.info("Created elements table for image %d (%d rows)", 
                           image_id, len(sorted_elements))
                return file_ann.getId().getValue()
            
        except Exception as exc:
            logger.error("Failed to populate elements table for image %d: %s", image_id, exc)
            try:
                table.close()
            except:
                pass
            return None
            
    except Exception as exc:
        logger.error("Failed to create elements table for image %d: %s", image_id, exc)
        return None


def create_spectrum_table(conn, image_id: int, spectrum: List[Tuple[float, float]], 
                         txt_filename: str) -> Optional[int]:
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
    
    try:
        from omero.grid import DoubleColumn
        from omero.model import OriginalFileI, FileAnnotationI
        from omero.rtypes import rstring, rlong
        
        # Create columns
        columns = [
            DoubleColumn('Energy_keV', '', []),
            DoubleColumn('Counts', '', [])
        ]
        
        # Populate data
        for x, y in spectrum:
            columns[0].values.append(x)
            columns[1].values.append(y)
        
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
            table.initialize(columns)
            table.addData(columns)
            
            # Get the original file
            orig_file = table.getOriginalFile()
            table.close()
            
            # Create file annotation
            file_ann = FileAnnotationI()
            file_ann.setFile(OriginalFileI(orig_file.getId().getValue(), False))
            file_ann.setNs(rstring("omero.tables.sem_edx.spectrum"))
            file_ann.setDescription(rstring(f"SEM EDX spectrum data from {txt_filename}"))
            
            # Save and link to image
            update_service = conn.getUpdateService()
            file_ann = update_service.saveAndReturnObject(file_ann)
            
            # Link to image
            image = conn.getObject("Image", image_id)
            if image:
                from omero.gateway import FileAnnotationWrapper
                image.linkAnnotation(FileAnnotationWrapper(conn, file_ann))
                logger.info("Created spectrum table '%s' for image %d (%d rows)", 
                           table_name, image_id, len(spectrum))
                return file_ann.getId().getValue()
            
        except Exception as exc:
            logger.error("Failed to populate spectrum table for image %d: %s", image_id, exc)
            try:
                table.close()
            except:
                pass
            return None
            
    except Exception as exc:
        logger.error("Failed to create spectrum table for image %d: %s", image_id, exc)
        return None


def attach_sem_edx_tables(conn, image_id: int, txt_path: Path) -> Optional[int]:
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
        table_id = create_spectrum_table(
            conn, image_id, parsed['spectrum'], txt_path.name
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
