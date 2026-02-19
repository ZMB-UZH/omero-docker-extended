import random
import math
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
    """Bounding box for collision detection"""
    def __init__(self, x0, y0, x1, y1):
        self.x0 = x0
        self.y0 = y0
        self.x1 = x1
        self.y1 = y1
    
    def overlaps(self, other):
        """Check if this bbox overlaps with another"""
        return not (self.x1 <= other.x0 or self.x0 >= other.x1 or 
                   self.y1 <= other.y0 or self.y0 >= other.y1)
    
    def overlap_area(self, other):
        """Calculate overlap area with another bbox"""
        if not self.overlaps(other):
            return 0.0
        
        x_overlap = min(self.x1, other.x1) - max(self.x0, other.x0)
        y_overlap = min(self.y1, other.y1) - max(self.y0, other.y0)
        return x_overlap * y_overlap


def lines_cross(x1, y1, x2, y2, x3, y3, x4, y4):
    """Check if line segment (x1,y1)-(x2,y2) crosses (x3,y3)-(x4,y4)"""
    def ccw(ax, ay, bx, by, cx, cy):
        return (cy - ay) * (bx - ax) > (by - ay) * (cx - ax)
    
    return (ccw(x1, y1, x3, y3, x4, y4) != ccw(x2, y2, x3, y3, x4, y4) and
            ccw(x1, y1, x2, y2, x3, y3) != ccw(x1, y1, x2, y2, x4, y4))


class LabelGene:
    """Single label placement gene"""
    def __init__(self, label_id: int, x: float, y: float):
        self.label_id = label_id
        self.x = x
        self.y = y
    
    def __repr__(self):
        return f"Gene(id={self.label_id}, x={self.x:.1f}, y={self.y:.1f})"


class Chromosome:
    """
    A complete solution (placement of all labels)
    genes: List of LabelGene objects
    fitness: Score (lower is better)
    """
    def __init__(self, genes: List[LabelGene]):
        self.genes = genes
        self.fitness = float('inf')
    
    def copy(self):
        """Deep copy of chromosome"""
        return Chromosome([LabelGene(g.label_id, g.x, g.y) for g in self.genes])
    
    def __repr__(self):
        return f"Chromosome(genes={len(self.genes)}, fitness={self.fitness:.2f})"


class GeneticLabelPlacer:
    """
    Genetic algorithm for optimal label placement
    """
    def __init__(
        self,
        label_specs: List[Dict[str, Any]],
        axes_bbox: BBox,
        ax,
        population_size: int = 200,
        generations: int = 500,
        mutation_rate: float = 0.15,
        elite_size: int = 10
    ):
        self.label_specs = label_specs
        self.axes_bbox = axes_bbox
        self.ax = ax
        self.population_size = population_size
        self.generations = generations
        self.mutation_rate = mutation_rate
        self.elite_size = elite_size
        
        # Store for line crossing checks
        self.peak_positions = {}
        for spec in label_specs:
            self.peak_positions[spec['id']] = []
            for peak_e in spec['peak_energies']:
                px, py = ax.transData.transform((peak_e, spec['spectrum_y']))
                self.peak_positions[spec['id']].append((px, py))
        
        print(f"\n=== Genetic Algorithm Setup ===")
        print(f"Labels: {len(label_specs)}")
        print(f"Population: {population_size}")
        print(f"Generations: {generations}")
        print(f"Mutation rate: {mutation_rate}")
        print(f"Elite size: {elite_size}")
    
    def generate_initial_chromosome(self) -> Chromosome:
        """
        IMPROVEMENT 4: Initial placement in INCREASING X order (left to right)
        """
        genes = []
        
        for spec in self.label_specs:
            # Initial position: slightly above peak, centered on X
            w = spec['width']
            h = spec['height']
            
            x = spec['x_peak']
            y = spec['y_peak'] + 30 + h/2
            
            # Clamp to bounds
            min_x = self.axes_bbox.x0 + 10 + w/2
            max_x = self.axes_bbox.x1 - 10 - w/2
            min_y = spec['y_peak'] + 25 + h/2
            max_y = self.axes_bbox.y1 - 10 - h/2
            
            x = max(min_x, min(max_x, x))
            y = max(min_y, min(max_y, y))
            
            genes.append(LabelGene(spec['id'], x, y))
        
        return Chromosome(genes)
    
    def generate_random_chromosome(self) -> Chromosome:
        """Generate random valid placement"""
        genes = []
        
        for spec in self.label_specs:
            w = spec['width']
            h = spec['height']
            
            min_x = self.axes_bbox.x0 + 10 + w/2
            max_x = self.axes_bbox.x1 - 10 - w/2
            min_y = spec['y_peak'] + 25 + h/2
            max_y = self.axes_bbox.y1 - 10 - h/2
            
            if min_x > max_x or min_y > max_y:
                x = spec['x_peak']
                y = spec['y_peak'] + 30 + h/2
            else:
                x = random.uniform(min_x, max_x)
                y = random.uniform(min_y, max_y)
            
            genes.append(LabelGene(spec['id'], x, y))
        
        return Chromosome(genes)
    
    def calculate_fitness(self, chromosome: Chromosome) -> float:
        """
        Calculate fitness score (LOWER is better)
        """
        score = 0.0
        
        # Build bboxes
        bboxes = []
        for gene in chromosome.genes:
            spec = self.label_specs[gene.label_id]
            w = spec['width']
            h = spec['height']
            bbox = BBox(gene.x - w/2, gene.y - h/2, gene.x + w/2, gene.y + h/2)
            bboxes.append(bbox)
        
        # 1. OVERLAP PENALTY (huge)
        overlap_penalty = 0.0
        for i in range(len(bboxes)):
            for j in range(i + 1, len(bboxes)):
                overlap = bboxes[i].overlap_area(bboxes[j])
                if overlap > 0:
                    overlap_penalty += overlap * 1000
        
        # 2. LINE CROSSING PENALTY (large)
        crossing_penalty = 0.0
        for i, gene_i in enumerate(chromosome.genes):
            for j, gene_j in enumerate(chromosome.genes):
                if i >= j:
                    continue
                
                for px1, py1 in self.peak_positions[gene_i.label_id]:
                    for px2, py2 in self.peak_positions[gene_j.label_id]:
                        if lines_cross(px1, py1, gene_i.x, gene_i.y,
                                     px2, py2, gene_j.x, gene_j.y):
                            crossing_penalty += 100
        
        # 3. DISTANCE PENALTY (exponential - punish far labels)
        distance_penalty = 0.0
        for gene in chromosome.genes:
            spec = self.label_specs[gene.label_id]
            ideal_x = spec['x_peak']
            ideal_y = spec['y_peak'] + 30 + (spec['height'] / 2)
            
            dx = gene.x - ideal_x
            dy = gene.y - ideal_y
            distance = math.sqrt(dx*dx + dy*dy)
            
            # Exponential penalty
            distance_penalty += (distance ** 1.5) * 0.5

            # Strongly discourage unnecessary horizontal drift
            # (vertical movement is preferred over x-movement)
            distance_penalty += abs(dx) * 25.0

            # Penalize excessive vertical lift (labels drifting too far up)
            excess_y = gene.y - ideal_y
            if excess_y > 25:
                distance_penalty += (excess_y ** 2) * 3.0


        
        # 4. OUT OF BOUNDS PENALTY (massive)
        bounds_penalty = 0.0
        for i, gene in enumerate(chromosome.genes):
            bbox = bboxes[i]
            spec = self.label_specs[gene.label_id]
            
            if bbox.x0 < self.axes_bbox.x0 or bbox.x1 > self.axes_bbox.x1:
                bounds_penalty += 10000
            if bbox.y0 < self.axes_bbox.y0 or bbox.y1 > self.axes_bbox.y1:
                bounds_penalty += 10000
            
            if bbox.y0 < spec['y_peak'] + 20:
                bounds_penalty += 5000
            
            # Maximum distance constraint
            dx = gene.x - spec['x_peak']
            dy = gene.y - (spec['y_peak'] + 30 + (spec['height'] / 2))
            dist = math.sqrt(dx*dx + dy*dy)
            if dist > 300:
                bounds_penalty += (dist - 300) * 50
        
        score = overlap_penalty + crossing_penalty + distance_penalty + bounds_penalty
        return score
    
    def tournament_selection(self, population: List[Chromosome], tournament_size: int = 3) -> Chromosome:
        """Select parent using tournament selection"""
        tournament = random.sample(population, tournament_size)
        return min(tournament, key=lambda c: c.fitness)
    
    def crossover(self, parent1: Chromosome, parent2: Chromosome) -> Tuple[Chromosome, Chromosome]:
        """Ordered crossover"""
        n = len(parent1.genes)
        split = random.randint(1, n - 1)
        
        child1_genes = []
        child2_genes = []
        
        for i in range(n):
            if i < split:
                child1_genes.append(LabelGene(
                    parent1.genes[i].label_id,
                    parent1.genes[i].x,
                    parent1.genes[i].y
                ))
                child2_genes.append(LabelGene(
                    parent2.genes[i].label_id,
                    parent2.genes[i].x,
                    parent2.genes[i].y
                ))
            else:
                child1_genes.append(LabelGene(
                    parent2.genes[i].label_id,
                    parent2.genes[i].x,
                    parent2.genes[i].y
                ))
                child2_genes.append(LabelGene(
                    parent1.genes[i].label_id,
                    parent1.genes[i].x,
                    parent1.genes[i].y
                ))
        
        return Chromosome(child1_genes), Chromosome(child2_genes)
    
    def mutate(self, chromosome: Chromosome) -> Chromosome:
        """Mutate by randomly adjusting positions"""
        mutated = chromosome.copy()
        
        for gene in mutated.genes:
            if random.random() < self.mutation_rate:
                spec = self.label_specs[gene.label_id]
                w = spec['width']
                h = spec['height']
                
                dx = random.uniform(-30, 30)
                dy = random.uniform(-20, 40)
                
                new_x = gene.x + dx
                new_y = gene.y + dy
                
                # Clamp to bounds
                min_x = self.axes_bbox.x0 + 10 + w/2
                max_x = self.axes_bbox.x1 - 10 - w/2
                min_y = spec['y_peak'] + 25 + h/2
                max_y = self.axes_bbox.y1 - 10 - h/2
                
                gene.x = max(min_x, min(max_x, new_x))
                gene.y = max(min_y, min(max_y, new_y))
        
        return mutated
    
    def evolve(self) -> Chromosome:
        """Main genetic algorithm loop"""
        print(f"\n=== Starting Evolution ===")
        
        # Initialize population: ONE initial ordered + rest random
        population = [self.generate_initial_chromosome()]
        population.extend([self.generate_random_chromosome() 
                          for _ in range(self.population_size - 1)])
        
        # Calculate initial fitness
        for chrom in population:
            chrom.fitness = self.calculate_fitness(chrom)
        
        population.sort(key=lambda c: c.fitness)
        print(f"Generation 0: Best fitness = {population[0].fitness:.2f}")
        
        # Evolution loop
        for gen in range(1, self.generations + 1):
            new_population = []
            
            # Elitism
            elite = population[:self.elite_size]
            new_population.extend([e.copy() for e in elite])
            
            # Generate rest
            while len(new_population) < self.population_size:
                parent1 = self.tournament_selection(population)
                parent2 = self.tournament_selection(population)
                
                child1, child2 = self.crossover(parent1, parent2)
                
                child1 = self.mutate(child1)
                child2 = self.mutate(child2)
                
                new_population.append(child1)
                if len(new_population) < self.population_size:
                    new_population.append(child2)
            
            # Calculate fitness
            for chrom in new_population:
                chrom.fitness = self.calculate_fitness(chrom)
            
            population = new_population
            population.sort(key=lambda c: c.fitness)
            
            if gen % 20 == 0 or gen == self.generations:
                print(f"Generation {gen}: Best fitness = {population[0].fitness:.2f}")
        
        best_solution = population[0]
        print(f"\n=== Evolution Complete ===")
        print(f"Final best fitness: {best_solution.fitness:.2f}")
        
        return best_solution


def genetic_label_placement(
    labels_data: List[Tuple[float, float, str]],
    axes_bbox: BBox,
    fig,
    ax,
    renderer,
    fixed_offset_pixels: float = 30,
) -> List[Tuple[float, float, str, float, float, List[float]]]:
    """
    Genetic algorithm for label placement
    """
    if not labels_data:
        return []
    
    # IMPROVEMENT 3: Don't merge elements with same symbol but very different Y values
    from collections import defaultdict
    symbol_groups = defaultdict(list)
    for energy, spectrum_y, symbol in labels_data:
        symbol_groups[symbol].append((energy, spectrum_y))
    
    merged_labels = []
    for symbol, peaks in symbol_groups.items():
        peaks.sort(key=lambda x: x[0])  # Sort by X
        groups = []
        current_group = [peaks[0]]
        
        for i in range(1, len(peaks)):
            # IMPROVEMENT 3: Check both X proximity AND Y similarity
            x_close = peaks[i][0] - current_group[-1][0] < 0.5
            
            # Check Y difference
            y_current_avg = sum(p[1] for p in current_group) / len(current_group)
            y_diff_ratio = abs(peaks[i][1] - y_current_avg) / max(peaks[i][1], y_current_avg, 1.0)
            y_similar = y_diff_ratio < 0.3  # Less than 30% difference
            
            if x_close and y_similar:
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
    
    # IMPROVEMENT 4: Sort by X coordinate (left to right) for initial placement
    merged_labels.sort(key=lambda x: x[0])  # Sort by energy (X position)
    
    # Measure labels
    label_specs = []
    for idx, (center_energy, spectrum_y, symbol, peak_energies) in enumerate(merged_labels):
        x_peak_disp, y_peak_disp = ax.transData.transform((center_energy, spectrum_y))
        
        temp = ax.text(0, 0, symbol, fontsize=7.5,
                      bbox=dict(boxstyle='round,pad=0.35', facecolor='#b8f0b0'),
                      ha='center', va='center', alpha=0)
        fig.canvas.draw()
        bbox = temp.get_window_extent(renderer=renderer)
        temp.remove()
        
        label_specs.append({
            'id': idx,
            'energy': center_energy,
            'spectrum_y': spectrum_y,
            'symbol': symbol,
            'peak_energies': peak_energies,
            'x_peak': x_peak_disp,
            'y_peak': y_peak_disp,
            'width': bbox.width + 8,
            'height': bbox.height + 8
        })
    
    # Run genetic algorithm
    ga = GeneticLabelPlacer(
        label_specs=label_specs,
        axes_bbox=axes_bbox,
        ax=ax,
        population_size=80,
        generations=200,
        mutation_rate=0.15,
        elite_size=10
    )
    
    best_solution = ga.evolve()
    
    # Convert to output format
    final_positions = []
    for gene in best_solution.genes:
        spec = label_specs[gene.label_id]
        final_positions.append((
            spec['energy'],
            spec['spectrum_y'],
            spec['symbol'],
            gene.x,
            gene.y,
            spec['peak_energies']
        ))
    
    return final_positions


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
    y_max_data = max(counts) if counts else 1.0
    y_max_data = y_max_data if y_max_data > 0 else 1.0
    
    # IMPROVEMENT 1: Spectrum fills 85% of Y-axis, 15% reserved for labels
    y_max_plot = y_max_data / 0.85

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
    ax.set_ylim(0, y_max_plot * 1.05)

    # IMPROVEMENT 2: Denser ticks (2x more frequent)
    from matplotlib.ticker import MaxNLocator, AutoMinorLocator
    ax.xaxis.set_major_locator(MaxNLocator(nbins=20))  # 2x density
    ax.yaxis.set_major_locator(MaxNLocator(nbins=10))  # 2x density
    
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
    fig.subplots_adjust(left=0.08, right=0.98, top=0.97, bottom=0.10)
    
    # Initial rendering to get axes bbox
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    axes_bbox_raw = ax.get_window_extent(renderer=renderer)
    axes_bbox = BBox(axes_bbox_raw.x0, axes_bbox_raw.y0, axes_bbox_raw.x1, axes_bbox_raw.y1)
    
    # Run genetic algorithm for label placement
    final_positions = genetic_label_placement(
        labels_data,
        axes_bbox,
        fig,
        ax,
        renderer,
        fixed_offset_pixels=30
    )
    
    # Draw labels and connector lines
    for center_energy, spectrum_y, symbol, label_x, label_y, peak_energies in final_positions:
        # Draw connector lines from EACH peak to the label
        for peak_energy in peak_energies:
            nearest = _nearest_spectrum_point(spectrum, peak_energy)
            if nearest:
                peak_x, peak_y = nearest
                
                annotation = ax.annotate(
                    '',
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
        
        # Draw the label box
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
        image_id: ID of the image to use for dataset lookup
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
        image = conn.getObject("Image", image_id)
        if not image:
            logger.error("Image %d not found; cannot create SEM EDX table", image_id)
            return None

        parents = list(image.listParents())
        dataset = parents[0] if parents else None
        if dataset is None:
            logger.warning(
                "No dataset found for image %d; skipping SEM EDX table creation for %s",
                image_id,
                txt_filename,
            )
            return None

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

            from omero.model import DatasetAnnotationLinkI, FileAnnotationI, OriginalFileI
            from omero.rtypes import rstring

            ann = FileAnnotationI()
            ann.setFile(OriginalFileI(orig_file_id, False))
            ann.setNs(rstring("openmicroscopy.org/omero/client/table"))
            ann.setDescription(rstring(f"SEM EDX spectrum data from {txt_filename}"))

            ann = conn.getUpdateService().saveAndReturnObject(ann)

            link = DatasetAnnotationLinkI()
            link.setParent(dataset._obj)
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
    Parse SEM EDX txt file and create OMERO Table with spectrum data attached to the dataset.
    
    This is the main function to call from the upload workflow.
    
    Args:
        conn: OMERO BlitzGateway connection
        image_id: ID of the image to use for dataset lookup
        txt_path: Path to the SEM EDX txt file
        
    Returns:
        File annotation ID if successful, None otherwise
    """
    logger.info("Parsing SEM EDX file %s for image %d", txt_path.name, image_id)
    
    # Parse the file
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
