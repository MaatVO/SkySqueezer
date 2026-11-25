from skysqueezer.gui.steps import step_states

BASE = {
    "source": "cds", "dataset": "reanalysis-era5-single-levels", "variables": [], "levels": [],
    "start": "2020-01-01", "end": "2020-01-31", "start_hour": 0, "end_hour": 23, "freq": "none", "hours": 6,
    "tz_offset": 0, "mode": "bbox", "west": 10.3, "south": 45.6, "east": 12.6, "north": 47.1, "points": "",
    "lon_convention": "-180..180", "grid": "native", "grid_custom": 0.5,
    "directory": "/data", "name": "era5_subset", "out_format": "icechunk", "target_mode": "create", "target_store": "",
    "extend_direction": "forward", "lossless": True, "keepbits": 13, "chunk_layout": None, "dtype": "float32",
    "compressor": "blosc-zstd", "clevel": 5, "shuffle": "shuffle", "sharding": False, "extra_attrs": "",
}


def states(**changes):
    return step_states({**BASE, **changes}, BASE, title="ERA5 hourly data on single levels", loaded=True)


def test_a_fresh_form_reads_as_its_defaults_with_variables_to_choose():
    s = states()
    assert s[1] == ("done", "Climate Data Store · ERA5 hourly data on single levels")
    assert s[2] == ("todo", "Choose what to download")
    assert s[3] == ("defaults", "2020-01-01 00:00 → 2020-01-31 23:00 · as stored")
    assert s[4][0] == "defaults" and s[4][1] == "Box · N 47.1 · W 10.3 · S 45.6 · E 12.6"
    assert s[5] == ("defaults", "New store · Icechunk · /data/era5_subset")


def test_changed_steps_read_done():
    s = states(variables=["u10", "v10", "d2m", "t2m"], levels=["500"], freq="day", tz_offset=1, mode="global",
               out_format="zarr")
    assert s[2] == ("done", "4 variables · 1 level · u10, v10, d2m and 1 more")
    assert s[3] == ("done", "2020-01-01 00:00 → 2020-01-31 23:00 · daily · UTC+1")
    assert s[4] == ("done", "Global")
    assert s[5][0] == "done" and "Zarr" in s[5][1]


def test_what_cannot_run_is_flagged():
    assert states(start="2020-02-01")[3] == ("error", "The end is before the start")
    assert states(start="1st of May")[3][0] == "error"
    assert states(north=40, south=45)[4] == ("error", "North must be above south")
    assert states(mode="points", points="# only a comment\n")[4][0] == "todo"
    assert states(target_mode="extend")[5] == ("error", "Enter the Icechunk store to extend")


def test_dataset_states_follow_loading():
    f = {**BASE}
    assert step_states(f, BASE, title=None)[1][0] == "todo"
    assert step_states(f, BASE, title="ERA5")[1][0] == "pending"
    assert step_states(f, BASE, title="ERA5", has_key=False)[1][0] == "error"
    assert step_states(f, BASE, title="ERA5", failed=True)[1][0] == "error"


def test_cds_grid_and_points_are_summed_up():
    s = states(grid="0.5", mode="points", points="trento, 46.07, 11.12\nbolzano, 46.5, 11.35")
    assert s[4] == ("done", "2 points · grid 0.5°")


def test_steps_name_every_dataset_of_a_combined_store():
    from skysqueezer.gui.steps import dataset_step, variables_step

    f = {"source": "edh", "dataset": "era5-single-levels-atmosphere", "variables": ["msl"],
         "extra": ["era5-pressure-levels"], "xvars": {"era5-pressure-levels": ["t", "z"]}, "levels": [850]}
    state, line = dataset_step(f, "ERA5 single levels", True, False, True)
    assert state == "done" and line.endswith("ERA5 single levels + era5-pressure-levels")
    state, line = variables_step(f)
    assert state == "done" and line.startswith("3 variables")
    f["source"] = "cds"  # combining is Earth Data Hub only: the added datasets are not counted
    assert variables_step(f)[1].startswith("1 variable")
