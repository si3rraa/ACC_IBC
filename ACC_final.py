# -*- coding: utf-8 -*-
"""
Application de Gestion et Optimisation de l'Autoconsommation Collective (ACC)
"""

import streamlit as st 
import pandas as pd 
import folium
from streamlit_folium import st_folium
import time
import requests
import json
import ACC as seb
import ACC_BDD as nathan
import ACC_NAF as NAFapi
import os
import datetime
import calendar

# CONFIGURATION DE LA PAGE
st.set_page_config("IBC Gestion ACC", layout="wide")

nathan.init_database()
conn = nathan.get_connection()
cursor = conn.cursor()
cursor.execute("SELECT COUNT(*) FROM VILLE")
nb_villes = cursor.fetchone()[0]
conn.close()

if nb_villes == 0:
    if os.path.exists("villes.csv"):
        print("Importation du fichier INSEE dans la base de données...")
        nathan.importer_ville("villes.csv")
    else:
        print("Fichier villes.csv introuvable.")

# MENU LATÉRAL
st.sidebar.title("Menu latéral")
page = st.sidebar.radio("Aller vers:", ["Etude de potentiel", "Optimisation de l'ACC"])

# INITIALISATION DE LA MÉMOIRE (SESSION STATE) 
if "Participants_Predefinis" not in st.session_state:
    st.session_state["Participants_Predefinis"] = []
if "Prospects_API" not in st.session_state:
    st.session_state["Prospects_API"] = []
if "Blacklist" not in st.session_state:
    st.session_state["Blacklist"] = []
if "Courbes_Importees" not in st.session_state:
    st.session_state["Courbes_Importees"] = {}
if "Parametres_Acteurs" not in st.session_state:
    st.session_state["Parametres_Acteurs"] = {}
if "Latitude" not in st.session_state:
    st.session_state["Latitude"] = 43.76
if "Longitude" not in st.session_state:
    st.session_state["Longitude"] = 4.42
if "calcul_lance" not in st.session_state:
    st.session_state["calcul_lance"] = False
if "Courbes_Importees_Optimisation" not in st.session_state:
    st.session_state["Courbes_Importees_Optimisation"] = {}
if "Cache_Courbes_Reelles" not in st.session_state:
    st.session_state["Cache_Courbes_Reelles"] = {}
if "Cache_NAF" not in st.session_state:
    st.session_state["Cache_NAF"] = {}
if "df_bilan_saved" not in st.session_state:
    st.session_state["df_bilan_saved"] = None
if "surplus_total_saved" not in st.session_state:
    st.session_state["surplus_total_saved"] = None
if "df_series_graph_saved" not in st.session_state:
    st.session_state["df_series_graph_saved"] = None
if "ids_consommateurs_noms_saved" not in st.session_state:
    st.session_state["ids_consommateurs_noms_saved"] = None

# ==========================================
# MODULE DE SAUVEGARDE ET CHARGEMENT (Menu latéral)
# ==========================================
st.sidebar.markdown("---")
st.sidebar.header("💾 Gestion du Projet")

# Export JSON
st.sidebar.write("💾 **Sauvegarde**")
etat_du_projet = {
    "Participants_Predefinis": st.session_state["Participants_Predefinis"],
    "Prospects_API": st.session_state["Prospects_API"],
    "Blacklist": st.session_state["Blacklist"],
    "Courbes_Importees": st.session_state.get("Courbes_Importees", {}),
    "Parametres_Acteurs": st.session_state.get("Parametres_Acteurs", {}),
    "centre_lat": st.session_state.get("centre_lat"),
    "centre_lon": st.session_state.get("centre_lon"),
    "rayon_opti": st.session_state.get("rayon_opti"),
    "nom_scenario": st.session_state.get("nom_scenario"),
    "calcul_lance": st.session_state.get("calcul_lance", False)
}
json_string = json.dumps(etat_du_projet, indent=4)

st.sidebar.download_button(
    label="📥 Télécharger la sauvegarde",
    file_name="Projet_ACC_IBC.json",
    mime="application/json",
    data=json_string,
    type="secondary",
    use_container_width=True
)

# Import JSON
st.sidebar.write("📂 **Restauration**")
fichier_upload = st.sidebar.file_uploader("Reprendre un projet (.json)", type=["json"])

if fichier_upload is not None:
    if st.sidebar.button("Restaurer ce projet", type="primary", use_container_width=True):
        donnees_restaurees = json.load(fichier_upload)
        st.session_state["Participants_Predefinis"] = donnees_restaurees.get("Participants_Predefinis", [])
        st.session_state["Prospects_API"] = donnees_restaurees.get("Prospects_API", [])
        st.session_state["Blacklist"] = donnees_restaurees.get("Blacklist", [])
        st.session_state["Courbes_Importees"] = donnees_restaurees.get("Courbes_Importees", {})
        st.session_state["Parametres_Acteurs"] = donnees_restaurees.get("Parametres_Acteurs", {})
        
        if donnees_restaurees.get("calcul_lance") == True:
            st.session_state["calcul_lance"] = True 
            st.session_state["centre_lat"] = donnees_restaurees.get("centre_lat")
            st.session_state["centre_lon"] = donnees_restaurees.get("centre_lon")
            st.session_state["rayon_opti"] = donnees_restaurees.get("rayon_opti")
            st.session_state["nom_scenario"] = donnees_restaurees.get("nom_scenario")
        else:
            st.session_state["calcul_lance"] = False
            
        st.sidebar.success("Projet restauré !")
        time.sleep(0.5)
        st.rerun()

# Nettoyage du cache
st.sidebar.write("🧹 **Nettoyage**")
if st.sidebar.button("Vider le cache en mémoire", type="secondary", use_container_width=True, help="Force l'application à oublier les anciennes courbes et données pré-calculées."):
    # Liste des mémoires tampons (dictionnaires) à réinitialiser
    cles_a_vider = [
        "Cache_Courbes_Reelles", 
        "Cache_NAF", 
        "Cache_NAF_Traite", 
        "Cache_GPS_INSEE",
        "Courbes_Importees",
        "Courbes_Importees_Optimisation"
    ]
    
    for cle in cles_a_vider:
        if cle in st.session_state:
            st.session_state[cle] = {}
            
    # On vide aussi le cache interne natif de Streamlit par précaution (si utilisé par des décorateurs @st.cache_data)
    st.cache_data.clear()
    
    st.sidebar.success("✅ Cache vidé avec succès !")
    time.sleep(1)
    st.rerun()

# ==========================================
# BLOC 1 : ÉTUDE DE POTENTIEL
# ==========================================
if page == "Etude de potentiel":
    st.title("Estimation technico-économique")
    
    # ---------------------------------------------------------
    # PARTIE 1 : AJOUTER DES ACTEURS (MANUEL OU IMPORT)
    # ---------------------------------------------------------
    st.header("1. Ajouter des acteurs au projet")
    
    tab_manuel, tab_import = st.tabs(["✍️ Saisie Manuelle", "📥 Importer une liste (CSV)"])
    
    # ONGLET 1 : SAISIE MANUELLE
    with tab_manuel:
        col1, col2 = st.columns(2)
        
        with col1:
            Nom_Acteur = st.text_input("Nom de l'acteur")
            st.write("📍 **Localisation de l'acteur' :**")
            
            # RECHERCHE PAR ADRESSE
            adresse_recherche = st.text_input("Rechercher une adresse postale :", placeholder="ex: 10 rue de la République, Nîmes")
            if st.button("🔍 Centrer la carte sur l'adresse", type="secondary"):
                if adresse_recherche:
                    url_api = f"https://api-adresse.data.gouv.fr/search/?q={adresse_recherche}&limit=1"
                    try:
                        reponse = requests.get(url_api).json()
                        if len(reponse["features"]) > 0:
                            coords = reponse["features"][0]["geometry"]["coordinates"]
                            st.session_state["Longitude"] = float(coords[0])
                            st.session_state["Latitude"] = float(coords[1])
                            st.session_state["zoom"] = 16 
                            st.rerun() 
                    except Exception:
                        st.error("Erreur de connexion à l'API Adresse.")
            
            # SAISIE MANUELLE DES COORDONNÉES GPS
            col_gps1, col_gps2 = st.columns(2)
            with col_gps1:
                # On utilise 'value' au lieu de 'key' pour éviter le conflit avec le clic sur la carte
                nouvelle_lat = st.number_input("Latitude", step=0.0001, format="%.5f", value=st.session_state["Latitude"])
            with col_gps2:
                nouvelle_lon = st.number_input("Longitude", step=0.0001, format="%.5f", value=st.session_state["Longitude"])
                
            if nouvelle_lat != st.session_state["Latitude"] or nouvelle_lon != st.session_state["Longitude"]:
                st.session_state["Latitude"] = nouvelle_lat
                st.session_state["Longitude"] = nouvelle_lon
                st.session_state["zoom"] = 16
                st.rerun()
    
            # CARTE INTERACTIVE
            m = folium.Map(location=[st.session_state["Latitude"], st.session_state["Longitude"]], zoom_start=st.session_state.get("zoom", 10))
            folium.Marker([st.session_state["Latitude"], st.session_state["Longitude"]], tooltip="Position sélectionnée").add_to(m)
            map_data = st_folium(m, width=True, height=350)
               
            # Récupération du clic sur la carte
            if map_data and map_data.get("last_clicked"):
                lat_click = map_data["last_clicked"]["lat"]
                lon_click = map_data["last_clicked"]["lng"]
                if st.session_state["Latitude"] != lat_click or st.session_state["Longitude"] != lon_click:
                    st.session_state["Latitude"] = lat_click
                    st.session_state["Longitude"] = lon_click
                    st.session_state["zoom"] = 16
                    st.rerun()
    
        # COLONNE DROITE : Paramètres
        with col2:
            Type_Acteur = st.selectbox(
                "Sélectionner le type d'acteur :", 
                ("Entreprise Consommatrice", "Particulier Consommateur", "Producteur", "SDIS", "Aucun")
            )    
            # Informations par défaut
            siret = ""
            superficie = 0
            contrat_actuel = "Inconnu"
            abo_mensuel = 0.0
            prix_saisis = {}
            puissance_crete = 0.0
            azimut = 0
            inclinaison = 30
            fichier_courbe = None
            
            if Type_Acteur == "Entreprise Consommatrice":
                # Sécurité pour bloquer le nombre de caractères à 14
                siret = st.text_input("Numéro SIRET (14 chiffres) 🔴 Obligatoire", max_chars=14, help="Indispensable pour l'étude technico économique")
                if len(siret) > 0 and (not siret.isdigit() or len(siret) != 14):
                    st.warning("⚠️ Le SIRET doit contenir exactement 14 chiffres (sans espaces ni lettres).")
        
                with st.expander("💼 Informations de démarchage - Consommation", expanded=True):
                    st.info("💡 *Laissez à 0 ou 'Inconnu' pour utiliser les approximations.*")
                    superficie = st.number_input("Superficie utile (m²)", min_value=0, value=0, step=50)
                    
                    col_c1, col_c2 = st.columns(2)
                    with col_c1:
                        contrat_actuel = st.selectbox("Contrat actuel", ["Inconnu", "Base", "HP/HC", "HP/HC Été/Hiver"])
                    with col_c2:
                        abo_mensuel = st.number_input("Abonnement (€/mois)", min_value=0.0, value=0.0, step=5.0)
                    
                    # Case pour remplir les tarifs du contrat d'électricité
                    if contrat_actuel == "Base":
                        prix_saisis["Base"] = st.number_input("Tarif Unique (€/kWh)", min_value=0.0, value=0.0, step=0.01, format="%.3f")
                    elif contrat_actuel == "HP/HC":
                        col_px1, col_px2 = st.columns(2)
                        with col_px1: prix_saisis["HP"] = st.number_input("Tarif HP", min_value=0.0, value=0.0, step=0.01, format="%.3f")
                        with col_px2: prix_saisis["HC"] = st.number_input("Tarif HC", min_value=0.0, value=0.0, step=0.01, format="%.3f")
                    elif contrat_actuel == "HP/HC Été/Hiver":
                        col_px1, col_px2, col_px3, col_px4 = st.columns(4)
                        with col_px1: prix_saisis["HP_Hiver"] = st.number_input("HP Hiver", min_value=0.0, value=0.0, step=0.01, format="%.3f")
                        with col_px2: prix_saisis["HC_Hiver"] = st.number_input("HC Hiver", min_value=0.0, value=0.0, step=0.01, format="%.3f")
                        with col_px3: prix_saisis["HP_Ete"] = st.number_input("HP Été", min_value=0.0, value=0.0, step=0.01, format="%.3f")
                        with col_px4: prix_saisis["HC_Ete"] = st.number_input("HC Été", min_value=0.0, value=0.0, step=0.01, format="%.3f")
    
                    fichier_courbe = st.file_uploader("Courbe de charge réelle (CSV)", type="csv")
            
            if Type_Acteur in ["Particulier Consommateur", "SDIS"]:
                with st.expander("💼 Informations de démarchage - Consommation", expanded=True):
                    fichier_courbe=st.file_uploader("Courbe de charge réelle (CSV)", type="csv")
                
            
            
            elif Type_Acteur == "Producteur":
                with st.expander("☀️ Informations de l'installation", expanded=True):
                    st.info("💡 *Ces paramètres permettront de simuler la production PV.*")
                    puissance_crete = st.number_input("Puissance Crête Installable (kWc)", min_value=0.0, value=0.0, step=1.0)
                    
                    col_sol1, col_sol2 = st.columns(2)
                    with col_sol1: azimut = st.number_input("Azimut (°)", min_value=-180, max_value=180, value=0, step=5)
                    with col_sol2: inclinaison = st.number_input("Inclinaison (°)", min_value=0, max_value=90, value=30, step=5)
                        
                    fichier_courbe = st.file_uploader("Courbe de production réelle (CSV)", type="csv")

            nom_invalide = (Nom_Acteur.strip() == "")
            siret_invalide = (Type_Acteur == "Entreprise Consommatrice" and (not siret.isdigit() or len(siret) != 14))
            condition_blocage = (Type_Acteur == "Aucun" or nom_invalide or siret_invalide)

            if nom_invalide:
                msg_aide = "Veuillez saisir un nom."
            elif siret_invalide:
                msg_aide = "Veuillez saisir un SIRET valide (14 chiffres, sans espaces)."
            else:
                msg_aide = "Cliquez pour ajouter le participant."

            if st.button("Ajouter le participant", type="secondary", disabled=condition_blocage, help=msg_aide): 
                if Nom_Acteur in st.session_state["Blacklist"]:
                    st.error(f"🚫 **Action impossible :** L'acteur '{Nom_Acteur}' est sur la **Liste Noire**. Retirez-le en Partie 4 pour l'intégrer.")
                else:
                    texte_tarifs = "Inconnu" if contrat_actuel == "Inconnu" else " | ".join([f"{k}: {v}€" for k, v in prix_saisis.items()])
                    
                    infos_p = {
                        "Nom": Nom_Acteur, 
                        "Type": Type_Acteur, 
                        "Statut": "Predefini",
                        "SIRET": siret if Type_Acteur == "Entreprise Consommatrice" else "-",
                        "Latitude": st.session_state["Latitude"],
                        "Longitude": st.session_state["Longitude"],
                        "Superficie (m2)": superficie if Type_Acteur != "Producteur" else "-",
                        "Contrat": contrat_actuel if Type_Acteur != "Producteur" else "-",
                        "Abo (€/mois)": abo_mensuel if Type_Acteur != "Producteur" else "-",
                        "Tarifs": texte_tarifs if Type_Acteur != "Producteur" else "-",
                        "Puissance (kWc)": puissance_crete if Type_Acteur == "Producteur" else "-",
                        "Azimut (°)": azimut if Type_Acteur == "Producteur" else "-",
                        "Inclinaison (°)": inclinaison if Type_Acteur == "Producteur" else "-"
                    }
                    st.session_state["Participants_Predefinis"].append(infos_p)
                    
                    if fichier_courbe is not None:
                                               
                        # Crée un dossier physique sur l'ordinateur
                        dossier_sauvegarde = "Courbes_Reelles_Importees"
                        os.makedirs(dossier_sauvegarde, exist_ok=True)
                        
                        # Définit le chemin complet où on va l'enregistrer
                        chemin_complet = os.path.join(dossier_sauvegarde, fichier_courbe.name)
                        
                        # Copie du fichier binaire de Streamlit vers le disque dur
                        with open(chemin_complet, "wb") as f:
                            f.write(fichier_courbe.getbuffer())
                            
                        # Sauvegarde du CHEMIN PHYSIQUE dans la mémoire
                        st.session_state["Courbes_Importees"][Nom_Acteur] = chemin_complet
                    
                    if Type_Acteur in ["Entreprise Consommatrice", "Particulier Consommateur", "SDIS"] and contrat_actuel != "Inconnu":
                        st.session_state["Parametres_Acteurs"][Nom_Acteur] = {
                            "pourcentage": 0.0, "type_contrat": contrat_actuel, "prix": prix_saisis, "abonnement": abo_mensuel * 12
                        }
                    elif Type_Acteur == "Producteur":
                        st.session_state["Parametres_Acteurs"][Nom_Acteur] = {
                            "pourcentage": 0.0, "puissance_crete": puissance_crete, "azimut": azimut, "inclinaison": inclinaison
                        }
                        
                    st.success(f"✅ {Nom_Acteur} enregistré !")
                    if "editor_partie2" in st.session_state: del st.session_state["editor_partie2"]
                    if "editor_partie3" in st.session_state: del st.session_state["editor_partie3"]
                    st.rerun()

    # ONGLET 2 : IMPORT CSV
    with tab_import:
        st.write("📥 **Importation de masse via fichier Excel / CSV**")
        fichier_liste = st.file_uploader("Sélectionner le fichier CSV des participants", type=["csv"])
        if fichier_liste is not None:
            if st.button("Intégrer la liste au projet", type="primary"):
                try:
                    df_import = pd.read_csv(fichier_liste)
                    for _, row in df_import.iterrows():
                        if row["Nom"] not in [p["Nom"] for p in st.session_state["Participants_Predefinis"]]:
                            st.session_state["Participants_Predefinis"].append({
                                "Nom": row["Nom"], 
                                "Type": row.get("Type", "Entreprise Consommatrice"), 
                                "Statut": "Importé",
                                "SIRET": str(row.get("SIRET", "-")),
                                "Latitude": row.get("Latitude", 0.0), 
                                "Longitude": row.get("Longitude", 0.0), 
                                "Superficie (m2)": row.get("Superficie", 0), 
                                "Contrat": row.get("Contrat", "Inconnu"),
                                "Abo (€/mois)": row.get("Abo", 0.0), 
                                "Tarifs": row.get("Tarifs", "Inconnu"),
                                "Puissance (kWc)": row.get("Puissance", 0.0), 
                                "Azimut (°)": row.get("Azimut", 0), 
                                "Inclinaison (°)": row.get("Inclinaison", 30)
                            })
                    st.success("Importation réussie !")
                    if "editor_partie2" in st.session_state: del st.session_state["editor_partie2"]
                    st.rerun()
                except Exception:
                    st.error("Erreur de lecture. Vérifiez les en-têtes (Nom, Type, SIRET...).")

    # ---------------------------------------------------------
    # PARTIE 2 : TABLEAU DU BLOC 1
    # ---------------------------------------------------------
    st.write("---")
    st.header("2. Liste des participants prédéfinis")
    if len(st.session_state["Participants_Predefinis"]) == 0:
        st.info("Aucun participant ajouté pour le moment.")
    else:
        df_predef = pd.DataFrame(st.session_state["Participants_Predefinis"])
        df_predef_edite = st.data_editor(df_predef, num_rows="dynamic", use_container_width=True, hide_index=True, key="editor_partie2")
        
        if len(df_predef_edite) < len(df_predef):
            noms_restants = set(df_predef_edite["Nom"])
            st.session_state["Participants_Predefinis"] = [p for p in st.session_state["Participants_Predefinis"] if p["Nom"] in noms_restants]
            st.toast("🗑️ Acteur supprimé.")
            if "editor_partie2" in st.session_state: del st.session_state["editor_partie2"]
            if "editor_partie3" in st.session_state: del st.session_state["editor_partie3"]
            st.rerun()
        elif df_predef_edite.to_dict('records') != st.session_state["Participants_Predefinis"]:
            st.session_state["Participants_Predefinis"] = df_predef_edite.to_dict('records')
            if "editor_partie3" in st.session_state: del st.session_state["editor_partie3"]

    # ---------------------------------------------------------
    # PARTIE 3 : CALCUL DES SCÉNARIOS & PMO GLOBALE
    # ---------------------------------------------------------
    st.write("---")
    st.header("3. Recherche et Optimisation du Périmètre")
    
    choix_rayon = st.selectbox(
        "📏 Réglementation applicable au projet (Rayon) :", 
        ["Automatique", 
         "1 km (Zone urbaine très dense)", 
         "5 km (Zone périurbaine)", 
         "10 km (Zone rurale ou dérogation SDIS)"]
    )
    
    if st.button("Rechercher et optimiser le périmètre", type="primary"):
        if len(st.session_state["Participants_Predefinis"]) == 0:
            st.error("⚠️ Vous devez d'abord ajouter au moins un participant prédéfini (ex: un producteur) pour définir le centre du projet.")
        else:
            with st.spinner("1/3 - Interrogation des bases de données de l'État..."):
                df_predef = pd.DataFrame(st.session_state["Participants_Predefinis"])
                # On crée un df_series pour l'algorithme
                df_series={} 
                horodates = pd.date_range(start="2026-01-01 00:00", periods=17520, freq="30min")
                df_series = pd.DataFrame({"Horodate": horodates})
                df_series["Production_Totale"] = 0.0
                liste_dfs = [] 
                ID_Acteur = 1
                
                # Initialisation globale
                puissance = 0.0
                inc = 30
                azi = 0
                rayon_max = 20
                
                # Mise en cache 
                if "Cache_NAF" not in st.session_state:
                    st.session_state["Cache_NAF"] = {}
                
                for p in st.session_state["Participants_Predefinis"]: 
                    p["ID_Acteur"] = ID_Acteur
    
                    if p["Type"]=="Entreprise Consommatrice":
                        if p["Nom"] in st.session_state["Courbes_Importees"]:
                            chemin_fichier = st.session_state["Courbes_Importees"][p["Nom"]]
                            if chemin_fichier in st.session_state.get("Cache_Courbes_Reelles", {}):
                                df = st.session_state["Cache_Courbes_Reelles"][chemin_fichier].copy()
                                col_valeur = [col for col in df.columns if col != "Horodate"][0]
                                df = df.rename(columns={col_valeur: ID_Acteur})
                            else:
                                df = seb.importer_courbe_enedis_reelle(chemin_fichier, ID_Acteur)
                                if not df.empty: st.session_state["Cache_Courbes_Reelles"][chemin_fichier] = df.copy()
                                
                            if not df.empty:
                                df = seb.uniformiser_pas_de_temps(df, colonne_date='Horodate', colonne_valeur=ID_Acteur, pas_cible='30min', type_grandeur='puissance')
                        else:
                            # Pour récupérer le code NAF
                            NAF=NAFapi.code_naf(p.get("SIRET",""))
                            sup_p = float(p.get("Superficie (m2)", p.get("Superficie", 0))) if p.get("Superficie (m2)", p.get("Superficie", 0)) else 0.0
                            # Si le NAF ne correspond pas aux courbes simulées, il se rapproche du domaine d'activité simulé
                            naf_nouveau = nathan.trouver_naf_correspondant(NAF)
                            nom_fichier = f"naf{naf_nouveau}.csv"
                            
                            # Vérification du cache pour ne pas faire des calculs déjà faits
                            if nom_fichier in st.session_state.get("Cache_NAF", {}):
                                df = st.session_state["Cache_NAF"][nom_fichier].copy()
                                col_valeur_cache = [col for col in df.columns if col != "Horodate"][0]
                                df = df.rename(columns={col_valeur_cache: ID_Acteur})
                            else:
                                df = seb.importer_courbe_enedis_simulee(ID_Acteur, naf_nouveau, sup_p)
                                if not df.empty: st.session_state["Cache_NAF"][nom_fichier] = df.copy()
                                    
                            if df.empty:
                                # Calcul du ratio de superficie pour les simulations
                                base_val = (sup_p if sup_p > 0 else 100.0) / 100.0
                                df = pd.DataFrame({"Horodate": horodates, ID_Acteur: base_val})
                            # Pour s'assurer que ça prenne le même pas de temps    
                            df = seb.uniformiser_pas_de_temps(df, colonne_date='Horodate', colonne_valeur=ID_Acteur, pas_cible='30min', type_grandeur='puissance')
                            
                        if not df.empty:
                            # Pour avoir le même nombre de valeurs
                            df = seb.forcer_format_17520(df, horodates)
                            liste_dfs.append(df)
                            
                    elif p["Type"] in ["Particulier Consommateur","SDIS"]:
                        if p["Nom"] in st.session_state["Courbes_Importees"]:
                            chemin_fichier = st.session_state["Courbes_Importees"][p["Nom"]]
                            
                            if chemin_fichier in st.session_state.get("Cache_Courbes_Reelles", {}):
                                df = st.session_state["Cache_Courbes_Reelles"][chemin_fichier].copy()
                                col_valeur = [col for col in df.columns if col != "Horodate"][0]
                                df = df.rename(columns={col_valeur: ID_Acteur})
                            else:
                                df = seb.importer_courbe_enedis_reelle(chemin_fichier, ID_Acteur)
                                if not df.empty: st.session_state["Cache_Courbes_Reelles"][chemin_fichier] = df.copy()
                            
                            if not df.empty:
                                df = seb.uniformiser_pas_de_temps(df, colonne_date='Horodate', colonne_valeur=ID_Acteur, pas_cible='30min', type_grandeur='puissance')
                        else:
                            df = pd.DataFrame({"Horodate": horodates, ID_Acteur: 0.0})
                            
                        if not df.empty:
                            df = seb.forcer_format_17520(df, horodates)
                            liste_dfs.append(df)
                            
                    elif p["Type"] == "Producteur":
                        # Un producteur ne consomme pas dans notre modèle
                        # Pour qu'il consomme, il faut qu'il soit à la fois producteur et consommateur
                        df_series[ID_Acteur]=0.0
                        # Initialisation des paramètres pour faire la requête à PVGIS
                        params = st.session_state["Parametres_Acteurs"].get(p["Nom"], {})
                        puissance = float(params.get("puissance_crete", p.get("Puissance (kWc)", 0.0)))
                        inc = int(params.get("inclinaison", p.get("Inclinaison (°)", 30)))
                        azi = int(params.get("azimut", p.get("Azimut (°)", 0)))
                        
                        if p["Nom"] in st.session_state["Courbes_Importees"]:
                            fichier = st.session_state["Courbes_Importees"][p["Nom"]]
                            if fichier in st.session_state.get("Cache_Courbes_Reelles", {}):
                                df_prod = st.session_state["Cache_Courbes_Reelles"][fichier].copy()
                            else:
                                df_prod = seb.importer_courbe_production_reelle(fichier)
                                if not df_prod.empty: st.session_state["Cache_Courbes_Reelles"][fichier] = df_prod.copy()
                        else:
                            df_prod = seb.obtenir_production_pvgis(p["Latitude"], p["Longitude"], puissance, inc, azi)
                            
                        if not df_prod.empty:
                            df_prod = seb.uniformiser_pas_de_temps(df_prod, colonne_date='Horodate', colonne_valeur='Production_kWh', pas_cible='30min', type_grandeur='energie')
                            df_prod = seb.forcer_format_17520(df_prod, horodates)
                            df_series["Production_Totale"] += df_prod["Production_kWh"].values
                    # Pour créer un ID unique pour chacun des acteurs/prospects
                    ID_Acteur += 1  
                
                for df in liste_dfs:
                    df_series = pd.merge(df_series, df, on="Horodate", how="left")
                df_series.fillna(0.0, inplace=True)
                df_series['Solaire_kWh'] = df_series['Production_Totale']
                        
                # Reconstruction de df_predef pour ajouter les ID_Acteur
                df_predef = pd.DataFrame(st.session_state["Participants_Predefinis"])
                coor_centre = seb.calculer_centre_optimal(df_predef, df_series)
                lat_centre = coor_centre["Latitude_Opti"]
                lon_centre = coor_centre["Longitude_Opti"]
                
                if hasattr(nathan, "ajouter_acteur"):
                    for p in st.session_state["Participants_Predefinis"]:
                        dict_pour_bdd = {
                            "Raison_Sociale": p["Nom"],
                            "Type_Acteur": "Consommateur" if p["Type"] != "Producteur" else "Producteur",
                            "Statut_Acteur": "Predefini",
                            "SIRET": p.get("SIRET", ""),
                            "Code_NAF": p.get("Code NAF", "")
                        }
                        nathan.ajouter_acteur(dict_pour_bdd)
                
            with st.spinner("2/3 - Préparation des données pour l'algorithme..."):
                liste_prospects = []
                try:
                    df_bdd = nathan.afficher_prospection_optimale(lat_centre, lon_centre, rayon_max, puissance, inc, azi)
                    if isinstance(df_bdd, pd.DataFrame): 
                        liste_prospects = df_bdd.to_dict('records') if not df_bdd.empty else []
                    elif isinstance(df_bdd, list): 
                        liste_prospects = df_bdd
                except Exception as e:
                    st.warning(f"⚠️ Erreur lors de la récupération des prospects : {e}")
                    
                # NOUVEAU CACHE
                if "Cache_NAF_Traite" not in st.session_state:
                    st.session_state["Cache_NAF_Traite"] = {}
                
                # Correction fragmentation : dictionnaire pour le pd.concat
                colonnes_a_ajouter = {}
                
                for p in liste_prospects: 
                    nom_prospect = p.get("Raison_Sociale", p.get("nom_raison_sociale", "Inconnu"))
                    if nom_prospect in st.session_state["Blacklist"] or nom_prospect in [pr["Nom"] for pr in st.session_state["Participants_Predefinis"]]:
                            continue

                    NAF = p.get("Code_NAF", p.get("activite_principale", ""))
                    superficie_p = float(p.get("Superficie (m2)", p.get("Superficie", p.get("superficie", 0)))) if p.get("Superficie (m2)", p.get("Superficie", p.get("superficie", 0))) else 0.0
                    naf_nouveau = nathan.trouver_naf_correspondant(NAF)
                    # Crée un nouveau fichier csv si la superficie n'est pas celle définie par défaut
                    nom_fichier = f"naf{naf_nouveau}_{superficie_p}.csv"
                    
                    if nom_fichier in st.session_state.get("Cache_NAF", {}):
                        df = st.session_state["Cache_NAF"][nom_fichier].copy() 
                        col_valeur_cache = [col for col in df.columns if col != "Horodate"][0]
                        df = df.rename(columns={col_valeur_cache: ID_Acteur})
                    else:
                        df = seb.importer_courbe_enedis_simulee(ID_Acteur, naf_nouveau, superficie_p)
                        if not df.empty: st.session_state["Cache_NAF"][nom_fichier] = df.copy()
                    
                    if df.empty:
                        df = pd.DataFrame({"Horodate": horodates, ID_Acteur: (superficie_p if superficie_p > 0 else 100.0) / 100.0})
                        
                    df = seb.uniformiser_pas_de_temps(df, colonne_date='Horodate', colonne_valeur=ID_Acteur, pas_cible='30min', type_grandeur='energie')
                    
                    if not df.empty:
                        df = seb.forcer_format_17520(df, horodates)
                        # Ajout au panier de colonnes au lieu de pd.merge
                        colonnes_a_ajouter[ID_Acteur] = df[ID_Acteur].values
                    
                    p["ID_Interface"] = ID_Acteur
                    p["Nom"] = nom_prospect 
                    
                    if "Latitude" in p:
                        p["Lat_Val"], p["Lon_Val"] = p["Latitude"], p["Longitude"]
                    elif "matching_etablissements" in p and p["matching_etablissements"]:
                        etab = p["matching_etablissements"][0]
                        p["Lat_Val"], p["Lon_Val"] = etab.get("latitude", lat_centre), etab.get("longitude", lon_centre)
                    else:
                        p["Lat_Val"], p["Lon_Val"] = lat_centre, lon_centre
                        
                    if "SIRET" not in p and "matching_etablissements" in p and p["matching_etablissements"]:
                        p["SIRET"] = p["matching_etablissements"][0].get("siret", "Inconnu")
                    elif "siret" in p: p["SIRET"] = p["siret"] 
                    
                    ID_Acteur += 1
                # Concaténation des colonnes
                if colonnes_a_ajouter:
                    df_prospects = pd.DataFrame(colonnes_a_ajouter)
                    df_series = pd.concat([df_series, df_prospects], axis=1)

            with st.spinner("3/3 - Recalcul du centre et du périmètre optimal..."):
                # Calcul des scores de coïncidence
                liste_tous_id = [p["ID_Acteur"] for p in st.session_state["Participants_Predefinis"]] + \
                                [p["ID_Interface"] for p in liste_prospects if "ID_Interface" in p]
                dict_scores = seb.calculer_score_consommation(liste_tous_id, df_series)
                
                # Initialisation pour calcul du centre
                acteurs_pour_seb = []
                cache_insee = {}
                # Cache GPS pour prévenir le crash de l'API Géo
                if "Cache_GPS_INSEE" not in st.session_state:
                    st.session_state["Cache_GPS_INSEE"] = {}
                    
                # Pré-calcul du poids solaire pour accélérer la boucle While
                solaire_array = df_series["Solaire_kWh"].values if "Solaire_kWh" in df_series else [0.0]*17520
                
                for p in st.session_state["Participants_Predefinis"]:
                    lat, lon = float(p["Latitude"]), float(p["Longitude"])
                    gps_key = f"{round(lat, 2)}_{round(lon, 2)}"
                    if gps_key in st.session_state["Cache_GPS_INSEE"]:
                        code_insee = st.session_state["Cache_GPS_INSEE"][gps_key]
                    else:
                        _, code_insee = seb.obtenir_ville_par_gps(lat, lon)
                        st.session_state["Cache_GPS_INSEE"][gps_key] = code_insee
                    niv = nathan.obtenir_niveau_insee(code_insee) if code_insee else 2
                    id_act = p["ID_Acteur"]
                    poids_sol = (df_series[id_act] * solaire_array).sum() if id_act in df_series else 0.0
                    # Ajout des acteurs avec leurs caractéristiques
                    acteurs_pour_seb.append({
                        "ID_Acteur": id_act,
                        "Nom": p["Nom"],
                        "Type": p["Type"],
                        "Latitude": lat,
                        "Longitude": lon,
                        "Statut": "Predefini",
                        "Niveau_INSEE": int(niv) if niv else 2, 
                        "Conso_Annuelle_kWh": df_series[id_act].sum() if id_act in df_series else 0,
                        "Est_SDIS": (p["Type"] == "SDIS"),
                        "Score_Coincidence": dict_scores.get(p["ID_Acteur"], 0.0),
                        "Poids_Solaire": poids_sol
                    })
                        
                for p in liste_prospects:
                    if "ID_Interface" in p:
                        lat_p = float(p.get("Lat_Val", lat_centre))
                        lon_p = float(p.get("Lon_Val", lon_centre))
                        id_act = p["ID_Interface"]
                        
                        # Récupération ultra-rapide si le prospect vient de l'API
                        code_insee = None
                        if "matching_etablissements" in p and p["matching_etablissements"]:
                            code_insee = p["matching_etablissements"][0].get("commune")
                            
                        # Repli sur le GPS si aucune donnée
                        if not code_insee:
                            gps_key = f"{round(lat_p, 2)}_{round(lon_p, 2)}"
                            if gps_key in st.session_state["Cache_GPS_INSEE"]:
                                code_insee = st.session_state["Cache_GPS_INSEE"][gps_key]
                            else:
                                _, code_insee = seb.obtenir_ville_par_gps(lat_p, lon_p)
                                st.session_state["Cache_GPS_INSEE"][gps_key] = code_insee
                            
                        if code_insee and code_insee not in cache_insee:
                            niv = nathan.obtenir_niveau_insee(code_insee)
                            cache_insee[code_insee] = int(niv) if niv is not None else 5 # Par défaut 5 parce que c'est possible dans les zones rurales
                            
                        niveau_final = cache_insee.get(code_insee, 5) # Pareil ici
                        poids_sol = (df_series[id_act] * solaire_array).sum() if id_act in df_series else 0.0
                        acteurs_pour_seb.append({
                            "ID_Acteur": id_act,
                            "Nom": p["Nom"],
                            "Type": "Entreprise Consommatrice",
                            "Latitude": lat_p,
                            "Longitude": lon_p,
                            "Statut": "Prospect",
                            "Niveau_INSEE": niveau_final, 
                            "Conso_Annuelle_kWh": df_series[id_act].sum() if id_act in df_series else 0,
                            "Est_SDIS": False,
                            "SIRET": p.get("SIRET", "Inconnu"),
                            "Code_NAF": p.get("Code_NAF", p.get("activite_principale", "Inconnu")),
                            "Score_Coincidence": dict_scores.get(id_act, 0.0),
                            "Poids_Solaire": poids_sol
                        })
                # Conversion du dictionnaire en DataFrame            
                df_acteurs_seb = pd.DataFrame(acteurs_pour_seb)
                # Recalcul du centre optimal avec les prospects en plus
                # Forcer le rayon manuellement
                if choix_rayon == "1 km (Zone urbaine très dense)":
                    rayon_legal_max = 1.0
                    df_acteurs_seb["Niveau_INSEE"] = 1  # FORCE l'algorithme à obéir
                elif choix_rayon == "5 km (Zone périurbaine)":
                    rayon_legal_max = 5.0
                    df_acteurs_seb["Niveau_INSEE"] = 3  # FORCE l'algorithme à obéir
                elif choix_rayon == "10 km (Zone rurale ou dérogation SDIS)":
                    rayon_legal_max = 10.0
                    df_acteurs_seb["Niveau_INSEE"] = 5  # FORCE l'algorithme à obéir
                else:
                    # Calcul Automatique Normal
                    pire_insee = df_acteurs_seb["Niveau_INSEE"].min()
                    if df_acteurs_seb["Est_SDIS"].any(): rayon_legal_max = 10.0
                    elif pire_insee <= 2: rayon_legal_max = 1.0
                    elif pire_insee <= 4: rayon_legal_max = 5.0
                    else: rayon_legal_max = 10.0

                predef_seulement = df_acteurs_seb[df_acteurs_seb["Statut"] == "Predefini"]
                iteration = 0
                    
                coor_centre_final = seb.calculer_centre_optimal(df_acteurs_seb, df_series)
                
                # Vérification de sécurité pour les membres prédéfinis
                predef_seulement = df_acteurs_seb[df_acteurs_seb["Statut"] == "Predefini"]
                iteration = 0

                if not predef_seulement.empty:
                    # Barycentre des prédéfinis
                    lat_moyen_predef = predef_seulement["Latitude"].mean()
                    lon_moyen_predef = predef_seulement["Longitude"].mean()
                    
                    # On vire directement de l'équation les prospects de l'API qui sont situés 
                    # à plus de 1.5x le rayon légal des prédéfinis. Ils ne rentreront jamais.
                    a_garder = []
                    for _, r in df_acteurs_seb.iterrows():
                        if r["Statut"] == "Predefini":
                            a_garder.append(True)
                        else:
                            d = seb.calculer_distance_gps(lat_moyen_predef, lon_moyen_predef, r["Latitude"], r["Longitude"])
                            a_garder.append(d <= (rayon_legal_max * 1.5))
                            
                    df_acteurs_seb = df_acteurs_seb[a_garder]
                    
                    # BOUCLE D'ÉLIMINATION ITÉRATIVE SÉCURISÉE
                    centre_trouve = False
                    while True:
                        # Calculer le barycentre avec la liste ACTUELLE
                        poids_tot = df_acteurs_seb["Poids_Solaire"].sum()
                        if poids_tot > 0:
                            lat_test = (df_acteurs_seb["Latitude"] * df_acteurs_seb["Poids_Solaire"]).sum() / poids_tot
                            lon_test = (df_acteurs_seb["Longitude"] * df_acteurs_seb["Poids_Solaire"]).sum() / poids_tot
                        else:
                            lat_test = df_acteurs_seb["Latitude"].mean()
                            lon_test = df_acteurs_seb["Longitude"].mean()
                        
                        predef_actuels = df_acteurs_seb[df_acteurs_seb["Statut"] == "Predefini"]
                        
                        if not predef_actuels.empty:
                            max_dist_predef = max(
                                seb.calculer_distance_gps(lat_test, lon_test, r["Latitude"], r["Longitude"])
                                for _, r in predef_actuels.iterrows()
                            )
                        else:
                            max_dist_predef = 0
                    
                        if max_dist_predef <= rayon_legal_max:
                            # Succès : le barycentre englobe tous les acteurs obligatoires
                            lat_centre_final = lat_test
                            lon_centre_final = lon_test
                            centre_trouve = True
                            break
                        else:
                            # Échec : le centre est trop tiré par les prospects. On élimine le moins pertinent.
                            prospects_actuels = df_acteurs_seb[df_acteurs_seb["Statut"] == "Prospect"].copy()
                    
                            if prospects_actuels.empty:
                                st.error(f"❌ Vos acteurs prédéfinis sont trop éloignés les uns des autres ({round(max_dist_predef, 2)} km) pour tenir dans le rayon légal de {rayon_legal_max} km.")
                                centre_trouve = False
                                break
                    
                            # Ciblage et élimination du prospect le plus éloigné du point moyen des prédéfinis
                            prospects_actuels["Dist_Predef"] = prospects_actuels.apply(
                                lambda row: seb.calculer_distance_gps(lat_moyen_predef, lon_moyen_predef, row["Latitude"], row["Longitude"]),
                                axis=1
                            )
                            
                            prospects_trop_loins = prospects_actuels[prospects_actuels["Dist_Predef"] > rayon_legal_max]
                            # Eliminer les prospects trop loins
                            if not prospects_trop_loins.empty:
                                prospects_trop_loins = prospects_trop_loins.sort_values(by="Dist_Predef", ascending=False)
                                id_a_eliminer = prospects_trop_loins.iloc[0]["ID_Acteur"]
                            else:
                                prospects_tries = prospects_actuels.sort_values(by=["Score_Coincidence", "Dist_Predef"], ascending=[True, False])
                                id_a_eliminer = prospects_tries.iloc[0]["ID_Acteur"]
                    
                            df_acteurs_seb = df_acteurs_seb[df_acteurs_seb["ID_Acteur"] != id_a_eliminer]
                            iteration += 1
                    
                    if not centre_trouve:
                        st.warning("⚠️ Impossible de générer le scénario. Veuillez modifier l'emplacement de vos acteurs principaux.")
                    else:
                        resultat_scenario = seb.evaluer_meilleur_scenario_acc(df_acteurs_seb, lat_centre_final, lon_centre_final)
                
            if "Erreur" in resultat_scenario:
                st.error(f"❌ Impossible de former la boucle : {resultat_scenario['Erreur']}")
            else:
                acteurs_retenus = resultat_scenario["Acteurs_Finaux"]
                Prospects_Finaux = []
                
                for a in acteurs_pour_seb:
                    if a["Statut"] == "Prospect" and a["ID_Acteur"] in acteurs_retenus:
                        Prospects_Finaux.append({
                            "ID_Acteur": a["ID_Acteur"],
                            "Nom": a["Nom"],
                            "Type": "Entreprise Consommatrice",
                            "Statut": "Prospect API",
                            "SIRET": a.get("SIRET", "Inconnu"),
                            "Code_NAF": a.get("Code NAF", "Inconnu"),
                            "Latitude": a["Latitude"],
                            "Longitude": a["Longitude"],
                            "Score": a.get("Score_Coincidence", 0.0)
                        })
                # On trie les prospects finaux par Score (conso_t * prod_t/prod_max)
                Prospects_Finaux = sorted(Prospects_Finaux, key=lambda x: x["Score"], reverse=True)
                
                st.session_state["Prospects_API"] = Prospects_Finaux
                st.session_state["calcul_lance"] = True
                
                # SAUVEGARDE DES INFOS DU CERCLE
                st.session_state["centre_lat"] = lat_centre_final
                st.session_state["centre_lon"] = lon_centre_final
                st.session_state["rayon_opti"] = resultat_scenario['Rayon_Applique_km']
                st.session_state["nom_scenario"] = resultat_scenario['Scenario_Retenu']
                
                st.success(f"✅ Scénario '{resultat_scenario['Scenario_Retenu']}' appliqué ! Rayon optimal calculé : {resultat_scenario['Rayon_Applique_km']} km.")
                time.sleep(2) 
                
                if "editor_partie3" in st.session_state: del st.session_state["editor_partie3"]
                st.rerun()

    if st.session_state.get("calcul_lance", False):
        
        # =========================================================
        # LA CARTE DU PÉRIMÈTRE ACC
        # =========================================================
        if "rayon_opti" in st.session_state:
            st.markdown(f"**📍 Visualisation du Périmètre ({st.session_state['nom_scenario']} - Rayon : {st.session_state['rayon_opti']} km)**")
            
            m_acc = folium.Map(location=[st.session_state["centre_lat"], st.session_state["centre_lon"]], zoom_start=12)
            
            # Cercle du rayon de Seb (Folium demande un rayon en mètres, d'où le * 1000)
            folium.Circle(
                location=[st.session_state["centre_lat"], st.session_state["centre_lon"]],
                radius=st.session_state["rayon_opti"] * 1000, 
                color="green",
                weight=2,
                fill=True,
                fill_opacity=0.15,
                tooltip=f"Périmètre ACC ({st.session_state['rayon_opti']} km)"
            ).add_to(m_acc)
            
            # Punaise rouge pour le centre du projet
            folium.Marker(
                [st.session_state["centre_lat"], st.session_state["centre_lon"]], 
                icon=folium.Icon(color="red", icon="star"),
                tooltip="Centre de Gravité du Projet"
            ).add_to(m_acc)
            
            # PUNAISES POUR LES ACTEURS VALIDÉS
            for p in st.session_state["Participants_Predefinis"]:
                # On différencie visuellement les originaux (bleu) des prospects validés (vert)
                if p.get("Statut") in ["Predefini", "Importé"]:
                    couleur_punaise = "blue"
                    icone_punaise = "home"
                    texte_tooltip = f"{p['Nom']} (Prédéfini)"
                else:
                    couleur_punaise = "green"
                    icone_punaise = "ok" # Icône de validation
                    texte_tooltip = f"{p['Nom']} (Prospect Validé)"
                    
                folium.Marker(
                    [float(p["Latitude"]), float(p["Longitude"])],
                    icon=folium.Icon(color=couleur_punaise, icon=icone_punaise),
                    tooltip=texte_tooltip
                ).add_to(m_acc)
                
            # PUNAISES POUR LES PROSPECTS EN ATTENTE
            for p in st.session_state["Prospects_API"]:
                folium.Marker(
                    [float(p["Latitude"]), float(p["Longitude"])],
                    icon=folium.Icon(color="orange", icon="briefcase"),
                    tooltip=f"{p['Nom']} (En attente)"
                ).add_to(m_acc)

            st_folium(m_acc, use_container_width=True, height=450, key="map_resultat_acc")

        # =========================================================
        # SÉLECTION ET VALIDATION DE LA PMO GLOBALE
        # =========================================================
        st.write("---")
        st.subheader("Constitution de la PMO finale")
        st.info("💡 Vos acteurs prédéfinis sont déjà validés. Cochez les prospects trouvés par l'API que vous souhaitez intégrer au projet.")
        
        # Initialisation de la corbeille
        if "Corbeille_Prospects" not in st.session_state:
            st.session_state["Corbeille_Prospects"] = []
            
        col_attente, col_valides = st.columns(2)
        
        # TABLEAU 1 : EN ATTENTE (Prospects API)
        with col_attente:
            st.markdown("### ⏳ Prospects dans la zone")
            if len(st.session_state["Prospects_API"]) == 0:
                st.warning("Aucun prospect en attente.")
            else:
                df_attente = pd.DataFrame(st.session_state["Prospects_API"])
                df_attente.insert(0, "Ajouter", False)
                
                cols_voulues = ["Ajouter", "Nom", "Type", "Statut", "Score", "SIRET"]
                cols_a_afficher = [c for c in cols_voulues if c in df_attente.columns]
                
                df_attente_edite = st.data_editor(
                    df_attente[cols_a_afficher], 
                    num_rows="dynamic", use_container_width=True, hide_index=True, key="editor_attente"
                )
                
                if len(df_attente_edite) < len(df_attente):
                    noms_suppr = set(df_attente["Nom"]) - set(df_attente_edite["Nom"])
                    for nom in noms_suppr:
                        if nom not in st.session_state["Blacklist"]: 
                            st.session_state["Blacklist"].append(nom)
                            
                            prospect = next((p for p in st.session_state["Prospects_API"] if p["Nom"] == nom), None)
                            if prospect: st.session_state["Corbeille_Prospects"].append(prospect)
                            
                        st.session_state["Prospects_API"] = [p for p in st.session_state["Prospects_API"] if p["Nom"] != nom]
                        st.toast(f"🚫 {nom} envoyé sur liste noire.")
                    if "editor_attente" in st.session_state: del st.session_state["editor_attente"]
                    st.rerun()
                # Pour passer un prospect en attente à un acteur validé
                if st.button("➡️ Ajouter les acteurs sélectionnés", type="primary"):
                    a_transferer = df_attente_edite[df_attente_edite["Ajouter"] == True]
                    if not a_transferer.empty:
                        noms = a_transferer["Nom"].tolist()
                        for p in st.session_state["Prospects_API"]:
                            if p["Nom"] in noms:
                                st.session_state["Participants_Predefinis"].append(p) # RETOUR A LA FUSION !
                                
                        st.session_state["Prospects_API"] = [p for p in st.session_state["Prospects_API"] if p["Nom"] not in noms]
                        st.toast(f"✅ {len(noms)} prospect(s) intégré(s) au projet !")
                        if "editor_attente" in st.session_state: del st.session_state["editor_attente"]
                        if "editor_valides" in st.session_state: del st.session_state["editor_valides"]
                        if "editor_partie2" in st.session_state: del st.session_state["editor_partie2"] # MàJ du grand tableau !
                        st.rerun()

        # TABLEAU 2 : VALIDÉS (Projet Final)
        with col_valides:
            st.markdown("### ✅ Acteurs Validés")
            
            pmo_a_afficher = st.session_state["Participants_Predefinis"] # PLUS BESOIN D'ADDITIONNER
            
            if len(pmo_a_afficher) == 0:
                st.info("Aucun acteur validé.")
            else:
                df_valides = pd.DataFrame(pmo_a_afficher)
                df_valides.insert(0, "Retirer", False)
                
                cols_voulues = ["Retirer", "Nom", "Type", "Statut", "Score", "SIRET"]
                cols_a_afficher = [c for c in cols_voulues if c in df_valides.columns]
                
                df_valides_edite = st.data_editor(
                    df_valides[cols_a_afficher], 
                    num_rows="dynamic", use_container_width=True, hide_index=True, key="editor_valides"
                )
                
                # Suppression vers la Liste Noire
                if len(df_valides_edite) < len(df_valides):
                    noms_suppr = set(df_valides["Nom"]) - set(df_valides_edite["Nom"])
                    for nom in noms_suppr:
                        acteur = next((p for p in st.session_state["Participants_Predefinis"] if p["Nom"] == nom), None)
                        
                        if acteur and acteur.get("Statut") in ["Predefini", "Importé"]:
                            st.warning(f"⚠️ Impossible de supprimer le Prédéfini '{nom}' ici. Veuillez remonter à la Partie 2.")
                        else:
                            if nom not in st.session_state["Blacklist"]: 
                                st.session_state["Blacklist"].append(nom)
                                if acteur: st.session_state["Corbeille_Prospects"].append(acteur)
                                
                            st.session_state["Participants_Predefinis"] = [p for p in st.session_state["Participants_Predefinis"] if p["Nom"] != nom]
                            st.toast(f"🚫 {nom} envoyé sur liste noire.")
                    if "editor_valides" in st.session_state: del st.session_state["editor_valides"]
                    if "editor_partie2" in st.session_state: del st.session_state["editor_partie2"]
                    st.rerun()

                if st.button("⬅️ Remettre en attente", type="secondary"):
                    a_retirer = df_valides_edite[df_valides_edite["Retirer"] == True]
                    if not a_retirer.empty:
                        noms = a_retirer["Nom"].tolist()
                        nb_retires = 0
                        noms_vraiment_retires = []
                        
                        for p in st.session_state["Participants_Predefinis"]:
                            if p["Nom"] in noms:
                                if p.get("Statut") in ["Predefini", "Importé"]:
                                    st.warning(f"⚠️ '{p['Nom']}' est un acteur prédéfini, il ne peut pas être mis en attente.")
                                else:
                                    st.session_state["Prospects_API"].append(p)
                                    noms_vraiment_retires.append(p["Nom"])
                                    nb_retires += 1
                                
                        # On ne retire des validés QUE les prospects API
                        st.session_state["Participants_Predefinis"] = [p for p in st.session_state["Participants_Predefinis"] if p["Nom"] not in noms_vraiment_retires]
                            
                        if nb_retires > 0:
                            st.toast(f"🔙 {nb_retires} prospect(s) renvoyé(s) en attente.")
                            
                        if "editor_attente" in st.session_state: del st.session_state["editor_attente"]
                        if "editor_valides" in st.session_state: del st.session_state["editor_valides"]
                        if "editor_partie2" in st.session_state: del st.session_state["editor_partie2"]
                        st.rerun()

    # ---------------------------------------------------------
    # PARTIE 4 : LA BLACKLIST
    # ---------------------------------------------------------
    st.write("---")
    st.header("4. Gestion de la Liste Noire (Prospects Refusés)")
    if len(st.session_state["Blacklist"]) == 0:
        st.info("Aucun prospect sur liste noire.")
    else:
        df_bl = pd.DataFrame(st.session_state["Blacklist"], columns=["Nom"])
        
        tout_cocher = st.checkbox("☑️ Tout sélectionner (Restauration de masse)")
        
        # On insère la colonne avec la valeur de la case (True si cochée, False sinon)
        df_bl.insert(0, "Restaurer", tout_cocher)
        
        df_bl_edite = st.data_editor(
            df_bl, 
            num_rows="dynamic", 
            use_container_width=True, 
            hide_index=True, 
            key="editor_partie4"
        )
        
        # BOUTON DE RESTAURATION
        if st.button("🔄 Réautoriser les acteurs sélectionnés", type="primary"):
            a_restaurer = df_bl_edite[df_bl_edite["Restaurer"] == True]
            if not a_restaurer.empty:
                noms = a_restaurer["Nom"].tolist()
                
                for nom in noms:
                    st.session_state["Blacklist"].remove(nom)
                    
                    # On le repêche de la corbeille pour le remettre en attente !
                    if "Corbeille_Prospects" in st.session_state:
                        prospect = next((p for p in st.session_state["Corbeille_Prospects"] if p["Nom"] == nom), None)
                        if prospect:
                            st.session_state["Prospects_API"].append(prospect)
                            st.session_state["Corbeille_Prospects"].remove(prospect)
                            
                st.toast(f"✅ {len(noms)} acteur(s) réautorisé(s) et replacé(s) en attente !")
                if "editor_attente" in st.session_state: del st.session_state["editor_attente"]
                if "editor_valides" in st.session_state: del st.session_state["editor_valides"]
                if "editor_partie4" in st.session_state: del st.session_state["editor_partie4"]
                st.rerun()
                
        # (Sécurité) Si l'utilisateur clique quand même sur la petite poubelle de Streamlit
        if len(df_bl_edite) < len(df_bl):
            nom_retire = (set(df_bl["Nom"]) - set(df_bl_edite["Nom"])).pop()
            st.session_state["Blacklist"].remove(nom_retire)
            
            # On le repêche aussi !
            if "Corbeille_Prospects" in st.session_state:
                prospect = next((p for p in st.session_state["Corbeille_Prospects"] if p["Nom"] == nom_retire), None)
                if prospect:
                    st.session_state["Prospects_API"].append(prospect)
                    st.session_state["Corbeille_Prospects"].remove(prospect)
                    
            st.toast(f"✅ {nom_retire} réautorisé !")
            if "editor_attente" in st.session_state: del st.session_state["editor_attente"]
            if "editor_valides" in st.session_state: del st.session_state["editor_valides"]
            if "editor_partie4" in st.session_state: del st.session_state["editor_partie4"]
            st.rerun()
            
            
# ==========================================
# BLOC 2 : OPTIMISATION DE L'ACC
# ==========================================

elif page == "Optimisation de l'ACC":
    st.title("Optimisation de l'Autoconsommation Collective")
    st.subheader("Période de facturation")
    pmo_globale=st.session_state["Participants_Predefinis"]
    col_m, col_a = st.columns(2)

    with col_m:
        liste_mois = ["Janvier", "Février", "Mars", "Avril", "Mai", "Juin", 
                      "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre"]
        mois_actuel = datetime.date.today().month
        mois_choisi = st.selectbox("Mois", liste_mois, index=mois_actuel - 1)
        
    with col_a:
        annee_actuelle = datetime.date.today().year
 
        liste_annees = [annee_actuelle - 1, annee_actuelle, annee_actuelle + 1]
        annee_choisie = st.selectbox("Année", liste_annees, index=1) # index=1 pour tomber sur l'année en cours
        
    st.header("1. Profils Énergétiques et Financiers Détaillés")
    
    
    if len(pmo_globale) == 0:
        st.warning("⚠️ Aucun participant chargé. Veuillez d'abord alimenter le Bloc 1.")
    else:
        for idx, participant in enumerate(pmo_globale):
            if isinstance(participant, dict):
                nom = participant.get("Nom", f"Acteur_Inconnu_{idx}")
                type_act = participant.get("Type", "Inconnu")
            else:
                continue # Ignore les données corrompues en mémoire
            
            if nom not in st.session_state["Parametres_Acteurs"] or not isinstance(st.session_state["Parametres_Acteurs"][nom], dict):
                st.session_state["Parametres_Acteurs"][nom] = {} if type_act == "Producteur" else {"pourcentage": 0.0, "type_contrat": "Base", "prix": {"Base": 0.25}, "abonnement": 150.0}
            
            params = st.session_state["Parametres_Acteurs"][nom]
            
            with st.expander(f"🏢 {nom} ({type_act})", expanded=False):
                col_i, col_u = st.columns(2)
                with col_i:
                    # Import des courbes
                    if nom in st.session_state["Courbes_Importees_Optimisation"]: st.success(f"✅ Fichier lié : {st.session_state['Courbes_Importees_Optimisation'][nom]}")
                    else: st.warning("Veuillez importer la courbe du mois actuel")
                with col_u:
                    lbl = "Importer courbe de charge (CSV)" if type_act != "Producteur" else "Importer courbe production (CSV)"
                    # Ajout de l'index (idx) pour garantir une clé unique
                    fichier = st.file_uploader(lbl, type=["csv"], key=f"opt_up_{idx}_{nom}")
                    if fichier is not None and nom not in st.session_state["Courbes_Importees_Optimisation"]:
                        os.makedirs("Courbes_Importees", exist_ok=True)
                        chemin_complet = os.path.join("Courbes_Importees", fichier.name)
                        with open(chemin_complet, "wb") as f: f.write(fichier.getbuffer())
                        st.session_state["Courbes_Importees_Optimisation"][nom] = chemin_complet
                        st.rerun()
                   
                    elif fichier is None and nom in st.session_state["Courbes_Importees_Optimisation"]:
                        del st.session_state["Courbes_Importees_Optimisation"][nom]
                        st.rerun()
                
                st.write("---")
                st.markdown("**⚙️ Configuration de la facturation et répartition**")
                
                if type_act != "Producteur":
                    col_p1, col_p2, col_p3 = st.columns(3)
                    # Ajout de l'index sur tous les widgets
                    with col_p1: n_pct = st.number_input("Clé allouée fixe (%)", 0.0, 100.0, float(params.get("pourcentage", 0.0)), 5.0, key=f"opct_{idx}_{nom}")
                    with col_p2:
                        lst_c = ["Base", "HP/HC", "HP/HC Été/Hiver"]
                        n_contrat = st.selectbox("Contrat de fourniture", lst_c, index=lst_c.index(params.get("type_contrat", "Base")) if params.get("type_contrat") in lst_c else 0, key=f"op_ct_{idx}_{nom}")
                    with col_p3: n_abo = st.number_input("Coût Abonnement Fournisseur (€/mois)", min_value=0.0, value=float(params.get("abonnement", 30.0)), step=10.0, key=f"op_ab_{idx}_{nom}")
                    # Entrer les tarifs d'élec
                    n_prix = {}
                    n_prix_revente = params.get("prix_revente", {}) if isinstance(params.get("prix_revente"), dict) else {}
                    st.caption(f"Grille tarifaire (€/kWh) - {n_contrat}")
                    if n_contrat == "Base":
                        cx1, cx2 = st.columns(2)
                        with cx1: n_prix["Base"] = st.number_input("Tarif Unique Fournisseur (€/kWh)", value=float(params.get("prix", {}).get("Base", 0.25)), step=0.01, format="%.3f", key=f"op_b_{idx}_{nom}")
                        with cx2: n_prix_revente["Base"] = st.number_input("Case Prix de Revente Unique (€/kWh)", value=float(n_prix_revente.get("Base", 0.15)), step=0.01, format="%.3f", key=f"op_br_{idx}_{nom}")                    
                    elif n_contrat == "HP/HC":
                        cx1, cx2, cx3, cx4 = st.columns(4)
                        with cx1: n_prix["HP"] = st.number_input("HP Fournisseur", value=float(params.get("prix", {}).get("HP", 0.27)), step=0.01, format="%.3f", key=f"op_hp_{idx}_{nom}")
                        with cx2: n_prix_revente["HP"] = st.number_input("HP Revente", value=float(n_prix_revente.get("HP", 0.16)), step=0.01, format="%.3f", key=f"op_hpr_{idx}_{nom}")
                        with cx3: n_prix["HC"] = st.number_input("HC Fournisseur", value=float(params.get("prix", {}).get("HC", 0.20)), step=0.01, format="%.3f", key=f"op_hc_{idx}_{nom}")
                        with cx4: n_prix_revente["HC"] = st.number_input("HC Revente", value=float(n_prix_revente.get("HC", 0.12)), step=0.01, format="%.3f", key=f"op_hcr_{idx}_{nom}")
                    elif n_contrat == "HP/HC Été/Hiver":
                        cx1, cx2 = st.columns(2)
                        with cx1:
                            n_prix["HP_Hiver"] = st.number_input("HP Hiver Fournisseur", value=float(params.get("prix", {}).get("HP_Hiver", 0.28)), format="%.3f", key=f"op_hph_{idx}_{nom}")
                            n_prix_revente["HP_Hiver"] = st.number_input("HP Hiver Revente", value=float(n_prix_revente.get("HP_Hiver", 0.17)), format="%.3f", key=f"op_hphr_{idx}_{nom}")
                            n_prix["HP_Ete"] = st.number_input("HP Été Fournisseur", value=float(params.get("prix", {}).get("HP_Ete", 0.26)), format="%.3f", key=f"op_hpe_{idx}_{nom}")
                            n_prix_revente["HP_Ete"] = st.number_input("HP Été Revente", value=float(n_prix_revente.get("HP_Ete", 0.15)), format="%.3f", key=f"op_hper_{idx}_{nom}")
                        with cx2:
                            n_prix["HC_Hiver"] = st.number_input("HC Hiver Fournisseur", value=float(params.get("prix", {}).get("HC_Hiver", 0.22)), format="%.3f", key=f"op_hch_{idx}_{nom}")
                            n_prix_revente["HC_Hiver"] = st.number_input("HC Hiver Revente", value=float(n_prix_revente.get("HC_Hiver", 0.13)), format="%.3f", key=f"op_hchr_{idx}_{nom}")
                            n_prix["HC_Ete"] = st.number_input("HC Été Fournisseur", value=float(params.get("prix", {}).get("HC_Ete", 0.19)), format="%.3f", key=f"op_hce_{idx}_{nom}")
                            n_prix_revente["HC_Ete"] = st.number_input("HC Été Revente", value=float(n_prix_revente.get("HC_Ete", 0.11)), format="%.3f", key=f"op_hcer_{idx}_{nom}")
                    
                    st.session_state["Parametres_Acteurs"][nom] = {"pourcentage": n_pct, "type_contrat": n_contrat, "prix": n_prix, "prix_revente": n_prix_revente, "abonnement": n_abo} 
                else:
                    st.markdown("**⚙️ Valorisation Surplus Solaire**")
                    t_oa = st.number_input("Tarif réglementé EDF OA (€/kWh)", min_value=0.0, value=float(params.get("tarif_edf_oa", 0.10)), step=0.01, format="%.3f", key=f"op_oa_{idx}_{nom}")
                    st.session_state["Parametres_Acteurs"][nom] = {"tarif_edf_oa": t_oa}

        st.write("---")
        st.header("2. Lancement des Algorithmes d'Optimisation Financière")
        blocage = any(p["Nom"] not in st.session_state["Courbes_Importees_Optimisation"] for p in pmo_globale)
        if st.button("Lancer les calculs d'optimisation", type="primary", disabled=blocage):
            mois_chiffre = {"Janvier": 1, "Février": 2, "Mars": 3, "Avril": 4, "Mai": 5, "Juin": 6, "Juillet": 7, "Août": 8, "Septembre": 9, "Octobre": 10, "Novembre": 11, "Décembre": 12}[mois_choisi]
            _, nb_jours = calendar.monthrange(annee_choisie, mois_chiffre)
        
            df_series = pd.DataFrame({"Horodate": pd.date_range(start=f"{annee_choisie}-{mois_chiffre:02d}-01 00:00", periods=nb_jours * 48, freq="30min")})
            df_series = df_series.set_index("Horodate")
            df_series["Solaire_kWh"] = 0.0
            
            dict_contrats, parts_fixes = {}, {}
            tarif_oa_global = 0.10
            
            for p in pmo_globale:
                nom_acteur = p["Nom"]
                id_acteur = p.get("ID_Acteur", nom_acteur)
                params_act = st.session_state["Parametres_Acteurs"].get(nom_acteur, {})
                
                if p["Type"] == "Producteur":
                    tarif_oa_global = params_act.get("tarif_edf_oa", 0.10)
                    df_series[id_acteur] = 0.0
                    fichier = st.session_state["Courbes_Importees_Optimisation"].get(nom_acteur)
                    df_prod = seb.importer_courbe_production_reelle(fichier)
                    if not df_prod.empty:
                        df_prod = seb.uniformiser_pas_de_temps(df_prod, 'Horodate', 'Production_kWh', '30min', 'puissance').set_index("Horodate")
                        df_series["Solaire_kWh"] = df_series["Solaire_kWh"].add(df_prod["Production_kWh"], fill_value=0.0)
                else:
                    parts_fixes[id_acteur] = params_act.get("pourcentage", 0.0)
                    dict_contrats[id_acteur] = {"type_contrat": params_act.get("type_contrat", "Base"), "prix": params_act.get("prix", {}), "prix_revente": params_act.get("prix_revente", {})}
                    
                    chemin_fichier = st.session_state["Courbes_Importees_Optimisation"].get(nom_acteur)
                    df = seb.importer_courbe_enedis_reelle(chemin_fichier, "Temp")
                    if not df.empty:
                        col_valeur = [col for col in df.columns if col != "Horodate"][0]
                        df = df.rename(columns={col_valeur: "Valeur"})
                        df = seb.uniformiser_pas_de_temps(df, 'Horodate', 'Valeur', '30min', 'puissance').set_index("Horodate")
                        df_series[id_acteur] = df["Valeur"]
                    else:
                        df_series[id_acteur] = 0.0

            df_series = df_series.fillna(0.0).reset_index()
            
            with st.spinner("Simulation linéaire en cours..."):
                df_bilan, surplus_total = seb.simuler_projet_complet(df_series, dict_contrats, parts_fixes, tarif_oa_global)
            
            # Reconstruction graphique des identifiants
            dict_noms = {p.get("ID_Acteur", p["Nom"]): p["Nom"] for p in pmo_globale}
            dict_noms['Producteur (Gains nets ACC)'] = 'Producteur (Gains nets ACC)'
            df_bilan["ID_Acteur"] = df_bilan["ID_Acteur"].map(lambda x: dict_noms.get(x, str(x)))
            
            ids_consommateurs_noms = [p["Nom"] for p in pmo_globale if p["Type"] != "Producteur"]
            df_series_graph = df_series.copy()
            for p in pmo_globale:
                if p["Type"] != "Producteur":
                    df_series_graph.rename(columns={p.get("ID_Acteur", p["Nom"]): p["Nom"]}, inplace=True)
            
            # STOCKAGE PERSISTANT POUR ÉVITER L'EFFACEMENT AU TÉLÉCHARGEMENT
            st.session_state["df_bilan_saved"] = df_bilan
            st.session_state["surplus_total_saved"] = surplus_total
            st.session_state["df_series_graph_saved"] = df_series_graph
            st.session_state["ids_consommateurs_noms_saved"] = ids_consommateurs_noms
            st.success("✅ Simulation finalisée avec succès !")
            st.rerun()

        # RE-AFFICHAGE AUTOMATIQUE ET PERSISTANT
        if st.session_state.get("df_bilan_saved") is not None:
            df_bilan = st.session_state["df_bilan_saved"]
            surplus_total = st.session_state["surplus_total_saved"]
            df_series_graph = st.session_state["df_series_graph_saved"]
            ids_consommateurs_noms = st.session_state["ids_consommateurs_noms_saved"]
                    
            # AFFICHAGE DES LIVRABLES (PLOTLY)
            st.write("---")
            st.subheader("📊 Résultats de la simulation")
            
            st.metric(label="Surplus total réinjecté sur le réseau (kWh)", value=f"{surplus_total} kWh")
            # Trouver les vrais IDs en excluant les producteurs
            ids_consommateurs = [p.get("ID_Acteur", p.get("ID_Interface")) for p in pmo_globale if p.get("Type") != "Producteur"]
            
            # Graphique énergétique
            if hasattr(seb, "generer_courbe_de_charge"):
                st.markdown("#### 📈 Bilan énergétique horaire")
                df_series_graph['Conso_Totale_kWh'] = df_series_graph[ids_consommateurs_noms].sum(axis=1)
                
                fig_courbes = seb.generer_courbe_de_charge(df_series_graph, ids_consommateurs_noms)
                st.plotly_chart(fig_courbes, use_container_width=True)
            
            # Graphique financier
            if hasattr(seb, "generer_graphique_financier"):
                st.markdown("#### 💶 Répartition financière")
                fig_finance = seb.generer_graphique_financier(df_bilan)
                fig_finance.update_layout(yaxis={'categoryorder':'total ascending'})
                st.plotly_chart(fig_finance, use_container_width=True)
            
            # Rapport PDF et Factures
            st.write("---")
            col_pdf, col_factures = st.columns(2)
            
            with col_pdf:
                fichier_pdf = seb.exporter_rapport_pdf(df_bilan, surplus_total, fig_courbes)
                if fichier_pdf and os.path.exists(fichier_pdf):
                    with open(fichier_pdf, "rb") as pdf_file:
                        st.download_button(
                            label="📥 Télécharger le rapport global (PDF)",
                            data=pdf_file,
                            file_name="Rapport_ACC_IBC.pdf",
                            mime="application/pdf",
                            type="primary",
                            use_container_width=True
                        )
            
            with col_factures:
                dossier_factures = f"Factures_{mois_choisi}_{annee_choisie}"
                nom_zip = f"{dossier_factures}.zip"
                os.makedirs(dossier_factures, exist_ok=True)
                
                for index, row in df_bilan.iterrows():
                    nom_act = row['ID_Acteur']
                    kwh = row['Total_Autoconsomme_kWh']
                    euros = row['Economie_Generee_Euros']
                    if kwh > 0 and row['Type_Ligne'] == 'Consommateur':
                        t_moyen = euros / kwh if kwh > 0 else 0
                        seb.generer_facture_mensuelle(str(nom_act), kwh, t_moyen, euros, str(mois_choisi), str(annee_choisie), dossier_factures)
                            
                # Compression de toutes les factures
                import shutil
                shutil.make_archive(dossier_factures, 'zip', dossier_factures)
                
                # Affichage du bouton
                if os.path.exists(nom_zip):
                    with open(nom_zip, "rb") as zip_file:
                        st.download_button(
                            label="🖨️ Télécharger les factures (Dossier ZIP)",
                            data=zip_file,
                            file_name=nom_zip,
                            mime="application/zip",
                            type="secondary",
                            use_container_width=True
                        )