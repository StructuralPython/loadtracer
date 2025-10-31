import loadtracer.analysis_models.wall_model as wm

POINT_LOAD_ARRAY = [
    {
        "location": 11.113,
        "magnitude": 0.0,
        "transfer_source": "J4.0-0",
        "transfer_reaction_index": 0,
        "direction": "gravity",
    },
    {
        "location": 10.113,
        "magnitude": 0.0,
        "transfer_source": "J4.0-1",
        "transfer_reaction_index": 0,
        "direction": "gravity",
    },
    {
        "location": 9.113,
        "magnitude": 0.0,
        "transfer_source": "J4.0-2",
        "transfer_reaction_index": 0,
        "direction": "gravity",
    },
    {
        "location": 8.113,
        "magnitude": 0.0,
        "transfer_source": "J4.0-3",
        "transfer_reaction_index": 0,
        "direction": "gravity",
    },
    {
        "location": 7.113,
        "magnitude": 0.0,
        "transfer_source": "J4.0-4",
        "transfer_reaction_index": 0,
        "direction": "gravity",
    },
    {
        "location": 6.113,
        "magnitude": 0.0,
        "transfer_source": "J4.0-5",
        "transfer_reaction_index": 0,
        "direction": "gravity",
    },
    {
        "location": 5.113,
        "magnitude": 0.0,
        "transfer_source": "J4.0-6",
        "transfer_reaction_index": 0,
        "direction": "gravity",
    },
    {
        "location": 4.113,
        "magnitude": 0.0,
        "transfer_source": "J4.0-7",
        "transfer_reaction_index": 0,
        "direction": "gravity",
    },
    {
        "location": 3.113,
        "magnitude": 0.0,
        "transfer_source": "J4.0-8",
        "transfer_reaction_index": 0,
        "direction": "gravity",
    },
    {
        "location": 2.113,
        "magnitude": 0.0,
        "transfer_source": "J4.0-9",
        "transfer_reaction_index": 0,
        "direction": "gravity",
    },
    {
        "location": 1.113,
        "magnitude": 0.0,
        "transfer_source": "J4.0-10",
        "transfer_reaction_index": 0,
        "direction": "gravity",
    },
    {
        "location": 0.113,
        "magnitude": 0.0,
        "transfer_source": "J4.0-11",
        "transfer_reaction_index": 0,
        "direction": "gravity",
    },
    {
        "location": 0.0,
        "magnitude": 0.0,
        "transfer_source": "J4.0-12",
        "transfer_reaction_index": 0,
        "direction": "gravity",
    },
]


def test_filter_point_arrays():
    by_parent = wm.filter_point_arrays(POINT_LOAD_ARRAY)
    assert list(by_parent.keys()) == ["J4.0"]
    assert len(by_parent["J4.0"]) == 13
    assert by_parent["J4.0"][0]["location"] == 0.0
    assert by_parent["J4.0"][-1]["location"] == 11.113
    assert by_parent["J4.0"][2]["location"] == 1.113


def test_get_point_intervals_by_parent():
    by_parent = wm.filter_point_arrays(POINT_LOAD_ARRAY)
    intervals = wm.get_point_intervals_by_parent(by_parent)
    assert list(intervals.keys()) == ["J4.0"]
    assert len(intervals["J4.0"]) == 12
    assert intervals["J4.0"][0] == 0.113
    assert intervals["J4.0"][1] == 1.0
    assert intervals["J4.0"][-1] == 1.0


def test_convert_point_arrays_into_dist_loads():
    dist_loads = wm.convert_point_arrays_into_dist_loads(POINT_LOAD_ARRAY)
    assert len(dist_loads) == 13
    assert dist_loads[0]["start_loc"] == 0.0
    assert dist_loads[0]["end_loc"] == 0.057
    assert dist_loads[1]["start_loc"] == 0.057
    assert dist_loads[1]["end_loc"] == 0.613
    assert dist_loads[2]["start_loc"] == 0.613
    assert dist_loads[2]["end_loc"] == 1.613
    assert dist_loads[-2]["start_loc"] == 9.613
    assert dist_loads[-2]["end_loc"] == 10.613
    assert dist_loads[-1]["start_loc"] == 10.613
    assert dist_loads[-1]["end_loc"] == 11.113
