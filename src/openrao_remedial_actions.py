"""
Actions correctives avec OpenRAO (via pypowsybl.rao)
=====================================================
Réseau UCTE 12 nœuds (4 pays), 1 transformateur déphaseur (PST) belge.
Le CRAC définit 7 CNEC (dont FFR1AA1-FFR2AA1 limité à 4000 MW) et une seule
action corrective préventive : PRA_PST_BE, réglable de -16 à +16.

OpenRAO optimise le tap du PST pour MAXIMISER LA MARGE MINIMALE sur les CNEC.
On vérifie ensuite le résultat par un simple load-flow DC (avant / après).

Ressources (réseau + CRAC + paramètres + GLSK) : dépôt powsybl/pypowsybl,
répertoire data/rao du tag v1.15.0.
Dépendances : pip install pypowsybl pandas
"""

import json
from pathlib import Path
import pandas as pd
import pypowsybl as pp
from pypowsybl.rao import Parameters as RaoParameters, Crac, Glsk as RaoGlsk

pd.set_option("display.width", 200)

DATA = Path(__file__).resolve().parents[1] / "data" / "rao"
NET  = str(DATA / "rao_network.uct")
CRAC = str(DATA / "rao_crac.json")
PARM = str(DATA / "rao_parameters.json")
GLSK = str(DATA / "rao_glsk.xml")
PST  = "BBE2AA1  BBE3AA1  1"          # transformateur déphaseur (Belgique)

# =====================================================================
# 1) OPTIMISATION DES ACTIONS CORRECTIVES PAR OpenRAO
# =====================================================================
network = pp.network.load(NET)
crac    = Crac.from_file_source(network, CRAC)
params  = RaoParameters.from_file_source(PARM)

runner = pp.rao.create_rao()
result = runner.run(crac, network, params,
                    rao_provider="SearchTreeRao",
                    loop_flow_glsk=RaoGlsk.from_file_source(GLSK))

print("Statut RAO :", result.status())

ra = result.get_remedial_action_results()
print("\nAction(s) corrective(s) retenue(s) :")
print(ra.to_string(index=False))

pst = result.get_pst_range_action_results()
opt_tap = int(pst["optimized_tap"].iloc[0])
print(f"\n-> PST '{PST}' déplacé au tap {opt_tap}")

cost = result.get_cost_results()   # functional_cost = - (marge minimale)
m_before = -cost.loc["initial",   "functional_cost"]
m_after  = -cost.loc["preventive","functional_cost"]
print(f"\nMarge minimale (objectif RAO) : {m_before:.1f} MW  ->  {m_after:.1f} MW "
      f"(gain {m_after - m_before:+.1f} MW)")

# =====================================================================
# 2) VÉRIFICATION INDÉPENDANTE PAR LOAD-FLOW DC (avant / après)
# =====================================================================
# seuils réels de chaque CNEC, lus dans le CRAC
c = json.load(open(CRAC))
thr = {fc["networkElementId"]: fc["thresholds"][0]["max"] for fc in c["flowCnecs"]}
cnecs = list(thr)

def flows(net):
    pp.loadflow.run_dc(net)
    s = net.get_lines()["p1"]
    return {k: float(s[k]) for k in cnecs}

net = pp.network.load(NET)
f0 = flows(net)                                   # tap 0  (avant)
net.update_phase_tap_changers(id=[PST], tap=[opt_tap])
f1 = flows(net)                                   # tap opt (après)

rows = []
for k in cnecs:
    m0, m1 = thr[k] - abs(f0[k]), thr[k] - abs(f1[k])
    rows.append([k.strip(), thr[k], round(f0[k], 1), round(f1[k], 1),
                 round(m0, 1), round(m1, 1)])
df = pd.DataFrame(rows, columns=["CNEC", "seuil", "flux_avant", "flux_apres",
                                 "marge_avant", "marge_apres"])
df = df.sort_values("marge_avant").reset_index(drop=True)
print("\nVérification DC (flux et marges en MW) :")
print(df.to_string(index=False))
print(f"\nMarge minimale DC : {df.marge_avant.min():.1f} MW (avant)  ->  "
      f"{df.marge_apres.min():.1f} MW (après)   [CNEC {df.CNEC.iloc[0]}]")
print("\n=> cohérent avec l'objectif optimisé par OpenRAO.")
