# -*- coding: utf-8 -*-
"""
Moteur de calcul - Autoconsommation Collective (ACC)
Projet IBC
"""
import os
import numpy as np
import pandas as pd
import math
import pulp
from typing import Dict, Tuple
import requests
import plotly.express as px
import plotly.graph_objects as go
from fpdf import FPDF
import datetime
import time
import streamlit as st

# =====================================================================
# BLOC 1 : GÉOLOCALISATION ET PÉRIMÈTRE LÉGAL
# =====================================================================

def calculer_distance_gps(lat1, lon1, lat2, lon2):
    """
    Calcule la distance en kilomètres entre 2 points GPS (Haversine).
    """
    R = 6371.0 # Rayon de la Terre en km
    lat1_rad, lon1_rad = math.radians(lat1), math.radians(lon1)
    lat2_rad, lon2_rad = math.radians(lat2), math.radians(lon2)
    
    # Distance euclidienne
    dlon = lon2_rad - lon1_rad
    dlat = lat2_rad - lat1_rad
    d = 2 * R * math.asin(math.sqrt(math.sin(dlat/2)**2 + math.cos(lat1_rad)*math.cos(lat2_rad)*math.sin(dlon/2)**2))
    return d

def charger_base_territoires(chemin_csv: str) -> pd.DataFrame:
    """
    Charge le CSV de l'Observatoire des Territoires en mémoire (Loi ACC).
    """

    try:
        df = pd.read_csv(chemin_csv, sep=';', dtype={'codgeo': str}) 
        df = df[['Code_INSEE', 'Ville', 'Niveau_INSEE']] 
        df.columns = ['Code_INSEE', 'Ville', 'Niveau_INSEE']
        df.set_index('Code_INSEE', inplace=True)
        return df
    except Exception as e:
        print(f"Erreur lors du chargement du CSV : {e}")
        return pd.DataFrame()
    
def obtenir_ville_par_gps(lat: float, lon: float):
    """
    Interroge l'API de l'Etat pour trouver la ville et le code postal à partir d'un point.
    """
    
    url = f"https://geo.api.gouv.fr/communes?lat={lat}&lon={lon}&fields=nom,code"
    try:
        reponse = requests.get(url, timeout=5).json()
        # Si l'API trouve une ville correspondant à ces coordonnées
        if len(reponse) > 0:
            nom_ville = reponse[0]['nom']
            code_insee = reponse[0]['code']
            return nom_ville, code_insee
        else:
            return "Hors de France", None
        
    except Exception as e:
        print(f"Erreur API Géo : {e}")
        return "Erreur de connexion", None

def calculer_centre_optimal(df_acteurs: pd.DataFrame, df_series: pd.DataFrame) -> dict:
    """
    Calcule le centre de gravité optimal d'un ensemble de consommateurs.
    Pondéré par la coïncidence temporelle (Solaire * Consommation).
    """
    # Trie en fonction du statut : Blacklist = supprimé
    df_valides = df_acteurs[df_acteurs['Statut'] != 'Blacklist'].copy()
    poids_solaire_total = 0
    somme_lat = 0
    somme_lon = 0
    
    # Poids = Somme(Conso acteur * Production solaire à la même heure)
    for index, acteur in df_valides.iterrows():
        id_acteur = acteur['ID_Acteur']
        if id_acteur in df_series.columns:
            coincidence = (df_series[id_acteur] * df_series['Solaire_kWh']).sum()
            somme_lat += acteur['Latitude'] * coincidence
            somme_lon += acteur['Longitude'] * coincidence
            poids_solaire_total += coincidence
            
    if poids_solaire_total == 0:
        return {'Latitude_Opti': df_valides['Latitude'].mean(), 'Longitude_Opti': df_valides['Longitude'].mean()}
    
    return {
        'Latitude_Opti': round(somme_lat / poids_solaire_total, 6),
        'Longitude_Opti': round(somme_lon / poids_solaire_total, 6)
    }

def evaluer_meilleur_scenario_acc(df_acteurs: pd.DataFrame, lat_centre: float, lon_centre: float) -> dict:
    """
    Orchestrateur Suprême de l'ACC.
    Évalue les scénarios de zonage pour trouver le plus rentable, 
    tout en respectant les statuts obligatoires (Prédéfini).
    """
    # Suppression des acteurs blacklist
    df_propre = df_acteurs[df_acteurs['Statut'] != 'Blacklist'].copy()
    # Conservations des acteurs prédéfinis (obligatoires)
    liste_predefinis = df_propre[df_propre['Statut'] == 'Predefini']['ID_Acteur'].tolist()
    
    df_propre['Distance_km'] = df_propre.apply(
        lambda row: calculer_distance_gps(lat_centre, lon_centre, row['Latitude'], row['Longitude']), axis=1
    )
    
    # Dérogation SDIS
    presence_sdis = df_propre.get('Est_SDIS', pd.Series([False]*len(df_propre))).any()
    if presence_sdis:
        candidats = df_propre[df_propre['Distance_km'] <= 10.0]
        valide = all(acteur in candidats['ID_Acteur'].values for acteur in liste_predefinis)
        if not valide: return {"Erreur": "Même avec la dérogation SDIS (10km de rayon), un acteur prédéfini est trop loin !"}
        return {"Scenario_Retenu": "Dérogation SDIS", "Rayon_Applique_km": 10.0, "Acteurs_Finaux": candidats['ID_Acteur'].tolist()}
    
    # SCÉNARIO 1 : Inclusif (Le pire niveau INSEE dicte la loi)
    pire_niveau_insee = df_propre['Niveau_INSEE'].min()
    if pire_niveau_insee <= 2: rayon_s1 = 1.0
    elif pire_niveau_insee <= 4: rayon_s1 = 5.0
    else: rayon_s1 = 10.0
        
    candidats_s1 = df_propre[df_propre['Distance_km'] <= rayon_s1]
    s1_valide = all(acteur in candidats_s1['ID_Acteur'].values for acteur in liste_predefinis)
    
    # SCÉNARIO 2 : Forçage Rural (Exclusion des zones urbaines et périurbaines)
    df_ruraux = df_propre[df_propre['Niveau_INSEE'] >= 5]
    rayon_s2 = 10.0
    candidats_s2 = df_ruraux[df_ruraux['Distance_km'] <= rayon_s2]
    s2_valide = all(acteur in candidats_s2['ID_Acteur'].values for acteur in liste_predefinis)
    
    # SCÉNARIO 3 : Forçage Périurbain (Exclusion des zones urbaines)
    df_purbains = df_propre[df_propre['Niveau_INSEE'] >= 3]
    rayon_s3 = 5.0
    candidats_s3 = df_purbains[df_purbains['Distance_km'] <= rayon_s3]
    s3_valide = all(acteur in candidats_s3['ID_Acteur'].values for acteur in liste_predefinis)
    
    # COMPARAISON
    score_s1 = candidats_s1['Conso_Annuelle_kWh'].sum() if s1_valide else 0
    score_s2 = candidats_s2['Conso_Annuelle_kWh'].sum() if s2_valide else 0
    score_s3 = candidats_s3['Conso_Annuelle_kWh'].sum() if s3_valide else 0
    
    if not s1_valide and not s2_valide and not s3_valide:
        return {"Erreur": "Impossible d'inclure tous les acteurs Prédéfinis dans les limites légales."}
        
    if score_s1 >= score_s2 and score_s1 >= score_s3:
        return {"Scenario_Retenu": "Inclusif", "Rayon_Applique_km": rayon_s1, "Acteurs_Finaux": candidats_s1['ID_Acteur'].tolist()}
    elif score_s2 >= score_s1 and score_s2 >= score_s3:
        return {"Scenario_Retenu": "Exclusion Urbaine", "Rayon_Applique_km": rayon_s2, "Acteurs_Finaux": candidats_s2['ID_Acteur'].tolist()}
    else:
        return {"Scenario_Retenu": "Exclusion Urbaine et Périurbaine", "Rayon_Applique_km": rayon_s3, "Acteurs_Finaux": candidats_s3['ID_Acteur'].tolist()}

def calculer_score_consommation(liste_acteurs:list[int], df_series: pd.DataFrame)-> Dict[int, float]:
    """
    Calcule le score de coïncidence solaire pour une liste d'acteurs.
    Renvoie la moyenne estimale et hivernale pour les heures de jour.
    """
    # Vérification et formatage de la colonne temporelle
    if not pd.api.types.is_datetime64_any_dtype(df_series["Horodate"]):
        df_series["Horodate"] = pd.to_datetime(df_series["Horodate"])
    
    # On ne conserve que les données où la production > 0
    df_jour = df_series[df_series["Production_Totale"] > 0].copy()
    prod_max = df_jour["Production_Totale"].max()
    if prod_max == 0:
        prod_max = 1.0
        
    scores_finaux = {}
    
    # Calcul des scores par acteur
    for acteur in liste_acteurs:
        # Pandas gère parfois les noms de colonnes comme des str ou des int
        col_acteur = acteur if acteur in df_series.columns else str(acteur)
        
        if col_acteur not in df_series.columns:
            scores_finaux[acteur] = 0.0
            continue
        
        # Calcul du score : Conso_t * (Prod_T/Prod_max)
        score_t = df_jour[col_acteur]*(df_jour["Production_Totale"]/prod_max)
        # Moyenne du score sur l'année
        scores_finaux[acteur] = round(score_t.mean(), 3) if not score_t.empty else 0.0
    return scores_finaux
    
# =====================================================================
# BLOC 2 : GÉNÉRATION ET IMPORT DES DONNÉES TEMPORELLES
# =====================================================================

@st.cache_data(show_spinner=False)

def obtenir_production_pvgis(lat: float, lon: float, puissance_kw: float, inclinaison: int, azimut: int) -> pd.DataFrame:
    """
    Interroge l'API européenne PVGIS pour obtenir la vraie courbe de production solaire.
    - azimut : 0 = Sud, -90 = Est, 90 = Ouest
    - inclinaison : angle des panneaux (ex: 35 degrés)
    """
    print(f"☀️ Interrogation de PVGIS pour {puissance_kw} kWc (Inc:{inclinaison}°, Azi:{azimut}°)...")
    
    url = f"https://re.jrc.ec.europa.eu/api/v5_2/seriescalc?lat={lat}&lon={lon}&raddatabase=PVGIS-SARAH2&outputformat=json&angle={inclinaison}&aspect={azimut}&pvcalculation=1&peakpower={puissance_kw}&loss=14&startyear=2020&endyear=2020"
    
    try:
        reponse = requests.get(url, timeout=15).json()
        donnees = reponse['outputs']['hourly']
        
        df = pd.DataFrame(donnees)
        
        # Le format de PVGIS est YYYYMMDD:HHMM
        df['Horodate'] = pd.to_datetime(df['time'], format='%Y%m%d:%H%M')
        
        # PVGIS renvoie la puissance générée (P) en Watts. On divise par 1000 pour les kW.
        df['Production_kWh'] = df['P'] / 1000.0 
        
        # On ne garde que les données utiles
        return df[['Horodate', 'Production_kWh']]
        
    except Exception as e:
        print(f"Erreur de connexion à l'API PVGIS : {e}")
        return pd.DataFrame()
    
def importer_courbe_production_reelle(chemin_fichier_csv: str)-> pd.DataFrame:
    """
    Importe une vraie courbe de production solaire depuis un CSV.
    Supporte les formats avec 'Horodate' ou 'Date'/'Heure'.
    """
    df = None
    strategies_csv = [
        {'sep': ';', 'encoding': 'utf-8', 'skiprows': 0},
        {'sep': ';', 'encoding': 'latin-1', 'skiprows': 0},
        {'sep': ',', 'encoding': 'utf-8', 'skiprows': 0},
        {'sep': ',', 'encoding': 'latin-1', 'skiprows': 0},
        {'sep': ';', 'encoding': 'utf-8', 'skiprows': 2},
        {'sep': ';', 'encoding':'latin-1', 'skiprows': 2},
        {'sep': ',', 'encoding': 'utf-8', 'skiprows': 2},
        {'sep': ',', 'encoding':'latin-1', 'skiprows': 2}
        ]
    for kwargs in strategies_csv:
        try:
            temp_df = pd.read_csv(chemin_fichier_csv, engine='c', on_bad_lines='skip', **kwargs)
            if not temp_df.empty and len(temp_df.columns) > 1:
                df = temp_df
                break
        except Exception:
            continue
            
    if df is None or df.empty:
        return pd.DataFrame()

    df.columns = df.columns.astype(str).str.strip()

    col_date, col_heure, col_valeur = None, None, None

    for col in df.columns:
        col_lower = col.lower()
        if 'horodate' in col_lower or 'date' in col_lower: col_date = col
        elif 'heure' in col_lower: col_heure = col
        # On ajoute le mot 'production' pour nos fichiers générés
        elif 'valeur' in col_lower or 'production' in col_lower or 'p' == col_lower: col_valeur = col

    if col_date is None and len(df.columns) >= 2:
        col_date = df.columns[0]
        col_valeur = df.columns[1] if len(df.columns) == 2 else df.columns[2]

    if col_date is None or col_valeur is None:
        return pd.DataFrame()

    if col_heure is not None:
        df['Horodate'] = pd.to_datetime(df[col_date].astype(str) + ' ' + df[col_heure].astype(str), dayfirst=True, errors='coerce')
    else:
        df['Horodate'] = pd.to_datetime(df[col_date], errors='coerce')

    df = df.dropna(subset=['Horodate'])

    try:
        df[col_valeur] = df[col_valeur].astype(float)
    except:
        df[col_valeur] = df[col_valeur].astype(str).str.replace(',', '.').astype(float)

    if 'kwh' not in col_valeur.lower() and 'kw' not in col_valeur.lower():
        df[col_valeur] = df[col_valeur] / 1000.0

    df = df[['Horodate', col_valeur]].rename(columns={col_valeur: 'Production_kWh'})
    df = df.set_index('Horodate').resample('30min').sum().reset_index()
    return df
    
def uniformiser_pas_de_temps(df, colonne_date='Horodate', colonne_valeur='Valeur', pas_cible='30min', type_grandeur='energie'):
    """
    Uniformise le pas de temps d'un DataFrame contenant des séries temporelles.
    Gère l'upsampling (ex: données 1h -> 30min) et le downsampling (ex: 10min -> 30min).
    """
    if df.empty or colonne_date not in df.columns or colonne_valeur not in df.columns:
        return df
    
    # Forcer uniformisation du fuseau horaire
    df[colonne_date] = pd.to_datetime(df[colonne_date], utc=True).dt.tz_localize(None)
    df = df.sort_values(by=colonne_date)
    
    # Déterminer la fréquence originale (médiane de l'écart entre deux dates en minutes)
    diff_minutes = df[colonne_date].diff().dt.total_seconds().median() / 60.0
    
    df = df.set_index(colonne_date)
    df[colonne_valeur] = pd.to_numeric(df[colonne_valeur], errors='coerce')
    df[colonne_valeur] = df[colonne_valeur].fillna(0.0)
    
    # 1. Si la donnée est plus large que 30min (ex: PVGIS 60min) -> Upsampling
    if diff_minutes and diff_minutes > 30.0:
        df_propre = df.resample(pas_cible).ffill() # On remplit les "trous" créés
        if type_grandeur == 'energie':
            # On divise la valeur proportionnellement (ex: 1h -> 30min = division par 2)
            df_propre[colonne_valeur] = df_propre[colonne_valeur] * (30.0 / diff_minutes)
            
    # 2. Si la donnée est plus fine ou égale (ex: PV*SOL 15min ou 30min) -> Downsampling
    else:
        if type_grandeur == 'energie':
            df_propre = df.resample(pas_cible).sum()
        elif type_grandeur == 'puissance':
            df_propre = df.resample(pas_cible).mean()
            
    df_propre = df_propre.fillna(0.0).reset_index()
    return df_propre

def forcer_format_17520(df, horodates_canvas):
    """
    Supprime le 29 février et force le DataFrame à avoir exactement 17520 lignes.
    Comble automatiquement les trous en fin d'année (ex: 31 décembre 23h30 manquant sur PVGIS).
    """
    if df.empty or "Horodate" not in df.columns:
        return df
    
    # On s'assure que la colonne est bien un objet datetime compréhensible par Pandas
    df["Horodate"] = pd.to_datetime(df["Horodate"], utc=True, errors='coerce').dt.tz_localize(None)
    # Enlever le 29 février
    df = df[~((df["Horodate"].dt.month == 2) & (df["Horodate"].dt.day == 29))].reset_index(drop=True)
    
    manquant = 17520 - len(df)
    if manquant > 0:
        dernieres_lignes = pd.DataFrame([df.iloc[-1]] * manquant)
        df = pd.concat([df, dernieres_lignes], ignore_index=True)
        
    df = df.iloc[:17520].copy()
    df["Horodate"] = horodates_canvas
    return df

def importer_courbe_enedis_reelle(chemin_fichier_csv: str, id_acteur: int) -> pd.DataFrame:
    """Importe la courbe de charge officielle d'Enedis (CSV)."""
    df = None
    
    # Stratégies explicites pour éviter le bug du sniffer (engine='python' + sep=None)
    strategies_csv = [
        {'sep': ';', 'encoding': 'utf-8', 'skiprows': 0},
        {'sep': ';', 'encoding': 'latin-1', 'skiprows': 0},
        {'sep': ',', 'encoding': 'utf-8', 'skiprows': 0},
        {'sep': ',', 'encoding': 'latin-1', 'skiprows': 0},
        {'sep': ';', 'encoding': 'utf-8', 'skiprows': 2},
        {'sep': ';', 'encoding':'latin-1', 'skiprows': 2},
        {'sep': ',', 'encoding': 'utf-8', 'skiprows': 2},
        {'sep': ',', 'encoding':'latin-1', 'skiprows': 2}
    ]

    for kwargs in strategies_csv:
        try:
            # Utilisation du moteur 'c' beaucoup plus stable pour éviter l'erreur "Expected X fields, saw Y"
            temp_df = pd.read_csv(chemin_fichier_csv, engine='c', on_bad_lines='skip', **kwargs)
            if not temp_df.empty and len(temp_df.columns) > 1:
                df = temp_df
                break
        except Exception:
            continue
            
    if df is None or df.empty:
        print(f"Erreur d'importation Enedis pour {id_acteur} : Impossible de lire le fichier.")
        return pd.DataFrame()

    df.columns = df.columns.astype(str).str.strip()

    # Même logique de détection que pour la simulée
    col_date = None
    col_heure = None
    col_valeur = None

    for col in df.columns:
        col_lower = col.lower()
        if 'horodate' in col_lower or 'date' in col_lower:
            col_date = col
        elif 'heure' in col_lower:
            col_heure = col
        elif 'valeur' in col_lower or 'puissance' in col_lower:
            col_valeur = col

    if col_date is None and len(df.columns) >= 2:
        col_date = df.columns[0]
        if len(df.columns) >= 3:
            col_heure = df.columns[1]
            col_valeur = df.columns[2]
        else:
            col_valeur = df.columns[1]

    if col_date is None:
        print(f"Colonne de date introuvable pour {id_acteur}.")
        return pd.DataFrame()

    # Gestion des erreurs de parsing de la date pour éviter un crash
    if col_heure is not None:
        df['Horodate'] = pd.to_datetime(df[col_date].astype(str) + ' ' + df[col_heure].astype(str), dayfirst=True, errors='coerce')
    else:
        df['Horodate'] = pd.to_datetime(df[col_date], errors='coerce')

    # Nettoyage des lignes où la date est illisible
    df = df.dropna(subset=['Horodate'])

    if col_valeur is None:
        print(f"Colonne de valeur introuvable pour {id_acteur}.")
        return pd.DataFrame()

    try:
        df[col_valeur] = df[col_valeur].astype(float)
    except:
        df[col_valeur] = df[col_valeur].astype(str).str.replace(',', '.').astype(float)
    
    if 'kwh' not in col_valeur.lower() and 'kw' not in col_valeur.lower():
        df[col_valeur] = df[col_valeur] / 1000.0


    df = df[['Horodate', col_valeur]].rename(columns={col_valeur: id_acteur})
    df = df.set_index('Horodate').resample('30min').sum().reset_index()
    return df

def importer_courbe_enedis_simulee(id_acteur: int, code_naf: str, superficie: float) -> pd.DataFrame:
    """
    Importe une courbe de charge simulée (NAF) avec colonnes 'Horodate' et 'Puissance moyenne (W)'.
    Gère aussi les cas où les noms diffèrent, mais priorise ces deux-là.
    """
    naf_propre = str(code_naf).replace(".", "").replace(" ", "").upper() if code_naf else "INCONNU"
    nom_fichier_csv = f"naf{naf_propre}.csv"

    if not os.path.exists(nom_fichier_csv):
        print(f"Fichier {nom_fichier_csv} introuvable pour l'acteur {id_acteur}.")
        return pd.DataFrame()

    df = None
    
    # 1. Tentative de lecture en CSV avec différentes stratégies
    strategies_csv = [
        {'sep': ';', 'decimal': ',', 'encoding': 'utf-8'},
        {'sep': ';', 'decimal': ',', 'encoding': 'latin-1'},
        {'sep': ',', 'decimal': '.', 'encoding': 'utf-8'},
        {'sep': ',', 'decimal': '.', 'encoding': 'latin-1'},
        {'sep': '\t', 'decimal': '.', 'encoding': 'utf-8'}
    ]

    for kwargs in strategies_csv:
        try:
            temp_df = pd.read_csv(nom_fichier_csv, **kwargs)
            # Vérification de la signature "PK" (Fichier ZIP/Excel déguisé en CSV)
            if not temp_df.empty and isinstance(temp_df.columns[0], str) and temp_df.columns[0].startswith("PK"):
                df = None
                break # On sort de la boucle CSV, c'est un Excel
            if not temp_df.empty:
                df = temp_df
                break
        except Exception:
            continue

    # 2. Tentative de lecture en Excel si le CSV a échoué
    if df is None or df.empty:
        try:
            print(f"⚠️ {nom_fichier_csv} détecté comme potentiel fichier Excel. Tentative de lecture via openpyxl...")
            df = pd.read_excel(nom_fichier_csv, engine='openpyxl')
        except Exception as e:
            print(f"Impossible de lire {nom_fichier_csv} ni en CSV ni en Excel pour l'acteur {id_acteur}. Erreur: {e}")
            return pd.DataFrame()

    if df is None or df.empty:
        print(f"Fichier {nom_fichier_csv} vide pour l'acteur {id_acteur}.")
        return pd.DataFrame()

    # Nettoyer les noms de colonnes
    df.columns = df.columns.astype(str).str.strip()

    # Colonnes spécifiques
    col_date = None
    col_valeur = None

    for col in df.columns:
        if 'Horodate' in col.lower() or 'date' in col.lower():
            col_date = col
        if 'Puissance moyenne (W)' in col.lower() or 'Valeur' in col.lower() or 'puissance' in col.lower():
            col_valeur = col

    # Si on ne les trouve pas, on prend les deux premières colonnes
    if col_date is None:
        col_date = df.columns[0]
        print(f"⚠️ Colonne 'Horodate' non trouvée dans {nom_fichier_csv}, utilisation de '{col_date}'")
    if col_valeur is None:
        for col in df.columns:
            if col != col_date:
                col_valeur = col
                break
        print(f"⚠️ Colonne de puissance non trouvée, utilisation de '{col_valeur}'")

    if col_valeur is None:
        print(f"Erreur : aucune colonne de valeur exploitable dans {nom_fichier_csv}")
        return pd.DataFrame()

    # Construction de l'horodate avec sécurité UTC
    try:
        df['Horodate'] = pd.to_datetime(df[col_date], utc=True, errors='coerce').dt.lz_localize(None)
    except:
        df['Horodate'] = pd.to_datetime(df[col_date], dayfirst=True, utc=True, errors='coerce').dt.tz_localize(None)

    # Conversion de la valeur
    if df[col_valeur].dtype == object:
        df[col_valeur] = df[col_valeur].astype(str).str.replace(',', '.')

    df['Valeur'] = pd.to_numeric(df[col_valeur], errors='coerce')
    df = df.dropna(subset=['Horodate', 'Valeur'])

    if df.empty:
        print(f"Fichier {nom_fichier_csv} vide après nettoyage pour {id_acteur}.")
        return pd.DataFrame()

    # On isole l'horodate et la nouvelle valeur propre
    df = df[['Horodate', 'Valeur']].copy()
    # Produit en croix (référence 100 m²)
    SUPERFICIE_REFERENCE = 100.0
    if superficie > 0.0:
        ratio = superficie / SUPERFICIE_REFERENCE
        df['Valeur'] = df['Valeur'] * ratio

    # Resampling à 1 heure (car données horaires)
    df = df.rename(columns={'Valeur': id_acteur})
    
    return df
  
# =====================================================================
# BLOC 3 : OPTIMISATION FINANCIÈRE (PuLP) & TURPE
# =====================================================================
def obtenir_tarif_horaire(param_contrat: dict, dt: pd.Timestamp) -> float:
    """
    Détermine le prix du kWh applicable à une heure précise en fonction du contrat.
    - Heures Pleines (HP) : 8h00 à 19h59
    - Heures Creuses (HC) : 20h00 à 7h59
    - Été : Mai à Octobre (Mois 5 à 10)
    """
    type_contrat = param_contrat.get("type_contrat", "Base")
    prix = param_contrat.get("prix", {})

    if type_contrat == "Base":
        return float(prix.get("Base", 0.25))

    heure = dt.hour
    mois = dt.month
    est_hp = (8 <= heure < 20) 

    if type_contrat == "HP/HC":
        return float(prix.get("HP", 0.27)) if est_hp else float(prix.get("HC", 0.20))

    if type_contrat == "HP/HC Été/Hiver":
        est_ete = (5 <= mois <= 10)
        if est_ete:
            return float(prix.get("HP_Ete", 0.26)) if est_hp else float(prix.get("HC_Ete", 0.19))
        else:
            return float(prix.get("HP_Hiver", 0.28)) if est_hp else float(prix.get("HC_Hiver", 0.22))

    return 0.25 # Valeur de sécurité

def optimiser_repartition_lp(volume_solaire_dispo: float, dict_conso: Dict[int, float], dict_tarifs: Dict[int, float], dict_parts_fixes: Dict[int, float] = None) -> Tuple[Dict[int, float], Dict[int, float], float]:
    """
    Répartit l'énergie avec une clé hybride : 
        1. Donne la part réservée manuellement.
        2. Optimise financièrement le reste avec le solveur PuLP.
    """
    if dict_parts_fixes is None:
        dict_parts_fixes = {}
    # Initialisation
    alloc_static = {act: 0.0 for act in dict_conso.keys()}
    alloc_dynamic = {act: 0.0 for act in dict_conso.keys()}
    
    if volume_solaire_dispo <= 0.001:
        return alloc_static, alloc_dynamic, 0.0
    
    # 1. Clé statique : Pourcentages manuels bloqués
    for acteur, pourcentage in dict_parts_fixes.items():
        if acteur in dict_conso and pourcentage > 0:
            part_kwh_theorique = volume_solaire_dispo*pourcentage/100
            kwh_alloues = min(dict_conso[acteur], part_kwh_theorique)
            alloc_static[acteur] = round(kwh_alloues, 3)
            
            # MAJ des stocks
            dict_conso[acteur] -= kwh_alloues
            volume_solaire_dispo -= kwh_alloues
    
    # Si la clé statique a tout réparti : on s'arrête
    if volume_solaire_dispo <= 0.001:
        return alloc_static, alloc_dynamic, 0.0
    
    # 2. Clé dynamique
    prob = pulp.LpProblem("Optimisation_Financiere_ACC", pulp.LpMaximize)
    variables_allocations = {acteur: pulp.LpVariable(f"Alloc_{acteur}", lowBound=0, upBound=conso_max) for acteur, conso_max in dict_conso.items() if conso_max > 0}
    
    if variables_allocations:
        prob += pulp.lpSum([variables_allocations[acteur] * dict_tarifs[acteur] for acteur in variables_allocations.keys()]), "Max_Revenu"
        prob += pulp.lpSum(variables_allocations.values()) <= volume_solaire_dispo, "Limite_Solaire"
        prob.solve(pulp.PULP_CBC_CMD(msg=False))
    
        for acteur, var in variables_allocations.items():
            alloc_dynamic[acteur] = round(var.varValue, 3) # var.varValue = solution du problème

    surplus_reseau = max(0.0, round(volume_solaire_dispo - sum(alloc_dynamic.values()), 3))
    
    return alloc_static, alloc_dynamic, surplus_reseau

def obtenir_tarif_revente_horaire(param_contrat: dict, dt: pd.Timestamp) -> float:
    """Détermine le prix de rachat interne (revente du producteur au consommateur)."""
    type_contrat = param_contrat.get("type_contrat", "Base")
    prix_rev = param_contrat.get("prix_revente", {})
    if type_contrat == "Base": return float(prix_rev.get("Base", 0.15))
    heure = dt.hour
    mois = dt.month
    est_hp = (8 <= heure < 20)

    if type_contrat == "HP/HC":
        return float(prix_rev.get("HP", 0.16)) if est_hp else float(prix_rev.get("HC", 0.11))
    if type_contrat == "HP/HC Été/Hiver":
        if (5 <= mois <= 10): return float(prix_rev.get("HP_Ete", 0.15)) if est_hp else float(prix_rev.get("HC_Ete", 0.10))
        else: return float(prix_rev.get("HP_Hiver", 0.17)) if est_hp else float(prix_rev.get("HC_Hiver", 0.12))
    return 0.15

def simuler_projet_complet(df_series_temporelles: pd.DataFrame, dict_contrats: Dict[int, dict], dict_parts_fixes: Dict[int, float] = None, tarif_edf_oa: float = 0.10) -> Tuple[pd.DataFrame, float]:
    """
    Simule la répartition de l'énergie sur une longue période (Année).
    """
    liste_acteurs = list(dict_contrats.keys())
    total_energie_allouee = {acteur: 0.0 for acteur in liste_acteurs}
    total_statique = {act: 0.0 for act in liste_acteurs}
    total_dynamique = {act: 0.0 for act in liste_acteurs}
    total_economies = {acteur: 0.0 for acteur in liste_acteurs}
    total_gains_revente_prod = {act: 0.0 for act in liste_acteurs}
    total_surplus_edf = 0.0
    records_temporels = df_series_temporelles.to_dict('records')
    
    for ligne in records_temporels:
        soleil_t = ligne['Solaire_kWh']
        horodate_t = ligne['Horodate']
        dict_conso_t = {acteur: ligne.get(acteur, 0.0) for acteur in liste_acteurs if acteur in ligne}
        # Calcul du prix exact pour cette heure précise
        dict_tarifs_t = {
            acteur: obtenir_tarif_horaire(dict_contrats[acteur], horodate_t)
            for acteur in liste_acteurs
        }
        dict_revente_t = {act: obtenir_tarif_revente_horaire(dict_contrats[act], horodate_t) for act in liste_acteurs}
            
        alloc_s, alloc_d, surplus_t = optimiser_repartition_lp(soleil_t, dict_conso_t, dict_tarifs_t, dict_parts_fixes)
        
        for act in alloc_s.keys():
            kwh_t = alloc_s[act] + alloc_d[act]
            total_statique[act] += alloc_s[act]
            total_dynamique[act] += alloc_d[act]
            total_energie_allouee[act] += kwh_t
            
            # VRAIE ÉCONOMIE CONSOMMATEUR : (Prix réseau - Prix revente ACC) * kWh
            total_economies[act] += kwh_t * (dict_tarifs_t[act] - dict_revente_t[act])
            
            # GAIN BRUT PRODUCTEUR (Ce que les consommateurs lui paient)
            total_gains_revente_prod[act] += kwh_t * dict_revente_t[act]
            
        total_surplus_edf += surplus_t
    sum_dyn = sum(total_dynamique.values())
        
    # CALCUL DU GAIN NET PRODUCTEUR (Coût d'opportunité vs EDF OA)
    gains_nets_producteur = 0.0
    for act in liste_acteurs:
        gain_opportunite = total_gains_revente_prod[act] - (total_energie_allouee[act] * tarif_edf_oa)
        gains_nets_producteur += gain_opportunite
        
    bilan_final = [{
        'ID_Acteur': acteur,
        'Total_Autoconsomme_kWh': round(total_energie_allouee[acteur], 2),
        'Economie_Generee_Euros': round(total_economies[acteur], 2),
        'Cle_Statique_Pct': round(dict_parts_fixes.get(acteur, 0.0), 1),
        'Cle_Dynamique_Pct': round((total_dynamique[acteur] / sum_dyn * 100.0) if sum_dyn > 0 else 0.0, 1),
        'Type_Ligne': 'Consommateur'
    } for acteur in liste_acteurs]
    
    gains_nets_producteur = 0.0
    for act in liste_acteurs:
        # Formule demandée : energie_allouee * (tarif_revente - tarif_edf_oa)
        # On calcule la différence entre ce que l'ACC a rapporté et ce qu'EDF OA aurait rapporté pour cet acteur
        gain_opportunite_acteur = total_gains_revente_prod[act] - (total_energie_allouee[act] * tarif_edf_oa)
        gains_nets_producteur += gain_opportunite_acteur
    
    bilan_final.append({
        'ID_Acteur': 'Producteur (Gains nets ACC)',
        'Total_Autoconsomme_kWh': round(sum(total_energie_allouee.values()), 2),
        'Economie_Generee_Euros': round(gains_nets_producteur, 2),
        'Cle_Statique_Pct': 0.0,
        'Cle_Dynamique_Pct': 0.0,
        'Type_Ligne': 'Producteur'
    })
    
    return pd.DataFrame(bilan_final), round(total_surplus_edf, 2)

def calculer_TURPE_Base(CG, CC, CSF, puissance_souscrite, tarif_base, conso_totale):
    return round(CG + CC + CSF*puissance_souscrite + tarif_base*conso_totale, 2)

def calculer_TURPE_HPC(CG, CC, CSF, puissance_souscrite, tarif_HP, conso_HP, tarif_HC, conso_HC):
    return round(CG + CC + CSF*puissance_souscrite + tarif_HC*conso_HC + tarif_HP*conso_HP, 2)

def calculer_TURPE_HPC_EteHiver(CG, CC, CSF, puissance_souscrite, tarif_HPH, conso_HPH, tarif_HCH, conso_HCH, tarif_HPE, conso_HPE, tarif_HCE, conso_HCE):
    return round(CG + CC + CSF*puissance_souscrite + tarif_HPH*conso_HPH + tarif_HCH*conso_HCH + tarif_HPE*conso_HPE + tarif_HCE*conso_HCE, 2)


# =====================================================================
# BLOC 4 : DATAVISUALISATION ET EXPORTS PDF
# =====================================================================

def generer_graphique_financier(df_bilan: pd.DataFrame):
    df_trie = df_bilan.sort_values(by="Economie_Generee_Euros", ascending=True)
    fig = px.bar(
        df_trie, x="Economie_Generee_Euros", y="ID_Acteur", orientation='h',
        title="Bilan financier : Economies générées sur la période",
        labels={"Economie_Generee_Euros" : "Economies (€)", "ID_Acteur" : "Participants"},
        color="Economie_Generee_Euros", color_continuous_scale="Viridis"
    )
    fig.update_layout(template="plotly_white")
    return fig

def generer_courbe_de_charge(df_horaire: pd.DataFrame, liste_ids_acteurs: list):
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df_horaire['Horodate'], 
        y=df_horaire['Solaire_kWh'], 
        mode='lines', 
        name='Production', 
        fill='tozeroy', 
        line=dict(color='rgba(255, 215, 0, 0.8)', width=2)
        ))
    fig.add_trace(go.Scatter(
        x=df_horaire['Horodate'], 
        y=df_horaire['Conso_Totale_kWh'], 
        mode='lines', 
        name='Conso Totale', 
        line=dict(color='firebrick', width=3)
        ))
    
    couleurs = ['royalblue', 'seagreen', 'darkorange', 'purple', 'cyan', 'brown']
    for index, id_acteur in enumerate(liste_ids_acteurs):
        if id_acteur in df_horaire.columns:
            fig.add_trace(go.Scatter(
                x=df_horaire['Horodate'], 
                y=df_horaire[id_acteur], 
                mode='lines', 
                name=f'{id_acteur}', 
                line=dict(color=couleurs[index % len(couleurs)], width=2, dash='dash')
            ))
            
    fig.update_layout(title="Courbe de charge vs Production photovoltaïque", xaxis_title="Heure", yaxis_title="Energie (kWh)", template="plotly_white", hovermode="x unified")
    fig.update_xaxes(rangeslider_visible=True)
    return fig

def exporter_rapport_pdf(df_bilan: pd.DataFrame, surplus_total: float, fig_courbes=None, dict_cles=None, chemin_fichier: str = "Rapport_Etude_ACC.pdf"):
    pdf = FPDF()
    pdf.add_page()
    
    pdf.set_font("helvetica", 'B', 16)
    pdf.cell(200, 10, text="Rapport d'Etude : Autoconsommation Collective (ACC)", new_x="LMARGIN", new_y="NEXT", align='C')
    pdf.set_font("helvetica", 'I', 10)
    pdf.cell(200, 10, text=f'Généré le {datetime.datetime.now().strftime("%d/%m/%Y")} par le moteur IBC', new_x="LMARGIN", new_y="NEXT", align='C')
    pdf.ln(10) 
    
    pdf.set_font("helvetica", 'B', 12)
    pdf.cell(200, 10, text='1. Bilan Energetique Global', new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("helvetica", '', 11)
    conso_rows = df_bilan[df_bilan['Type_Ligne'] == 'Consommateur']
    prod_rows = df_bilan[df_bilan['Type_Ligne'] == 'Producteur']
    pdf.cell(200, 8, text=f"- Energie locale partagee : {round(conso_rows['Total_Autoconsomme_kWh'].sum(), 2)} kWh", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(200, 8, text=f"- Surplus revendu (EDF OA) : {round(surplus_total, 2)} kWh", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(200, 8, text=f"- Gains nets du producteur : {round(prod_rows['Economie_Generee_Euros'].sum(), 2)} Euros", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)
    
    if fig_courbes is not None:
        try:
            fichier_image = "temp_graphique_acc.png"
            # Sauvegarde de la figure Plotly en image fixe
            fig_courbes.write_image(fichier_image, width=900, height=350, engine='kaleido')
            time.sleep(0.5)
            # Insertion dans le PDF
            pdf.image(fichier_image, x=10, w=190)
            pdf.ln(5)
            # Nettoyage du fichier temporaire
            if os.path.exists(fichier_image):
                os.remove(fichier_image)
        except Exception as e:
            pdf.set_font("helvetica", 'I', 10)
            pdf.set_text_color(255, 0, 0) # En rouge
            pdf.cell(200, 10, text="(Le graphique n'a pas pu etre insere. Executer 'pip install -U kaleido' dans le terminal)", new_x="LMARGIN", new_y="NEXT", align='C')
            pdf.set_text_color(0, 0, 0)
    
    pdf.set_font("helvetica", 'B', 12)
    pdf.cell(200, 10, text='2. Tableau Recapitulatif des Participants et Cles', new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("helvetica", 'B', 9)
    
    pdf.cell(50, 10, "Acteur / Participant", border=1, align='C')
    pdf.cell(30, 10, "Cle Stat. (%)", border=1, align='C')
    pdf.cell(30, 10, "Cle Dyn. (%)", border=1, align='C')
    pdf.cell(40, 10, "Volume (kWh)", border=1, align='C')
    pdf.cell(40, 10, "Gains/Eco (Euros)", border=1, new_x="LMARGIN", new_y="NEXT", align='C')

    pdf.set_font("helvetica", '', 9)
    for index, ligne in df_bilan.iterrows():
        nom_propre = str(ligne['ID_Acteur']).encode('latin-1', 'replace').decode('latin-1')
        c_stat = f"{ligne['Cle_Statique_Pct']}%" if ligne['Type_Ligne'] == 'Consommateur' else "-"
        c_dyn = f"{ligne['Cle_Dynamique_Pct']}%" if ligne['Type_Ligne'] == 'Consommateur' else "-"
        
        pdf.cell(50, 10, nom_propre, border=1)
        pdf.cell(30, 10, c_stat, border=1, align='C')
        pdf.cell(30, 10, c_dyn, border=1, align='C')
        pdf.cell(40, 10, str(ligne['Total_Autoconsomme_kWh']), border=1, align='R')
        pdf.cell(40, 10, str(ligne['Economie_Generee_Euros']), border=1, new_x="LMARGIN", new_y="NEXT", align='R')

    pdf.output(chemin_fichier)
    return chemin_fichier

def generer_facture_mensuelle(id_acteur: int, kwh_consommes: float, tarif_kwh: float, total_euros: float, mois: str, annee: str, dossier_sortie: str = "Factures") -> str:
    """
    Génère une facture légale au format PDF pour un participant de l'ACC.
    """
    # Création du dossier s'il n'existe pas encore sur l'ordinateur
    if not os.path.exists(dossier_sortie):
        os.makedirs(dossier_sortie)
        
    nom_fichier = f"{dossier_sortie}/Facture_{id_acteur}_{mois}_{annee}.pdf"
    
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("helvetica", 'B', 20)
    pdf.set_text_color(41, 128, 185)
    pdf.cell(200, 15, text="FACTURE D'ELECTRICITE - PMO", new_x="LMARGIN", new_y="NEXT", align='C')
    pdf.set_text_color(0, 0, 0)
    pdf.ln(10)
    # En-tête
    pdf.set_font("helvetica", 'B', 11)
    pdf.cell(100, 6, text="Emetteur : PMO Energie Locale", align='L')
    pdf.cell(90, 6, text=f"Client : {id_acteur}", new_x="LMARGIN", new_y="NEXT", align='R')
    pdf.ln(10)
    
    date_jour = datetime.datetime.now().strftime("%d/%m/%Y")
    num_facture = f"F-{annee}-{mois}-{str(id_acteur)[:3].upper()}"
    
    pdf.set_font("helvetica", 'B', 10)
    pdf.cell(100, 6, text=f"Numero de facture : {num_facture}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(100, 6, text=f"Date de facturation : {date_jour}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(100, 6, text=f"Periode de consommation : {mois} {annee}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(10)
    
    pdf.set_fill_color(200, 220, 255)
    w_col = [80, 40, 40, 30]
    pdf.cell(w_col[0], 10, text="Designation", border=1, fill=True, align='C')
    pdf.cell(w_col[1], 10, text="Quantite (kWh)", border=1, fill=True, align='C')
    pdf.cell(w_col[2], 10, text="Prix moyen", border=1, fill=True, align='C')
    pdf.cell(w_col[3], 10, text="Total", border=1, new_x="LMARGIN", new_y="NEXT", align='C')
    
    pdf.set_font("helvetica", '', 10)
    pdf.cell(w_col[0], 10, text="Electricite de rachat interne ACC", border=1)
    pdf.cell(w_col[1], 10, text=f"{kwh_consommes:.2f}", border=1, align='C')
    pdf.cell(w_col[2], 10, text=f"{tarif_kwh:.4f} Euros", border=1, align='C')
    pdf.cell(w_col[3], 10, text=f"{total_euros:.2f} Euros", border=1, new_x="LMARGIN", new_y="NEXT", align='R')
    
    pdf.ln(5)
    pdf.set_font("helvetica", 'B', 12)
    pdf.cell(160, 10, text="Total a regler :", align='R')
    pdf.cell(30, 10, text=f"{total_euros:.2f} Euros", border=1, new_x="LMARGIN", new_y="NEXT", align='R')
    
    pdf.output(nom_fichier)
    return nom_fichier

def generer_lot_factures(df_bilan: pd.DataFrame, df_tarifs: pd.DataFrame, mois: str, annee: str):
    """
    Boucle sur tous les acteurs pour créer le lot de factures du mois.
    """
    
    fichiers_generes = []
    
    # On boucle sur le bilan mensuel
    for index, ligne in df_bilan.iterrows():
        id_acteur = ligne['ID_Acteur']
        kwh = ligne['Total_Autoconsomme_kWh']
        euros = ligne['Economie_Generee_Euros']
        
        # On ignore les producteurs purs qui n'ont rien consommé
        if kwh > 0:
            tarif = df_tarifs[df_tarifs['ID_Acteur'] == id_acteur]['Tarif_Reseau_Euro_kWh'].values[0]
            
            chemin = generer_facture_mensuelle(id_acteur, kwh, tarif, euros, mois, annee)
            fichiers_generes.append(chemin)
            print(f"Facture créée : {chemin}")
            
    return fichiers_generes
