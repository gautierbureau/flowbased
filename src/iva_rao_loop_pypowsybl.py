"""
IVA avec RAO dans la boucle — corriger AVANT de couper (pypowsybl + OpenRAO)
===========================================================================
Incrément de `iva_validation_pypowsybl.py`.

Dans le premier script, dès qu'un sommet du domaine était non sécurisable, le
GRT appliquait directement un IVA (il réduisait le RAM). Ici, on ajoute
l'étape réaliste : à chaque point de validation, le GRT demande D'ABORD à
OpenRAO / CASTOR si une **action corrective** suffit à sécuriser le point ;
il n'applique un **IVA** (réduction de capacité) que si la RAO échoue.

  secure sans action        -> rien à faire
  sécurisé par une RAO      -> capacité GARDÉE (pas d'IVA)
  RAO insuffisante          -> IVA (capacité réduite)

Pourquoi ce script tourne sur le réseau UCTE 12 nœuds (data/rao/) et non sur
le triangle 3 zones : sur le triangle, la contrainte qui mord est un flux
*post-incident radial* qu'aucune action corrective ne peut soulager (la RAO
n'aurait jamais rien à apporter). Le réseau 12 nœuds possède un vrai PST belge
qui soulage réellement une congestion Belgique–France — on peut donc voir la
RAO réussir, puis échouer quand on pousse plus loin.

Chaque « scénario » ci-dessous est un point d'exploitation de plus en plus
tendu (analogue à un sommet extrême du domaine que le GRT doit valider).

Algorithme RAO : provider `SearchTreeRao` = CASTOR, objectif MAX_MIN_MARGIN
(cf. rao_parameters.json), avec calcul des loop-flows (d'où la GLSK).

Dépendances : pip install pypowsybl pandas
"""

from pathlib import Path

import pandas as pd
import pypowsybl as pp
from pypowsybl.rao import Parameters as RaoParameters, Crac, Glsk as RaoGlsk

pd.set_option("display.width", 200)

DATA = Path(__file__).resolve().parents[1] / "data" / "rao"
NET = str(DATA / "rao_network.uct")
CRAC = str(DATA / "rao_crac.json")
PARM = str(DATA / "rao_parameters.json")
GLSK = str(DATA / "rao_glsk.xml")

PST = "BBE2AA1  BBE3AA1  1"          # transformateur déphaseur belge (l'action corrective)
MON = "BBE2AA1  FFR3AA1  1"          # CNEC surveillé (interconnexion Belgique–France)

# Jugement opérationnel du GRT : la limite réellement *sécurisable* sur ce CNEC
# vaut 4600 MW (au lieu de la TATL de 5000 MW retenue par le marché).
OP_LIMIT = 4600.0

# Axe de stress : la Belgique exporte de plus en plus vers la France
# (BBE2 monte, FFR3 descend) — ce qui charge progressivement MON.
STRESS = [4000, 4600, 4900, 5000, 5300, 5800]     # MW de décalage (dP)


def stressed_network(dP):
    net = pp.network.load(NET)
    net.update_generators(id=["BBE2AA1 _generator", "FFR3AA1 _generator"],
                          target_p=[3000 + dP, 3000 - dP])
    return net


def flow_on_mon(net):
    pp.loadflow.run_dc(net)
    return float(net.get_lines()["p1"][MON])


def rao_optimal_tap(net):
    """Appelle OpenRAO / CASTOR (SearchTreeRao, MAX_MIN_MARGIN) et renvoie le
    tap optimal du PST pour ce point d'exploitation."""
    crac = Crac.from_file_source(net, CRAC)
    params = RaoParameters.from_file_source(PARM)
    result = pp.rao.create_rao().run(
        crac, net, params, rao_provider="SearchTreeRao",
        loop_flow_glsk=RaoGlsk.from_file_source(GLSK))
    return int(result.get_pst_range_action_results()["optimized_tap"].iloc[0])


print("=" * 78)
print(" IVA avec RAO dans la boucle — corriger AVANT de couper")
print("=" * 78)
print(f"CNEC surveillé : {MON.strip()}")
print(f"Limite sécurisable jugée par le GRT (op_limit) : {OP_LIMIT:.0f} MW")
print(f"Action corrective disponible : PST '{PST.strip()}' (via OpenRAO / CASTOR)\n")

rows = []
n_secure = n_rao = n_iva = 0
for dP in STRESS:
    net = stressed_network(dP)
    f0 = flow_on_mon(net)                       # flux sans action corrective

    tap = rao_optimal_tap(net)                  # <-- OpenRAO / CASTOR
    net.update_phase_tap_changers(id=[PST], tap=[tap])
    f1 = flow_on_mon(net)                        # flux après action corrective

    if abs(f0) <= OP_LIMIT + 1e-6:
        verdict, iva = "SÉCURISÉ (sans action)", 0.0
        n_secure += 1
    elif abs(f1) <= OP_LIMIT + 1e-6:
        verdict, iva = "SÉCURISÉ PAR RAO (capacité gardée)", 0.0
        n_rao += 1
    else:
        verdict, iva = "IVA REQUIS (capacité réduite)", abs(f1) - OP_LIMIT
        n_iva += 1

    rows.append([dP, round(f0, 1), tap, round(f1, 1),
                 round(abs(f1) - abs(f0), 1), verdict, round(iva, 1)])

df = pd.DataFrame(rows, columns=[
    "stress_dP", "flux_sans_RA", "tap_RAO", "flux_avec_RA",
    "effet_RA", "verdict", "IVA_MW"])
print(df.to_string(index=False))

# ---------------------------------------------------------------------
# Synthèse : ce que la RAO apporte
# ---------------------------------------------------------------------
relief = df.flux_sans_RA.abs().to_numpy() - df.flux_avec_RA.abs().to_numpy()
print("\n" + "-" * 78)
print(f"Soulagement moyen de la RAO sur le CNEC : {relief.mean():.0f} MW "
      f"(PST au tap {int(df.tap_RAO.mode().iloc[0]):+d}).")
print(f"Scénarios : {n_secure} sécurisés sans action, "
      f"{n_rao} sécurisés PAR LA RAO (IVA évité), {n_iva} nécessitant un IVA.")
print("\nLecture : la RAO déplace le seuil au-delà duquel il faut couper la")
print("capacité. Dans les scénarios « SÉCURISÉ PAR RAO », le GRT valide en")
print("GARDANT la capacité — l'IVA n'intervient que lorsque même la meilleure")
print("action corrective ne suffit plus. IVA et RAO sont les deux leviers de")
print("la validation : corriger d'abord, couper en dernier recours.")
print("\nTerminé.")
