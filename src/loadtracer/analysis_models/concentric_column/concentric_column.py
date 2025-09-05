from pydantic import BaseModel
from typing import Optional


class ConcentricColumn(BaseModel):
    height: float
    point_loads: Optional[list[dict]] = None
    gravity_dir: str = "z"
    strong_axis_dir: str = "y"
    weak_axis_dir: str = "x"
    reverse_reaction_sign: bool = False

    def add_point_load(
        self,
        magnitude: float,
        location: float,
        case: str,
        direction: str,
    ):
        """
        Adds a point load to the collection of point loads
        """
        point_load = {
            "magnitude": magnitude,
            "location": location,
            "case": case,
            "direction": direction,
        }
        self.point_loads.append(point_load)



    def get_reactions(self) -> float:
        """
        Returns a float representing the total sum of loads for the
        given 'dir' (direction) and 'case' (load case).
        """
        acc = {}
        for p in self.point_loads:
            dir = p['direction']
            acc.setdefault(dir, {})
            case = p['case']
            acc[dir].setdefault(case, [])
            acc[dir][case].append(p['magnitude'])

        for dir, cases in acc.items():
            for case, forces in cases.items():
                acc[dir][case] = sum(forces)
                if self.reverse_reaction_sign:
                    acc[dir][case] = -acc[dir][case]
        return acc

    

    @classmethod
    def from_point_loads(cls, point_loads: dict[str, dict[str, str | float]]):
        """
        
        """
        reaction_components = {}
        for load_case in point_loads.items():
            reaction_components.setdefault(load_case, {})
            for load_dir, pt_loads in load_case.items():
                reaction_components[load_case].setdefault(load_dir, [])
                for point_load in pt_loads:
                    reaction_components[load_dir][load_case].append(point_load['magnitude'])
        return cls(reaction_components)