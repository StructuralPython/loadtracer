from dataclasses import dataclass
from typing import Optional
from papermodels.loads.load_distribution import Singularity, singularities_to_polygon

@dataclass
class LinearReaction:
    x0: float
    x1: float
    w0: float
    w1: float

    def point_in_reaction(self, x: float):
        return self.x0 <= x <= self.x1
    
    def points_enclose_reaction(self, xa: float, xb: float) -> bool:
        """
        Returns True if xa <= self.x0 <= self.x1 <= xb
        """
        return xa <= self.x0 <= self.x1 <= xb

    def extract_reaction(self, xa: float, xb: float) -> "LinearReaction":
        """
        Returns the portion of the reaction that would exist between
        'xa' and 'xb'
        """
        m = (self.w1 - self.w0) / (self.x1 - self.x0)
        y0 = self.w0
        if not any([
            self.point_in_reaction(xa), 
            self.point_in_reaction(xb),
            self.points_enclose_reaction(xa, xb),
        ]):
            return LinearReaction(self.x0, self.x1, 0.0, 0.0) 
        if not self.point_in_reaction(xa):
            xi = self.x0
            yi = self.w0
        else:
            xi = xa
            yi = y0 + (xi - self.x0) * m

        if not self.point_in_reaction(xb):
            xj = self.x1
            yj = self.w1
        else:
            xj = xb
            yj = y0 + (xj - self.x0) * m

        return LinearReaction(xi, xj, yi, yj)


@dataclass
class LinearReactionString:
    """
    
    """
    _reaction_components = dict[str, dict[str, list[LinearReaction]]]

    def __post_init__(self):
        self.reactions = sorted(self.reactions, key=lambda x: x.x0)


    def extract_reactions(self, xa: float, xb: float, case: str, dir: str) -> Optional[list[LinearReaction]]:
        """
        Returns a LinearReactionString representing the linear reactions that
        exist between 'xa' and 'xb' extracted from self.

        Returns None if there are no reactions within the 'x0' and 'x1' extents
        """
        extracted = []
        for reaction in self._reaction_components.get(case, {}).get(dir, {}):
            extracted.append(reaction.extract_reaction(xa, xb))
        return LinearReactionString([lr for lr in extracted if lr.w0 != 0 and lr.w1 != 0])
        

    @classmethod
    def from_dist_loads(cls, dist_loads: dict[str, dict[str, list[dict]]]):
        """
        Collects distributed loads from the top of a wall run and
        converts them into a LinearReactionString which can sum and
        parcel out the reactions into wall segments or beams that are
        supporting the wall run.
        """
        reaction_components = {}
        for load_dir, dir_loads in dist_loads.items():
            reaction_components.setdefault(load_dir, {})
            for load_case, distributed_loads in dir_loads.items():
                reaction_components[load_dir].setdefault(load_case, [])
                singularity_functions = []
                for dist_load in distributed_loads:
                    m = (dist_load['w1'] - dist_load['w0']) / (dist_load['x1'] - dist_load['x0'])
                    y0 = dist_load['w0']
                    singularity_function = Singularity(x0=dist_load['x0'], y0=y0, x1=dist_load['x1'], m=m, precision=3)
                    singularity_functions.append(singularity_function)
                linear_reactions = singularity_xy_to_linear_reactions(
                    singularities_to_polygon(
                        singularity_functions, xy=True
                    )
                )
                reaction_components[load_dir][load_case] = linear_reactions

        return cls(reaction_components)
            
        
def filter_repeated_y_values(xy_vals: list[list[float], list[float]]) -> list[list[float, float]]:
    """
    Returns xy_vals but with any "repeating" data points removed and
    returns a list of coordinates, list[list[float, float]]
    """
    coords = list(zip(*xy_vals))
    filtered = []
    for idx, (x, y) in enumerate(coords):
        next_y_idx = min(idx + 1, len(coords) - 1)
        next_y = coords[next_y_idx][1]
        if idx == 0:
            filtered.append([x, y])
            prev_y = y
        else:
            if prev_y == y == next_y:
                continue
            else:
                filtered.append([x, y])
        prev_y = y
    return filtered
        
    

def singularity_xy_to_linear_reactions(xy_vals: list[list[float], list[float]]) -> list[dict]:
    """
    Returns dicts representing distributed 
    """
    filtered = filter_repeated_y_values(xy_vals)
    dist_loads = []
    prev_x = None
    for idx, (x, y) in enumerate(filtered):
        cycle_idx = idx % 2
        if idx == 0: continue
        if prev_x is None:
            prev_x = x
            prev_y = y
        elif x - prev_x > 1e-3:
            dist_load = LinearReaction(**{"x0": prev_x, "w0": prev_y, "x1": x, "w1": y})
            dist_loads.append(dist_load)
            prev_x = x
            prev_y = y
        else:
            prev_x = x
            prev_y = y
    return dist_loads