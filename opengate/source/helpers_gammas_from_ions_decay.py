import pathlib
import radioactivedecay as rd
import numpy as np
from .GammaFromIonDecayExtractor import *
import jsonpickle
import copy
import urllib
import pandas

"""
Gammas from ions decay helpers.
This file groups function useful to model source of gammas emitted during ions decay.

Abbreviated : GID (Gammas from Ions Decay)
"""


def print_gid_info(rad_name, br=1.0, tab=""):
    nuclide = get_nuclide_from_name(rad_name)
    print(
        f"{tab}{nuclide.nuclide}    Z={nuclide.Z} A={nuclide.A}     "
        f"HL={nuclide.half_life('readable')} ({nuclide.half_life('s'):.1f} s)"
        f"     BF={br}"
    )
    progeny = nuclide.progeny()
    brs = nuclide.branching_fractions()
    t = tab + "  "
    for p, b in zip(progeny, brs):
        print_gid_info(p, b, t)
    return nuclide


def get_nuclide_from_name(rad_name):
    try:
        return rd.Nuclide(rad_name)
    except:
        gate.fatal(f"Cannot find nuclide named {rad_name}, try something like 225Ac.")


def get_nuclide_and_direct_progeny(z, a):
    a = int(a)
    z = int(z)
    id = int(f"{z:3}{a:3}0000")
    nuclide = rd.Nuclide(id)
    p = nuclide.progeny()
    return nuclide, p


def get_nuclide_progeny(nuclide, intensity=1.0, parent=None):
    # insert current nuclide
    p = []
    if parent is None:
        a = Box()
        a.nuclide = nuclide
        a.hl = a.nuclide.half_life()
        a.parent = [None]
        a.intensity = intensity
        p.append(a)
    # start a list of daughters
    daughters = nuclide.progeny()
    branching_fractions = nuclide.branching_fractions()
    # loop recursively
    # the intensity is the branching fraction x the current intensity
    # if the rad is already in the list, we add the intensity
    nuc_to_add = []
    i = 0
    for d, br in zip(daughters, branching_fractions):
        a = Box()
        try:
            a.nuclide = rd.Nuclide(d)
        except:
            gate.warning(f"Unknown nuclide {d}, ignoring ...")
            continue
        a.hl = a.nuclide.half_life()
        a.parent = [nuclide]
        a.intensity = intensity * br
        p.append(a)
        aa = get_nuclide_progeny(a.nuclide, intensity=a.intensity, parent=nuclide)
        nuc_to_add += aa
        i = i + 1

    # the daughter's daughters are added after the loop to keep the order
    # also : merge parents
    for aa in nuc_to_add:
        found = next(
            (item for item in p if item.nuclide.nuclide == aa.nuclide.nuclide),
            None,
        )
        if found:
            found.intensity += aa.intensity
            found.parent += aa.parent
            # remove duplicate
            found.parent = list(set(found.parent))
        else:
            p.append(aa)
    return p


def atomic_relaxation_get_gammas_from_iaea_website(a, rad_name):
    livechart = "https://nds.iaea.org/relnsd/v0/data?"
    nuclide_name = f"{a}{rad_name}"
    url = livechart + f"fields=decay_rads&nuclides={nuclide_name}&rad_types=x"
    try:
        df = gate.lc_read_csv(url)
    except:
        raise Exception(
            f"Cannot get data for atomic relaxation of {rad_name} with this url : {url}"
        )
    if "intensity" not in df:
        # when there is no xray
        return None
    return df


def atomic_relaxation_get_ene_weights_from_df(df):
    if df is None:
        return np.array([]), np.array([])
    # remove blanks (unknown intensities)
    df = df[pandas.to_numeric(df["intensity"], errors="coerce").notna()]
    # convert to numeric. Note how one can specify the field by attribute or by string
    keV = gate.g4_units("keV")
    df.energy = df["energy"].astype(float)
    df.intensity = df["intensity"].astype(float)
    return df.energy.to_numpy() * keV, df.intensity.to_numpy() / 100


def atomic_relaxation_get_and_store_main_radionuclides():
    rads = [
        (225, "ac"),
        (221, "fr"),
        (221, "ra"),
        (217, "at"),
        (217, "rn"),
        (213, "bi"),
        (213, "po"),
        (212, "bi"),
        (212, "pb"),
        (212, "po"),
        (211, "at"),
        (211, "po"),
        (209, "tl"),
        (208, "tl"),
        (209, "pb"),
        (209, "bi"),
        (208, "pb"),
        (207, "pb"),
        (207, "bi"),
        (177, "lu"),
    ]
    for r in rads:
        print(r)
        try:
            df = gate.atomic_relaxation_get_gammas_from_iaea_website(r[0], r[1])
            gate.atomic_relaxation_store(f"{r[1]}-{r[0]}", df)
        except:
            gate.warning(f"Cannot store atomic relaxation data for {r}")


def atomic_relaxation_store(nuclide_name, df):
    nuclide_name = nuclide_name.lower()
    folder = pathlib.Path(gate.__path__[0]) / "data" / "atomic_relaxation"
    file = f"{folder / nuclide_name}.txt"
    if df is not None:
        df.to_csv(file, index=False)
    else:
        f = open(file, "w")
        f.close()


def atomic_relaxation_load(nuclide_name):
    nuclide_name = nuclide_name.lower()
    folder = pathlib.Path(gate.__path__[0]) / "data" / "atomic_relaxation"
    file = f"{folder / nuclide_name}.txt"
    try:
        df = pandas.read_csv(file)
    except pandas.errors.EmptyDataError:
        return [], []
    except FileNotFoundError:
        raise Exception(
            f"During 'load_ion_gamma_atomic_relaxation_nds_iaea' cannot read file {nuclide_name}.txt in {folder}"
        )
    try:
        ene, w = atomic_relaxation_get_ene_weights_from_df(df)
    except:
        return [], []
    return ene, w


def lc_read_csv(url):
    req = urllib.request.Request(url)
    req.add_header(
        "User-Agent",
        "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:77.0) Gecko/20100101 Firefox/77.0",
    )
    return pandas.read_csv(urllib.request.urlopen(req))


def isomeric_transition_extract_gammas(ion, verbose=False):
    a = ion.a
    z = ion.z

    # get all channels and gammas for this ion
    g = gate.GammaFromIonDecayExtractor(z, a, verbose=verbose)
    g.extract()
    gammas = g.gammas

    # create the final arrays of energy and weights
    energies = [g.transition_energy for g in gammas]
    weights = [g.final_intensity for g in gammas]

    return energies, weights


def isomeric_transition_read_from_g4_data(a, z, ignore_zero_deex=True):
    # get folder
    data_paths = g4.get_G4_data_paths()
    folder = pathlib.Path(data_paths["G4LEVELGAMMADATA"])
    ion_filename = folder / f"z{z}.a{a}"
    with open(ion_filename) as file:
        lines = [line for line in file]
    levels = Box()
    i = 0
    keV = gate.g4_units("keV")
    while i < len(lines) - 1:
        l = Box()
        words = lines[i].split()
        # 1)An integer defining the order index of the level starting by 0  for the ground state
        l.order_level = words[0]
        # 2)A string  defining floating level  (-,+X,+Y,+Z,+U,+V,+W,+R,+S,+T,+A,+B,+C)
        l.floating_level = words[1]
        # 3) Excitation energy of the level (keV)
        l.excitation_energy = float(words[2]) * keV
        # 4) Level half-life (s). A -1 half-life means a stable ground state.
        l.half_life = words[3]
        # 5) JPi information of the level.
        # 6) n_gammas= Number of possible gammas deexcitation channel from the level.
        l.n_gammas = int(words[5])
        # if no channel, we (may) ignore
        if ignore_zero_deex and l.n_gammas == 0:
            i += 1
            continue
        l.daugthers = Box()
        i += 1
        for j in range(0, l.n_gammas):
            a = isomeric_transition_read_one_gamma_deex_channel_line(lines[i])
            l.daugthers[a.daughter_order] = a
            i += 1
        levels[l.order_level] = l
    return levels


def isomeric_transition_read_one_gamma_deex_channel_line(line):
    keV = gate.g4_units("keV")
    words = line.split()
    l = Box()
    # 1) The order number of the daughter level.
    l.daughter_order = int(words[0])
    # 2) The energy of the gamma transition.
    l.transition_energy = float(words[1]) * keV
    # 3) The relative gamma emission intensity.
    l.intensity = float(words[2])
    """
    4)The multipolarity number with 1,2,3,4,5,6,7 representing E0,E1,M1,E2,M2,E3,M3  monopole transition
       and  100*Nx+Ny representing multipolarity transition with Ny and Ny taking the value 1,2,3,4,5,6,7
       referring to   E0,E1,M1,E2,M2,E3,M3,.. For example a M1+E2 transition would be written 304.
       A value of 0 means an unknown multipolarity.
    5)The multipolarity mixing ratio. O means that either the transition is a E1,M1,E2,M2 transition
        or the multipolarity mixing ratio is not given in ENSDF.
    6) Total internal conversion coefficient : alpha = Ic/Ig
     Note1: total transition is the sum of gamma de-excitation and internal
          conversion. Therefore total branching ratio is proportional to
          (1+alpha)*Ig
     Note2: total branching ratios from a given level do not always sum up to
          100%. They are re-normalized internally.
     Note3: relative probabilities for gamma de-excitation and internal conversion
          are 1/(1+alpha) and alpha/(1+alpha) respectively
    """
    l.alpha = float(words[5])
    return l


def isomeric_transition_read_from_file(filename):
    with open(filename) as infile:
        s = infile.read()
        data = jsonpickle.decode(s)
    return data


def get_tac_from_decay(ion_name, daugther, start_activity, start_time, end_time, bins):
    """
    The following will be modified according to the TAC:
    ui.start_time, ui.end_time, ui.activity.

    param is ui.tac_from_decay_parameters
    param is a dict with:
    - nuclide: a Nuclide object from radioactivedecay module, with the main ion
    - daughter: the daughter for which we compute the intensity in the time intervals
    - bins: number of bins for the discretised TAC

    - run_timing_intervals: is the list of time range from the Simulation
    """
    ion = rd.Inventory({ion_name: 1.0}, "Bq")
    sec = gate.g4_units("s")
    times = np.linspace(start_time, end_time, num=bins, endpoint=True)
    activities = []
    max_a = 0
    min_a = start_activity
    start_time = -1
    for t in times:
        x = ion.decay(t / sec, "s")
        intensity = x.activities()[daugther.nuclide.nuclide]
        a = intensity * start_activity
        activities.append(a)
        if start_time == -1 and a > 0:
            start_time = t
        if a > max_a:
            max_a = a
        if a < min_a:
            min_a = a

    """print(
        f"{daugther.nuclide.nuclide} time range {start_time / sec}  {end_time / sec} "
        f": {start_time / sec} {min_a / Bq} {max_a / Bq}"
    )"""
    return times, activities


class NumpyArrayHandler(jsonpickle.handlers.BaseHandler):
    def flatten(self, obj, data):
        return obj.tolist()

    def restore(self, obj):
        return np.array(obj)


def gid_build_all_sub_sources(ui):
    """
    Build all gamma sources for the given nuclide
    all isomeric transition gammas and all atomic relaxation fluo x-rays
    """
    # consider the user ion
    words = ui.particle.split(" ")
    if not ui.particle.startswith("ion") or len(words) != 3:
        gate.fatal(
            f"The 'ion' option of user_info must be 'ion Z A', while it is {ui.ion}"
        )
    z = int(words[1])
    a = int(words[2])

    if ui.isomeric_transition_flag:
        gid_build_all_sub_sources_isomeric_transition(ui, z, a)

    if ui.atomic_relaxation_flag:
        gid_build_all_sub_sources_atomic_relaxation(ui, z, a)

    if not ui.isomeric_transition_flag and not ui.atomic_relaxation_flag:
        gate.fatal(
            f"Error 'isomeric_transition_flag' or 'atomic_relaxation_flag' "
            f"must be True for the source {ui.name}"
        )


def gid_build_all_sub_sources_atomic_relaxation(ui, z, a):
    # get list of decay ions
    id = int(f"{z:3}{a:3}0000")
    first_nuclide = rd.Nuclide(id)
    ui.daughters = get_nuclide_progeny(first_nuclide)
    for daughter in ui.daughters:
        ene, w = gate.atomic_relaxation_load(daughter.nuclide.nuclide)
        if len(ene) > 0:
            s = gid_build_one_sub_source(
                "atomic_relaxation", ui, daughter, ene, w, first_nuclide
            )
            if s:
                ui.ui_sub_sources.append(s)


def gid_build_all_sub_sources_isomeric_transition(ui, z, a):
    """
    Build (or read from file) all isomeric transition gammas for all daughters in the decay
    """
    # read from file ?
    read_data = None
    if ui.load_from_file:
        read_data = isomeric_transition_read_from_file(ui.load_from_file)

    # get list of decay ions
    id = int(f"{z:3}{a:3}0000")
    first_nuclide = rd.Nuclide(id)
    ui.daughters = get_nuclide_progeny(first_nuclide)
    ui.log += f"Initial nuclide : {first_nuclide.nuclide}   z={z} a={a}\n"
    if ui.load_from_file:
        ui.log += f"Read from file {ui.load_from_file} \n"
    ui.log += f"Daughters {len(ui.daughters)}\n\n"

    # loop to add all sources, we copy all options and update the info
    data_to_save = {}
    for daughter in ui.daughters:
        if read_data is None:
            ion_gamma_daughter = Box({"z": daughter.nuclide.Z, "a": daughter.nuclide.A})
            ene, w = gate.isomeric_transition_extract_gammas(
                ion_gamma_daughter, verbose=False
            )
        else:
            n = daughter.nuclide.nuclide
            if n not in read_data:
                ui.log += f" no gamma. Ignored\n"
                continue
            ene = read_data[n]["ene"]
            w = read_data[n]["w"]
        s = gid_build_one_sub_source(
            "isomeric_transition", ui, daughter, ene, w, first_nuclide
        )
        if s:
            ui.ui_sub_sources.append(s)

        # output ?
        if ui.write_to_file is not None:
            n = daughter.nuclide.nuclide
            data_to_save[n] = {}
            data_to_save[n]["ene"] = ene
            data_to_save[n]["w"] = w

    # save to file ?
    if ui.write_to_file is not None:
        jsonpickle.handlers.registry.register(np.ndarray, NumpyArrayHandler)
        frozen = jsonpickle.encode(data_to_save)
        with open(ui.write_to_file, "w") as outfile:
            outfile.write(frozen)


def gid_build_one_sub_source(stype, ui, daughter, ene, w, first_nuclide):
    nuclide = daughter.nuclide
    ion_gamma_daughter = Box({"z": nuclide.Z, "a": nuclide.A})
    ui.log += f"{nuclide.nuclide} {stype} z={nuclide.Z} a={nuclide.A} "
    if len(ene) == 0:
        ui.log += f" no gamma. Ignored\n"
        return None
    ui.log += f" {len(ene)} gammas, with total weights = {np.sum(w) * 100:.2f}%\n"
    s = copy.deepcopy(ui)
    s.ui_sub_sources = None
    s._name = f"{ui.name}_{stype}_{daughter.nuclide.nuclide}"
    # additional info, specific to ion gamma source
    s.particle = "gamma"
    # set gamma lines
    s.energy.type = "spectrum_lines"
    s.energy.ion_gamma_mother = Box({"z": first_nuclide.Z, "a": first_nuclide.A})
    s.energy.ion_gamma_daughter = ion_gamma_daughter
    s.energy.spectrum_weight = w
    s.energy.spectrum_energy = ene
    # prepare times and activities that will be set during initialisation
    s.tac_from_decay_parameters = {
        "ion_name": first_nuclide,
        "daughter": daughter,
        "bins": ui.tac_bins,
    }
    return s
