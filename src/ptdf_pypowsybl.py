"""
Calcul des PTDF sur un réseau triangle à 3 zones (A, B, C).
================================================================
Deux calculs sont menés en parallèle et comparés :

  (1) THEORIE  -- PTDF = Bd · A · X   (load-flow DC, à la main avec NumPy)
  (2) OUTIL    -- pypowsybl (moteur OpenLoadFlow, analyse de sensibilité DC)

Le réseau : 3 noeuds reliés en triangle par 3 lignes de réactances égales.
Slack (noeud de référence) = C.  Résultat attendu : PTDF = 1/3 et 2/3,
et PTDF_C = 0.  Ce sont exactement les valeurs du domaine flow-based
de l'exemple à 3 zones.

Dépendances : pip install pypowsybl numpy pandas
"""

import numpy as np
import pandas as pd
import pypowsybl as pp

pd.set_option("display.float_format", lambda v: f"{v:+.4f}")

# =====================================================================
# (1) PTDF ANALYTIQUE — formulation matricielle du load-flow DC
# =====================================================================
# Ordre des noeuds : A=0, B=1, C=2   (slack = C)
# Lignes orientées : L_AB (A->B), L_BC (B->C), L_AC (A->C)
nodes = ["A", "B", "C"]
slack = 2                      # indice du noeud C
X = 10.0                       # réactance identique sur les 3 lignes
b = 1.0 / X                    # susceptance de branche

# Matrice d'incidence branche x noeud (+1 origine, -1 extrémité)
A = np.array([
    [+1, -1,  0],   # L_AB
    [ 0, +1, -1],   # L_BC
    [+1,  0, -1],   # L_AC
], dtype=float)
Bd = np.diag([b, b, b])                 # susceptances de branche
Bbus = A.T @ Bd @ A                      # matrice nodale (Laplacien pondéré)

# Inversion réduite : on retire la ligne/colonne du slack, on inverse, on ré-emboîte
keep = [i for i in range(3) if i != slack]
Xmat = np.zeros((3, 3))
Xmat[np.ix_(keep, keep)] = np.linalg.inv(Bbus[np.ix_(keep, keep)])

PTDF_theo = Bd @ A @ Xmat                # (branches x noeuds), colonnes = injections
branches = ["L_AB", "L_BC", "L_AC"]
df_theo = pd.DataFrame(PTDF_theo, index=branches, columns=nodes).T
print("=== (1) PTDF analytique  PTDF = Bd·A·X  (slack = C) ===")
print(df_theo, "\n")

# =====================================================================
# (2) Le même réseau dans pypowsybl
# =====================================================================
n = pp.network.create_empty("triangle-3-zones")
n.create_substations(id=["S_A", "S_B", "S_C"])
n.create_voltage_levels(
    id=["VL_A", "VL_B", "VL_C"],
    substation_id=["S_A", "S_B", "S_C"],
    topology_kind=["BUS_BREAKER"] * 3,
    nominal_v=[400.0] * 3,
)
n.create_buses(id=["A", "B", "C"], voltage_level_id=["VL_A", "VL_B", "VL_C"])
n.create_lines(
    id=branches,
    voltage_level1_id=["VL_A", "VL_B", "VL_A"], bus1_id=["A", "B", "A"],
    voltage_level2_id=["VL_B", "VL_C", "VL_C"], bus2_id=["B", "C", "C"],
    r=[0.0] * 3, x=[X, X, X],
    g1=[0.0] * 3, b1=[0.0] * 3, g2=[0.0] * 3, b2=[0.0] * 3,
)
# une injection par noeud (sert de variable de sensibilité)
n.create_generators(
    id=["G_A", "G_B", "G_C"],
    voltage_level_id=["VL_A", "VL_B", "VL_C"], bus_id=["A", "B", "C"],
    target_p=[100.0, 100.0, 0.0], min_p=[-1e3] * 3, max_p=[1e3] * 3,
    target_q=[0.0] * 3, voltage_regulator_on=[False] * 3,
)
n.create_loads(id=["LD_C"], voltage_level_id=["VL_C"], bus_id=["C"],
               p0=[200.0], q0=[0.0])

# Paramètres : mode DC + slack UNIQUE forcé sur le noeud C (via son voltage level)
lf = pp.loadflow.Parameters(
    dc=True, distributed_slack=False,
    provider_parameters={"slackBusSelectionMode": "NAME", "slackBusesIds": "VL_C"},
)
params = pp.sensitivity.Parameters(load_flow_parameters=lf)

# ---- PTDF nodal ----
sa = pp.sensitivity.create_dc_analysis()
sa.add_branch_flow_factor_matrix(branches_ids=branches,
                                 variables_ids=["G_A", "G_B", "G_C"])
res = sa.run(n, params, provider="OpenLoadFlow")
ptdf_pp = res.get_sensitivity_matrix()
ptdf_pp.index = ["A", "B", "C"]           # renomme G_x -> x
print("=== (2) PTDF pypowsybl (slack = C) ===")
print(ptdf_pp, "\n")

print("--- Flux de référence (MW) ---")
print(res.get_reference_matrix(), "\n")

# ---- Vérification théorie == outil ----
assert np.allclose(df_theo.values, ptdf_pp.loc[["A", "B", "C"], branches].values,
                   atol=1e-6), "Écart entre théorie et pypowsybl !"
print(">>> OK : PTDF analytiques et pypowsybl identiques (écart < 1e-6)\n")

# =====================================================================
# (3) PTDF ZONAL — zones définies par des GSK (Generation Shift Keys)
# =====================================================================
zones = [
    pp.sensitivity.create_zone_from_injections_and_shift_keys("A", ["G_A"], [1.0]),
    pp.sensitivity.create_zone_from_injections_and_shift_keys("B", ["G_B"], [1.0]),
    pp.sensitivity.create_zone_from_injections_and_shift_keys("C", ["G_C"], [1.0]),
]
sa2 = pp.sensitivity.create_dc_analysis()
sa2.set_zones(zones)
sa2.add_branch_flow_factor_matrix(branches_ids=branches,
                                  variables_ids=["A", "B", "C"])
res2 = sa2.run(n, params, provider="OpenLoadFlow")
print("=== (3) PTDF ZONAL zone->hub (slack = C) ===")
print(res2.get_sensitivity_matrix(), "\n")

# PTDF zone-à-zone : sensibilité d'un échange bilatéral A -> B
ptdf_z = res2.get_sensitivity_matrix()
z2z_AB = ptdf_z.loc["A"] - ptdf_z.loc["B"]
print("--- PTDF zone-à-zone (échange A->B) = PTDF_A - PTDF_B ---")
print(z2z_AB.to_frame("A->B").T, "\n")

# =====================================================================
# (4) CNEC — PTDF post-contingence (perte de L_AC)
# =====================================================================
sa3 = pp.sensitivity.create_dc_analysis()
sa3.add_single_element_contingency("L_AC")
sa3.add_branch_flow_factor_matrix(branches_ids=["L_BC"],
                                  variables_ids=["G_A", "G_B", "G_C"])
res3 = sa3.run(n, params, provider="OpenLoadFlow")
cnec = res3.get_sensitivity_matrix(contingency_id="L_AC")
cnec.index = ["A", "B", "C"]
print("=== (4) CNEC : PTDF de L_BC après perte de L_AC (réseau radial) ===")
print(cnec)
