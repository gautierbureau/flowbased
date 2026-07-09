"""
IVA — validation d'un domaine flow-based par un GRT (pypowsybl + OpenRAO)
========================================================================
Ce script illustre, sur le réseau 3 zones du document, ce qu'un GRT fait
pendant l'étape de VALIDATION du calcul de capacité — l'IVA (*Individual
Validation Adjustment*) :

  1. on (re)construit le domaine flow-based (PTDF/RAM via pypowsybl) et ses
     sommets ;
  2. on VALIDE chaque sommet par un load-flow pypowsybl (cas de base N et
     post-incident N-1) : le GRT vérifie le flux physique sur chaque CNEC ;
  3. le GRT applique son JUGEMENT opérationnel : sur le CNEC post-incident,
     la limite réellement *sécurisable* est plus basse que la TATL utilisée
     par le calcul automatisé (raison tension / dynamique non modélisée). Il
     RÉDUIT le RAM correspondant = il applique un IVA ;
  4. on recalcule le domaine, on RE-VALIDE, et on vérifie le garde-fou
     réglementaire minRAM (70 %).

Enfin, on illustre l'ALTERNATIVE à l'IVA avec OpenRAO : plutôt que de rogner
la capacité, prouver qu'une action corrective (un PST) restaure la marge
(réseau UCTE 12 nœuds, data/rao/).

Toute la physique (PTDF, flux) vient de pypowsybl ; la géométrie du domaine
(intersection des contraintes -> sommets) est en pur Python par-dessus.

Dépendances : pip install pypowsybl numpy pandas
"""

import itertools
from pathlib import Path

import numpy as np
import pandas as pd
import pypowsybl as pp

pd.set_option("display.float_format", lambda v: f"{v:+.1f}")

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "rao"

X = 10.0
BRANCHES = ["L_AB", "L_BC", "L_AC"]

# load-flow / sensibilité : DC, slack unique sur C
LF = pp.loadflow.Parameters(
    dc=True, distributed_slack=False,
    provider_parameters={"slackBusSelectionMode": "NAME", "slackBusesIds": "VL_C"})
SP = pp.sensitivity.Parameters(load_flow_parameters=LF)


# ---------------------------------------------------------------------
# Réseau triangle A-B-C (injections en A et B, C = slack)
# ---------------------------------------------------------------------
def build_network(pa=0.0, pb=0.0):
    n = pp.network.create_empty("triangle")
    n.create_substations(id=["S_A", "S_B", "S_C"])
    n.create_voltage_levels(id=["VL_A", "VL_B", "VL_C"],
        substation_id=["S_A", "S_B", "S_C"],
        topology_kind=["BUS_BREAKER"] * 3, nominal_v=[400.0] * 3)
    n.create_buses(id=["A", "B", "C"], voltage_level_id=["VL_A", "VL_B", "VL_C"])
    n.create_lines(id=BRANCHES,
        voltage_level1_id=["VL_A", "VL_B", "VL_A"], bus1_id=["A", "B", "A"],
        voltage_level2_id=["VL_B", "VL_C", "VL_C"], bus2_id=["B", "C", "C"],
        r=[0.0] * 3, x=[X] * 3, g1=[0.0] * 3, b1=[0.0] * 3, g2=[0.0] * 3, b2=[0.0] * 3)
    n.create_generators(id=["G_A", "G_B", "G_C"],
        voltage_level_id=["VL_A", "VL_B", "VL_C"], bus_id=["A", "B", "C"],
        target_p=[pa, pb, 0.0], min_p=[-1e4] * 3, max_p=[1e4] * 3,
        target_q=[0.0] * 3, voltage_regulator_on=[False] * 3)
    return n


def nodal_ptdf(net):
    sa = pp.sensitivity.create_dc_analysis()
    sa.add_branch_flow_factor_matrix(BRANCHES, ["G_A", "G_B", "G_C"])
    m = sa.run(net, SP, "OpenLoadFlow").get_sensitivity_matrix()
    m.index = ["A", "B", "C"]
    return m


def postcont_ptdf(net, outage, monitored):
    sa = pp.sensitivity.create_dc_analysis()
    sa.add_single_element_contingency(outage)
    sa.add_branch_flow_factor_matrix([monitored], ["G_A", "G_B", "G_C"])
    m = sa.run(net, SP, "OpenLoadFlow").get_sensitivity_matrix(contingency_id=outage)
    m.index = ["A", "B", "C"]
    return m


def lf_flow(pa, pb, outage=None):
    """Flux DC (MW) sur chaque ligne pour l'injection (pa en A, pb en B)."""
    n = build_network(pa, pb)
    if outage:
        n.update_lines(id=[outage], connected1=[False], connected2=[False])
    pp.loadflow.run_dc(n, LF)
    return n.get_lines()["p1"]


# ---------------------------------------------------------------------
# Domaine : contraintes CNEC -> sommets (géométrie, pur Python)
# ---------------------------------------------------------------------
def ram(c):
    """RAM = Fmax - FRM - IVA (référence à plat : Fref = 0)."""
    return c["fmax"] - c["frm"] - c.get("iva", 0.0)


def vertices(cnecs, eps=1e-6):
    H = []  # a*x + b*y <= r  (deux demi-plans par CNEC)
    for c in cnecs:
        H += [(c["a"], c["b"], ram(c)), (-c["a"], -c["b"], ram(c))]

    def feasible(x, y):
        return all(a * x + b * y <= r + eps for a, b, r in H)

    verts = []
    for (a1, b1, r1), (a2, b2, r2) in itertools.combinations(H, 2):
        M = np.array([[a1, b1], [a2, b2]])
        if abs(np.linalg.det(M)) < 1e-9:
            continue
        x, y = np.linalg.solve(M, [r1, r2])
        if feasible(x, y):
            verts.append((round(x, 2), round(y, 2)))
    return sorted(set(verts), key=lambda p: np.arctan2(p[1], p[0]))


def poly_area(verts):
    if len(verts) < 3:
        return 0.0
    v = np.array(verts)
    x, y = v[:, 0], v[:, 1]
    return 0.5 * abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))


def flow_on(cnec, x, y):
    """Flux physique (MW) sur le CNEC au point (dNP_A, dNP_B), par load-flow."""
    if cnec.get("outage"):
        return float(lf_flow(x, y, cnec["outage"])[cnec["monitored"]])
    return float(lf_flow(x, y)[cnec["name"]])


def validate(verts, cnecs):
    """Pour chaque sommet, calcule par load-flow le flux sur chaque CNEC actif
    et le compare à la limite *sécurisable* jugée par le GRT (op_limit).
    Renvoie la liste des violations (flux > op_limit)."""
    violations = []
    for (x, y) in verts:
        for c in cnecs:
            f = flow_on(c, x, y)
            if abs(abs(f) - ram(c)) > 1e-2:      # CNEC non actif à ce sommet
                continue
            op = c.get("op_limit", c["fmax"])     # limite sécurisable du GRT
            secure = abs(f) <= op + 1e-6
            if not secure:
                violations.append(dict(x=x, y=y, cnec=c["name"], flow=f, op_limit=op))
    return violations


def show_domain(title, cnecs):
    verts = vertices(cnecs)
    df = pd.DataFrame(verts, columns=["dNP_A", "dNP_B"])
    df["dNP_C"] = -(df.dNP_A + df.dNP_B)
    print(f"\n{title} — {len(verts)} sommets, aire = {poly_area(verts):,.0f} MW²")
    print(df.to_string(index=False))
    return verts


# =====================================================================
# 1) Domaine flow-based initial (PTDF/RAM issus de pypowsybl)
# =====================================================================
print("=" * 70)
print(" 1) DOMAINE FLOW-BASED INITIAL (avant validation GRT)")
print("=" * 70)

net = build_network()
P = nodal_ptdf(net)
Pc = postcont_ptdf(net, outage="L_AC", monitored="L_BC")

CNECS = [
    dict(name="L_AB",        a=P.loc["A", "L_AB"], b=P.loc["B", "L_AB"], fmax=250, frm=50),
    dict(name="L_BC",        a=P.loc["A", "L_BC"], b=P.loc["B", "L_BC"], fmax=360, frm=60),
    dict(name="L_AC",        a=P.loc["A", "L_AC"], b=P.loc["B", "L_AC"], fmax=360, frm=60),
    dict(name="L_BC | L_AC", a=Pc.loc["A", "L_BC"], b=Pc.loc["B", "L_BC"],
         fmax=600, frm=100, outage="L_AC", monitored="L_BC",
         # >>> jugement opérationnel du GRT : sur cet élément post-incident, la
         #     limite réellement sécurisable (tension/dynamique) vaut 420 MW,
         #     pas la TATL de 600 MW utilisée par le calcul automatisé.
         op_limit=420),
]
tbl = pd.DataFrame(CNECS)
tbl["RAM"] = [ram(c) for c in CNECS]
print(tbl[["name", "a", "b", "fmax", "frm", "RAM"]].to_string(index=False))

verts0 = show_domain("Domaine initial", CNECS)

# =====================================================================
# 2) Validation de chaque sommet par load-flow (le cœur de l'IVA)
# =====================================================================
print("\n" + "=" * 70)
print(" 2) VALIDATION DE CHAQUE SOMMET PAR LOAD-FLOW pypowsybl")
print("=" * 70)
print("Pour chaque sommet actif sur le CNEC post-incident 'L_BC | L_AC',")
print("on calcule le flux physique de L_BC après perte de L_AC, et on le")
print("compare à la limite sécurisable jugée par le GRT (op_limit = 420 MW).\n")

viol = validate(verts0, CNECS)
for (x, y) in verts0:
    f = flow_on(CNECS[-1], x, y)             # L_BC | L_AC
    if abs(abs(f) - ram(CNECS[-1])) > 1e-2:  # non actif ici
        continue
    op = CNECS[-1]["op_limit"]
    tag = "OK" if abs(f) <= op + 1e-6 else "NON SÉCURISABLE"
    print(f"  sommet ({x:+7.1f},{y:+7.1f})  flux L_BC|L_AC = {f:+8.1f} MW  "
          f"(limite GRT {op:.0f})  [{tag}]")

if not viol:
    print("\n=> tous les sommets sont sécurisables : aucun IVA nécessaire.")
else:
    print(f"\n=> {len(viol)} sommet(s) NON sécurisable(s) : le flux post-incident")
    print("   dépasse la limite que le GRT sait tenir. Il doit réduire le RAM.")

# =====================================================================
# 3) Le GRT applique l'IVA : réduction du RAM du CNEC concerné
# =====================================================================
print("\n" + "=" * 70)
print(" 3) LE GRT APPLIQUE L'IVA (Individual Validation Adjustment)")
print("=" * 70)

c = CNECS[-1]                        # L_BC | L_AC
ram_before = ram(c)
iva = max(0.0, ram_before - c["op_limit"])   # on ramène le RAM à la limite sûre
c["iva"] = iva
ram_after = ram(c)
print(f"CNEC '{c['name']}' : RAM {ram_before:.0f} -> {ram_after:.0f} MW "
      f"(IVA appliqué = {iva:.0f} MW)")

verts1 = show_domain("Domaine après IVA", CNECS)
print(f"\nRéduction d'aire du domaine : "
      f"{poly_area(verts0):,.0f} -> {poly_area(verts1):,.0f} MW² "
      f"({100 * (1 - poly_area(verts1) / poly_area(verts0)):.1f} % en moins).")

# =====================================================================
# 4) Re-validation + garde-fou minRAM (70 %)
# =====================================================================
print("\n" + "=" * 70)
print(" 4) RE-VALIDATION ET GARDE-FOU minRAM (70 %)")
print("=" * 70)

viol2 = validate(verts1, CNECS)
if not viol2:
    print("Re-validation : tous les sommets du nouveau domaine sont "
          "sécurisables. [OK]")
else:
    print(f"Re-validation : {len(viol2)} sommet(s) encore non sécurisable(s).")

floor = 0.7 * c["fmax"]
print(f"\nminRAM : RAM = {ram_after:.0f} MW  vs  plancher 0,7 x Fmax = {floor:.0f} MW  "
      f"-> {'au plancher' if abs(ram_after - floor) < 1e-6 else ('OK' if ram_after >= floor else 'SOUS LE PLANCHER !')}")
print("Le GRT ne peut pas réduire davantage sans enfreindre le minRAM : toute")
print("IVA supplémentaire devrait être justifiée auprès du régulateur.")

# =====================================================================
# 5) Alternative à l'IVA : action corrective via OpenRAO
# =====================================================================
print("\n" + "=" * 70)
print(" 5) ALTERNATIVE À L'IVA : UNE ACTION CORRECTIVE (OpenRAO)")
print("=" * 70)
print("Plutôt que de rogner la capacité (IVA), un GRT peut valider en prouvant")
print("qu'une action corrective restaure la marge. Démonstration sur le réseau")
print("UCTE 12 nœuds (PST belge) fourni dans data/rao/.\n")

try:
    from pypowsybl.rao import Parameters as RaoParameters, Crac, Glsk as RaoGlsk

    need = ["rao_network.uct", "rao_crac.json", "rao_parameters.json", "rao_glsk.xml"]
    missing = [f for f in need if not (DATA / f).exists()]
    if missing:
        raise FileNotFoundError(f"ressources absentes : {missing} "
                                f"(récupérables via scripts/fetch_rao_data.sh)")

    network = pp.network.load(str(DATA / "rao_network.uct"))
    crac = Crac.from_file_source(network, str(DATA / "rao_crac.json"))
    params = RaoParameters.from_file_source(str(DATA / "rao_parameters.json"))
    result = pp.rao.create_rao().run(
        crac, network, params, rao_provider="SearchTreeRao",
        loop_flow_glsk=RaoGlsk.from_file_source(str(DATA / "rao_glsk.xml")))

    cost = result.get_cost_results()          # functional_cost = -(marge min)
    m_before = -cost.loc["initial", "functional_cost"]
    m_after = -cost.loc["preventive", "functional_cost"]
    tap = int(result.get_pst_range_action_results()["optimized_tap"].iloc[0])
    print(f"Statut RAO : {result.status()}")
    print(f"Action retenue : PST au tap {tap:+d}")
    print(f"Marge minimale : {m_before:.1f} -> {m_after:.1f} MW "
          f"(gain {m_after - m_before:+.1f} MW).")
    print("\n=> Ici l'action corrective RELÈVE la marge : le GRT peut valider en")
    print("   GARDANT la capacité, au lieu de la réduire par un IVA. IVA et RAO")
    print("   sont les deux leviers de la validation : couper, ou corriger.")
except Exception as exc:                       # OpenRAO indisponible / données absentes
    print(f"[OpenRAO non exécuté : {exc}]")
    print("Le raisonnement reste valable : si une action corrective sécurise le")
    print("réseau, le GRT peut garder la capacité plutôt qu'appliquer un IVA.")

print("\nTerminé.")
