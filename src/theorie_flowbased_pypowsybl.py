"""
Théorie du flow-based illustrée AVEC pypowsybl
==============================================
Toute la PHYSIQUE est calculée par pypowsybl :
  - PTDF nodal            (analyse de sensibilité DC)
  - PTDF zonal via GSK    (zones + shift keys)
  - flux de référence     (load-flow DC)
  - PTDF post-contingence (CNEC : sensibilité en N-1)
  - vérification des sommets du domaine (load-flow DC à chaque sommet)

La GÉOMÉTRIE du domaine (intersection des contraintes -> sommets -> tracé)
est faite en pur Python par-dessus les PTDF/RAM fournis par pypowsybl.

Réseau : triangle A-B-C, 3 lignes de réactances égales, slack = C.
Dépendances : pip install pypowsybl numpy matplotlib
"""

import itertools
from pathlib import Path
import numpy as np
import pandas as pd
import pypowsybl as pp
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

FIG = Path(__file__).resolve().parents[1] / "figures"
FIG.mkdir(exist_ok=True)

pd.set_option("display.float_format", lambda v: f"{v:+.4f}")

X = 10.0
BRANCHES = ["L_AB", "L_BC", "L_AC"]

# --- paramètres load-flow / sensibilité : DC + slack unique sur C ---
LF = pp.loadflow.Parameters(
    dc=True, distributed_slack=False,
    provider_parameters={"slackBusSelectionMode": "NAME", "slackBusesIds": "VL_C"})
SP = pp.sensitivity.Parameters(load_flow_parameters=LF)


def build_network(pa=0.0, pb=0.0):
    """Triangle A-B-C ; injections pa en A, pb en B, C = slack (absorbe le solde)."""
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


# =====================================================================
# 1) PTDF NODAL (pypowsybl)
# =====================================================================
net = build_network()
sa = pp.sensitivity.create_dc_analysis()
sa.add_branch_flow_factor_matrix(BRANCHES, ["G_A", "G_B", "G_C"])
res = sa.run(net, SP, "OpenLoadFlow")
ptdf = res.get_sensitivity_matrix(); ptdf.index = ["A", "B", "C"]
print("=== 1) PTDF NODAL (pypowsybl, slack = C) ===")
print(ptdf, "\n")

# =====================================================================
# 2) PTDF ZONAL via GSK (pypowsybl)
# =====================================================================
zones = [pp.sensitivity.create_zone_from_injections_and_shift_keys(z, [f"G_{z}"], [1.0])
         for z in "ABC"]
sa2 = pp.sensitivity.create_dc_analysis(); sa2.set_zones(zones)
sa2.add_branch_flow_factor_matrix(BRANCHES, list("ABC"))
ptdf_z = sa2.run(net, SP, "OpenLoadFlow").get_sensitivity_matrix()
print("=== 2) PTDF ZONAL zone->hub (pypowsybl, GSK) ===")
print(ptdf_z, "\n")

# =====================================================================
# 3) PTDF POST-CONTINGENCE : CNEC L_BC | L_AC hors service (pypowsybl)
# =====================================================================
sa3 = pp.sensitivity.create_dc_analysis()
sa3.add_single_element_contingency("L_AC")
sa3.add_branch_flow_factor_matrix(["L_BC"], ["G_A", "G_B", "G_C"])
cnec_ptdf = sa3.run(net, SP, "OpenLoadFlow").get_sensitivity_matrix(contingency_id="L_AC")
cnec_ptdf.index = ["A", "B", "C"]
print("=== 3) PTDF post-contingence L_BC | L_AC (pypowsybl) ===")
print(cnec_ptdf, "\n")

# =====================================================================
# 4) CNEC + RAM  (Fmax/FRM choisis ; F_ref = 0, référence à plat)
# =====================================================================
# (a, b) = (PTDF_A, PTDF_B) lus depuis pypowsybl ci-dessus
CNECS = [
    dict(name="L_AB",             a=ptdf.loc["A","L_AB"], b=ptdf.loc["B","L_AB"], fmax=250, frm=50),
    dict(name="L_BC",             a=ptdf.loc["A","L_BC"], b=ptdf.loc["B","L_BC"], fmax=360, frm=60),
    dict(name="L_AC",             a=ptdf.loc["A","L_AC"], b=ptdf.loc["B","L_AC"], fmax=360, frm=60),
    dict(name="L_BC | L_AC",      a=cnec_ptdf.loc["A","L_BC"], b=cnec_ptdf.loc["B","L_BC"],
         fmax=600, frm=100, outage="L_AC", monitored="L_BC"),
]
for c in CNECS:
    c["ram"] = c["fmax"] - c["frm"]          # F_ref = 0
print("=== 4) CNEC et RAM (RAM = Fmax - FRM, F_ref = 0) ===")
print(pd.DataFrame(CNECS)[["name","a","b","fmax","frm","ram"]].to_string(index=False), "\n")

# =====================================================================
# 5) DOMAINE : contraintes -> sommets  (géométrie, pur Python)
# =====================================================================
# variables x = dNP_A, y = dNP_B ; deux demi-plans par CNEC (+/-)
H = []  # (a, b, c) pour a*x + b*y <= c
for c in CNECS:
    H.append((c["a"],  c["b"],  c["ram"]))
    H.append((-c["a"], -c["b"], c["ram"]))

def feasible(x, y, eps=1e-6):
    return all(a*x + b*y <= c + eps for a, b, c in H)

verts = []
for (a1,b1,c1), (a2,b2,c2) in itertools.combinations(H, 2):
    M = np.array([[a1,b1],[a2,b2]]); 
    if abs(np.linalg.det(M)) < 1e-9: 
        continue
    x, y = np.linalg.solve(M, [c1, c2])
    if feasible(x, y):
        verts.append((round(x,3), round(y,3)))
verts = sorted(set(verts), key=lambda p: np.arctan2(p[1], p[0]))
V = np.array(verts)
print(f"=== 5) SOMMETS DU DOMAINE ({len(verts)}) ===")
dfv = pd.DataFrame(verts, columns=["dNP_A","dNP_B"])
dfv["dNP_C"] = -(dfv.dNP_A + dfv.dNP_B)
print(dfv.to_string(index=False), "\n")

# =====================================================================
# 6) VÉRIFICATION DES SOMMETS PAR LOAD-FLOW pypowsybl
#    à chaque sommet, le flux LF sur les CNEC actifs doit valoir +/- RAM
# =====================================================================
def lf_flow(pa, pb, outage=None):
    n = build_network(pa, pb)
    if outage:
        n.update_lines(id=[outage], connected1=[False], connected2=[False])
    pp.loadflow.run_dc(n, LF)
    return n.get_lines()["p1"]

print("=== 6) VÉRIFICATION pypowsybl : flux LF aux sommets ===")
ok = True
for x, y in verts:
    base = lf_flow(x, y)
    for c in CNECS:
        flow = (lf_flow(x, y, c["outage"])[c["monitored"]] if c.get("outage")
                else base[c["name"]])
        if abs(abs(flow) - c["ram"]) < 1e-3:      # CNEC actif à ce sommet
            tag = "OK" if abs(abs(flow) - c["ram"]) < 1e-3 else "!!"
            print(f"  sommet ({x:+7.1f},{y:+7.1f})  CNEC {c['name']:<11} "
                  f"flux LF = {flow:+8.1f}  (RAM = {c['ram']:.0f})  [{tag}]")
print()

# =====================================================================
# 7) TRACÉ DU DOMAINE
# =====================================================================
fig, ax = plt.subplots(figsize=(7, 7))
lim = 650
xs = np.linspace(-lim, lim, 400)
for c in CNECS:                       # droites des CNEC (les 2 sens)
    for s in (+1, -1):
        a, b, r = s*c["a"], s*c["b"], c["ram"]
        if abs(b) > 1e-9:
            ax.plot(xs, (r - a*xs)/b, color="0.8", lw=0.8, zorder=1)
poly = plt.Polygon(V, closed=True, facecolor="#1F5C99", alpha=0.15,
                   edgecolor="#1F5C99", lw=2.2, zorder=2)
ax.add_patch(poly)
ax.scatter(V[:,0], V[:,1], color="#1F5C99", zorder=3, s=28)
for (x, y) in verts:                  # étiquette de sommet
    ax.annotate(f"({x:.0f},{y:.0f})", (x, y), textcoords="offset points",
                xytext=(6, 4), fontsize=8, color="#1F5C99")
ax.axhline(0, color="0.5", lw=0.6); ax.axvline(0, color="0.5", lw=0.6)
ax.set_xlim(-lim, lim); ax.set_ylim(-lim, lim); ax.set_aspect("equal")
ax.set_xlabel(r"$\Delta NP_A$  (MW)"); ax.set_ylabel(r"$\Delta NP_B$  (MW)")
ax.set_title("Domaine flow-based (PTDF & RAM issus de pypowsybl)")
fig.tight_layout()
fig.savefig(FIG / "domaine_flowbased.png", dpi=130)
fig.savefig(FIG / "domaine_flowbased.pdf")
print(f"Tracé enregistré dans {FIG}/domaine_flowbased.png / .pdf")
