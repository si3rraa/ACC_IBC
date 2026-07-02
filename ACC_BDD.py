import sqlite3
import os
import requests
import pandas as pd
from math import radians, sin, cos, atan2, sqrt
from concurrent.futures import ThreadPoolExecutor
import json



# ============================================================
# CONFIGURATION — une seule base pour tout
# ============================================================
DB_PATH = "data/ibc_acc.db"

# ============================================================
# CONNEXION
# ============================================================
def get_connection():
    os.makedirs("data", exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

# ============================================================
# INITIALISATION — crée toutes les tables
# ============================================================
def init_database():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.executescript('''
       CREATE TABLE IF NOT EXISTS UTILISATEUR (
           ID_Utilisateur INTEGER PRIMARY KEY AUTOINCREMENT,
           Nom_Complet VARCHAR(100) UNIQUE,
           Email VARCHAR(100) UNIQUE,
           Role VARCHAR(50)
         );
        CREATE TABLE IF NOT EXISTS PMO (
        ID_PMO INTEGER PRIMARY KEY AUTOINCREMENT,
        ID_Utilisateur INT,
        Nom_Operation VARCHAR(100) UNIQUE,
        Date_Creation DATE,
        Statut_PMO VARCHAR(50),
        FOREIGN KEY (ID_Utilisateur) REFERENCES UTILISATEUR(ID_Utilisateur)
        );
        CREATE TABLE IF NOT EXISTS DOCUMENT (
            ID_Document INTEGER PRIMARY KEY AUTOINCREMENT,
            ID_PMO INT,
            Type_Doc VARCHAR(50),
            Statut_Signature VARCHAR(50),
            URL_Stockage VARCHAR(225),
            FOREIGN KEY (ID_PMO) REFERENCES PMO(ID_PMO)
        );
        CREATE TABLE IF NOT EXISTS VILLE (
            Code_INSEE   VARCHAR(10) PRIMARY KEY,
            Ville        VARCHAR(100),
            Niveau_INSEE INT
        );
        CREATE TABLE IF NOT EXISTS ACTEUR (
            ID_Acteur        INTEGER PRIMARY KEY AUTOINCREMENT,
            ID_PMO           INT,
            Type_Acteur      VARCHAR(50),
            Statut_Acteur    VARCHAR(50),
            Raison_Sociale   VARCHAR(100),
            SIRET            VARCHAR(14) UNIQUE,
            Code_NAF         VARCHAR(10),
            Score_Coincidence FLOAT,
            Latitude         FLOAT,
            Longitude        FLOAT,
            Code_INSEE       VARCHAR(10),
            FOREIGN KEY (ID_PMO)      REFERENCES PMO(ID_PMO),
            FOREIGN KEY (Code_INSEE)  REFERENCES VILLE(Code_INSEE)
        );
        CREATE TABLE IF NOT EXISTS COMPTEUR (
            PRM_Linky VARCHAR(14) PRIMARY KEY,
            ID_Acteur INT,
            Type_Compteur VARCHAR(50),
            Puissance_Souscrite FLOAT,
            FOREIGN KEY (ID_Acteur) REFERENCES ACTEUR(ID_Acteur)
        );
        CREATE TABLE IF NOT EXISTS INSTALLATION_PV (
            ID_PV INTEGER PRIMARY KEY AUTOINCREMENT,
            PRM_Linky VARCHAR(14) UNIQUE,
            Puissance_Crete FLOAT,
            Azimut INT,
            Inclinaison INT,
            FOREIGN KEY (PRM_Linky) REFERENCES COMPTEUR(PRM_Linky)
        );
        CREATE TABLE IF NOT EXISTS COURBE_TEMPORELLE (
            ID_MESURE INTEGER PRIMARY KEY AUTOINCREMENT,
            PRM_Linky VARCHAR(14),
            Horodate DATETIME,
            LATITUDE FLOAT,
            LONGITUDE FLOAT,
            Volume_kWh FLOAT,
            Est_Simule BOOLEAN,
            Code_NAF VARCHAR(10),  -- ← ajoute cette colonne
            UNIQUE (PRM_Linky, Horodate),
            FOREIGN KEY (PRM_Linky) REFERENCES COMPTEUR(PRM_Linky)
        );
        CREATE TABLE IF NOT EXISTS CONTRAT_FINANCIER (
            ID_Contrat INTEGER PRIMARY KEY AUTOINCREMENT,
            ID_Producteur INT,
            ID_Consommateur INT,
            Tarif_Achat_Interne FLOAT,
            Commission_IBC FLOAT,
            FOREIGN KEY (ID_Producteur) REFERENCES ACTEUR(ID_Acteur),
            FOREIGN KEY (ID_Consommateur) REFERENCES ACTEUR(ID_Acteur)
        );
        CREATE TABLE IF NOT EXISTS FACTURE (
            ID_Facture INTEGER PRIMARY KEY AUTOINCREMENT,
            ID_Acteur INT,
            Mois_Facturation DATE,
            Volume_Total_kWh FLOAT,
            Montant_HT FLOAT,
            Montant_TTC FLOAT,
            Statut_Paiement VARCHAR(50),
            FOREIGN KEY (ID_Acteur) REFERENCES ACTEUR(ID_Acteur)
        );
    ''')
    conn.commit()
    conn.close()
    print("✓ Base initialisée avec toutes les tables")

# ============================================================
# PROGRAMME 1 — Importer une courbe de charge CSV
# ============================================================
def importer_courbe_csv(fichier_csv, id_acteur=None, code_naf=None):
    """
    Deux cas :
    - Courbe réelle  : importer_courbe_csv('fichier.csv', id_acteur=1)
    - Courbe simulée : importer_courbe_csv('fichier.csv', code_naf='naf10')
    """
    df = pd.read_csv(fichier_csv, sep=';', encoding='utf-8-sig')
    df.columns = ['Horodate', 'Volume_kWh']
    df['Volume_kWh'] = df['Volume_kWh'].astype(str).str.replace(',', '.').astype(float)
    print(f"✓ {len(df)} lignes lues")

    if id_acteur is not None:
        conn = get_connection()
        prm = pd.read_sql(f"SELECT PRM_Linky FROM COMPTEUR WHERE ID_Acteur = {id_acteur}", conn)
        conn.close()
        if prm.empty:
            print(f"✗ Pas de compteur pour l'acteur {id_acteur}")
            return
        prm_linky = prm.iloc[0]['PRM_Linky']
        est_simule = 0
        code_naf_val = None

    elif code_naf is not None:
        prm_linky = None
        est_simule = 1
        code_naf_val = code_naf

    else:
        print("✗ Il faut préciser id_acteur ou code_naf")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    inseres = 0
    ignores = 0

    for index, row in df.iterrows():
        try:
            cursor.execute("""
                INSERT INTO COURBE_TEMPORELLE
                (PRM_Linky, Horodate, Volume_kWh, Est_Simule, Code_NAF)
                VALUES (?, ?, ?, ?, ?)
            """, (prm_linky, row["Horodate"], row["Volume_kWh"], est_simule, code_naf_val))
            inseres += 1
        except sqlite3.IntegrityError:
            ignores += 1

    conn.commit()
    conn.close()
    print(f"✓ {inseres} lignes insérées, {ignores} doublons ignorés")
# ============================================================
# PROGRAMME 2 — Trouver les entreprises dans un rayon GPS
# ============================================================
def distance_km(lat1, lon1, lat2, lon2):
    R = 6371
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
    return R * 2 * atan2(sqrt(a), sqrt(1 - a))

def get_entreprises_commune(code_commune):
    try:
        toutes = []
        for page in range(1, 9):
            reponse = requests.get(
                "https://recherche-entreprises.api.gouv.fr/search",
                params={
                    "code_commune": code_commune,
                    "per_page": 25,
                    "page": page
                },
                timeout=60
            )
            if reponse.status_code != 200:
                break
            resultats = reponse.json().get("results", [])
            if not resultats:
                break
            toutes.extend(resultats)
        return toutes
    except:
        return []

def get_entreprises_rapide(communes):
    codes = [c["code"] for c in communes]
    print(f"→ {len(codes)} requêtes en parallèle...")
    with ThreadPoolExecutor(max_workers=10) as executor:
        resultats = list(executor.map(get_entreprises_commune, codes))
    toutes = []
    for r in resultats:
        toutes.extend(r)
    vus = set()
    uniques = []
    for e in toutes:
        siret = e.get("siret")
        if not siret:
            etabs = e.get("matching_etablissements", [])
            if etabs:
                siret = etabs[0].get("siret")
        if siret and siret not in vus:
            vus.add(siret)
            uniques.append(e)
    print(f"✓ {len(uniques)} entreprises uniques")
    return uniques

def entreprises_rayon(entreprises, lat_centre, lon_centre, rayon_km):
    dans_rayon = []
    for e in entreprises:
        etabs = e.get("matching_etablissements", [])
        if not etabs:
            continue
        etab = etabs[0]
        lat = etab.get("latitude")
        lon = etab.get("longitude")
        if not lat or not lon:
            continue
        try:
            lat = float(lat)
            lon = float(lon)
        except ValueError:
            continue
        dist = distance_km(lat_centre, lon_centre, lat, lon)
        if dist <= rayon_km:
            dans_rayon.append(e)
    print(f"✓ {len(dans_rayon)} entreprises dans le rayon exact")
    return dans_rayon

def inserer_prospects(entreprises, id_pmo=None):
    conn = get_connection()
    cursor = conn.cursor()

    inseres = 0
    ignores = 0

    for e in entreprises:

        raison_sociale = e.get("nom_raison_sociale")

        # Ignorer les entreprises sans nom
        if raison_sociale is None:
            ignores += 1
            continue

        raison_sociale = raison_sociale.strip()

        if raison_sociale == "":
            ignores += 1
            continue

        code_naf = e.get("activite_principale", None)

        etabs = e.get("matching_etablissements", [])

        siret = etabs[0].get("siret") if etabs else None
        lat = float(etabs[0].get("latitude")) if etabs and etabs[0].get("latitude") else None
        lon = float(etabs[0].get("longitude")) if etabs and etabs[0].get("longitude") else None

        if not siret:
            ignores += 1
            continue

        try:
            cursor.execute("""
                INSERT INTO ACTEUR
                (ID_PMO, Type_Acteur, Statut_Acteur,
                 Raison_Sociale, SIRET, Code_NAF,
                 Latitude, Longitude)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                id_pmo,
                "Consommateur",
                "Prospect",
                raison_sociale,
                siret,
                code_naf,
                lat,
                lon
            ))

            inseres += 1

        except sqlite3.IntegrityError:
            ignores += 1

    conn.commit()
    conn.close()

    print(f"✓ {inseres} prospects insérés, {ignores} ignorés")
# ============================================================
# PROGRAMME 3 — Insérer depuis une liste de dictionnaires
# ============================================================
def ajouter_utilisateur(data):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT INTO UTILISATEUR (Nom_Complet, Email, Role)
            VALUES (?, ?, ?)
        ''', (data.get('Nom_Complet', 'Inconnu'), data.get('Email'), data.get('Role')))
        conn.commit()
        print(f"  ✓ Utilisateur {data.get('Nom_Complet', 'Inconnu')} ajouté")
    except sqlite3.IntegrityError:
        print(f"  ✗ Utilisateur déjà en base")
    finally:
        conn.close()

def ajouter_pmo(data):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT INTO PMO (ID_Utilisateur, Nom_Operation, Date_Creation, Statut_PMO)
            VALUES (?, ?, ?, ?)
        ''', (data.get('ID_Utilisateur'), data.get('Nom_Operation', 'Inconnu'),
              data.get('Date_Creation'), data.get('Statut_PMO', 'Etude')))
        conn.commit()
        print(f"  ✓ PMO {data.get('Nom_Operation', 'Inconnu')} ajoutée")
    except sqlite3.IntegrityError:
        print(f"  ✗ PMO déjà en base")
    finally:
        conn.close()

def ajouter_document(data):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT INTO DOCUMENT (ID_PMO, Type_Doc, Statut_Signature, URL_Stockage)
            VALUES (?, ?, ?, ?)
        ''', (data.get('ID_PMO'), data.get('Type_Doc', 'Inconnu'),
              data.get('Statut_Signature', 'En attente'), data.get('URL_Stockage')))
        conn.commit()
        print(f"  ✓ Document {data.get('Type_Doc', 'Inconnu')} ajouté")
    except sqlite3.IntegrityError:
        print(f"  ✗ Document déjà en base")
    finally:
        conn.close()

def ajouter_acteur(data):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT INTO ACTEUR
            (ID_PMO, Type_Acteur, Statut_Acteur, Raison_Sociale, SIRET, Code_NAF)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (data.get('ID_PMO'), data.get('Type_Acteur', 'Consommateur'),
              data.get('Statut_Acteur', 'Prospect'), data.get('Raison_Sociale', 'Inconnu'),
              data.get('SIRET'), data.get('Code_NAF')))
        conn.commit()
        print(f"  ✓ Acteur {data.get('Raison_Sociale', 'Inconnu')} ajouté")
    except sqlite3.IntegrityError:
        print(f"  ✗ Acteur déjà en base")
    finally:
        conn.close()

def ajouter_compteur(data):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT INTO COMPTEUR
            (PRM_Linky, ID_Acteur, Type_Compteur, Latitude, Longitude, Puissance_Souscrite)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (data.get('PRM_Linky'), data.get('ID_Acteur'),
              data.get('Type_Compteur', 'Soutirage'), data.get('Latitude'),
              data.get('Longitude'), data.get('Puissance_Souscrite')))
        conn.commit()
        print(f"  ✓ Compteur {data.get('PRM_Linky', 'Inconnu')} ajouté")
    except sqlite3.IntegrityError:
        print(f"  ✗ Compteur déjà en base")
    finally:
        conn.close()

def ajouter_installation_pv(data):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT INTO INSTALLATION_PV (PRM_Linky, Puissance_Crete, Azimut, Inclinaison)
            VALUES (?, ?, ?, ?)
        ''', (data.get('PRM_Linky'), data.get('Puissance_Crete'),
              data.get('Azimut', 0), data.get('Inclinaison', 25)))
        conn.commit()
        print(f"  ✓ Installation PV ajoutée")
    except sqlite3.IntegrityError:
        print(f"  ✗ Installation PV déjà en base")
    finally:
        conn.close()

def ajouter_compteur(data):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT INTO COMPTEUR
            (PRM_Linky, ID_Acteur, Type_Compteur, Puissance_Souscrite)
            VALUES (?, ?, ?, ?)
        ''', (data.get('PRM_Linky'), data.get('ID_Acteur'),
              data.get('Type_Compteur', 'Soutirage'),
              data.get('Puissance_Souscrite')))
        conn.commit()
        print(f"  ✓ Compteur {data.get('PRM_Linky', 'Inconnu')} ajouté")
    except sqlite3.IntegrityError:
        print(f"  ✗ Compteur déjà en base")
    finally:
        conn.close()

def ajouter_facture(data):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT INTO FACTURE
            (ID_Acteur, Mois_Facturation, Volume_Total_kWh,
             Montant_HT, Montant_TTC, Statut_Paiement)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (data.get('ID_Acteur'), data.get('Mois_Facturation'),
              data.get('Volume_Total_kWh'), data.get('Montant_HT'),
              data.get('Montant_TTC'), data.get('Statut_Paiement', 'En attente')))
        conn.commit()
        print(f"  ✓ Facture ajoutée")
    except sqlite3.IntegrityError:
        print(f"  ✗ Facture déjà en base")
    finally:
        conn.close()

def inserer_liste_dictionnaires(liste):
    """
    Prend une liste de dictionnaires, insère chacun dans la bonne table
    et affiche toute la base à la fin.
    except sqlite3.IntegrityError:
    """
    for data in liste:
        if 'Nom_Complet' in data or 'Email' in data:
            ajouter_utilisateur(data)
        elif 'Nom_Operation' in data or 'Statut_PMO' in data:
            ajouter_pmo(data)
        elif 'Type_Doc' in data or 'Statut_Signature' in data:
            ajouter_document(data)
        elif 'Raison_Sociale' in data or 'Type_Acteur' in data:
            ajouter_acteur(data)
        elif 'PRM_Linky' in data and 'Type_Compteur' in data:
            ajouter_compteur(data)
        elif 'Puissance_Crete' in data:
            ajouter_installation_pv(data)
        elif 'Tarif_Achat_Interne' in data:
            ajouter_contrat(data)
        elif 'Mois_Facturation' in data or 'Montant_HT' in data:
            ajouter_facture(data)
        else:
            print("✗ Impossible de déterminer la table")

    # Afficher toute la base
    conn = get_connection()
    for table in ['UTILISATEUR', 'PMO', 'DOCUMENT', 'ACTEUR', 'COMPTEUR',
                  'INSTALLATION_PV', 'CONTRAT_FINANCIER', 'FACTURE']:
        print(f"\n===== {table} =====")
        df = pd.read_sql(f"SELECT * FROM {table}", conn)
        print(df)
    conn.close()
def afficher_table(nom_table):
    conn = get_connection()
    df = pd.read_sql(f"SELECT * FROM {nom_table}", conn)
    conn.close()
    print(f"\n===== {nom_table} =====")
    return df
def obtenir_production_pvgis(lat, lon, puissance_kw, inclinaison, azimut):
    """
    Interroge l'API européenne PVGIS pour obtenir la vraie courbe de production solaire.
    """
    print(f"☀️ Interrogation de PVGIS pour {puissance_kw} kWc (Inc:{inclinaison}°, Azi:{azimut}°)...")

    url = f"https://re.jrc.ec.europa.eu/api/v5_2/seriescalc?lat={lat}&lon={lon}&raddatabase=PVGIS-SARAH2&outputformat=json&angle={inclinaison}&aspect={azimut}&pvcalculation=1&peakpower={puissance_kw}&loss=14&startyear=2020&endyear=2020"

    try:
        reponse = requests.get(url, timeout=60).json()
        donnees = reponse['outputs']['hourly']
        df = pd.DataFrame(donnees)
        df['Horodate'] = pd.to_datetime(df['time'], format='%Y%m%d:%H%M', utc=True)
        df['Production_kWh'] = df['P'] / 1000.0
        return df[['Horodate', 'Production_kWh']]
    except Exception as e:
        print(f"Erreur de connexion à l'API PVGIS : {e}")
        return pd.DataFrame()
def calculer_scores_naf():
    """
    Calcule le score moyen de consommation pour chaque code NAF
    et retourne un dictionnaire {code_naf: score}.
    """
    conn = get_connection()

    scores_naf = pd.read_sql("""
        SELECT Code_NAF, AVG(Volume_kWh) as Score
        FROM COURBE_TEMPORELLE
        WHERE Est_Simule = 1
        GROUP BY Code_NAF
    """, conn)
    conn.close()

    # Stocker dans un dictionnaire
    scores = {}
    for _, row in scores_naf.iterrows():
        scores[row['Code_NAF']] = round(row['Score'], 3)

    # Afficher
    print("\n===== SCORES PAR CODE NAF =====")
    for naf, score in scores.items():
        print(f"  {naf} → Score : {score}")

    return scores
# ============================================================
# CORRESPONDANCE NAF
# ============================================================
CORRESPONDANCE_NAF = {
    # Agriculture, sylviculture, pêche
    '01': '10', '02': '10', '03': '10',
    # Industries alimentaires et boissons
    '10': '10', '11': '10', '12': '10', '13': '10',
    '14': '10', '15': '10', '16': '10', '17': '10',
    '18': '10', '19': '10',
    # Extraction minières et énergie
    '05': '3600', '06': '3600', '07': '3600', '08': '3600',
    '09': '3600', '35': '3600', '36': '3600', '37': '3600',
    '38': '3600', '39': '3600',
    # Industries manufacturières
    '20': '5510', '21': '5510', '22': '5510', '23': '5510',
    '24': '5510', '25': '5510', '26': '5510', '27': '5510',
    '28': '5510', '29': '5510', '30': '5510', '31': '5510',
    '32': '5510', '33': '5510',
    # Construction
    '41': '5510', '42': '5510', '43': '5510',
    # Commerce de gros et détail
    '45': '4711', '46': '4711', '47': '4711',
    # Transports et entreposage
    '49': '3700', '50': '3700', '51': '3700',
    '52': '3700', '53': '3700',
    # Hébergement
    '55': '55',
    # Restauration
    '56': '55',
    # Edition, audiovisuel, télécommunications
    '58': '7010', '59': '7010', '60': '7010',
    '61': '7010',
    # Informatique
    '62': '7010', '63': '7010',
    # Finance et assurance
    '64': '7010', '65': '7010', '66': '7010',
    # Activités immobilières
    '68': '6831',
    # Activités juridiques comptables conseil
    '69': '7010', '70': '7010', '71': '7010',
    '72': '7010', '73': '7010', '74': '7010', '75': '7010',
    # Services administratifs et soutien
    '77': '7010', '78': '7010', '79': '55',
    '80': '7010', '81': '7010', '82': '7010',
    # Administration publique
    '84': '8411',
    # Enseignement
    '85': '8411',
    # Santé humaine
    '86': '8413',
    # Hébergement médico-social et action sociale
    '87': '8790', '88': '8790',
    # Arts spectacles loisirs
    '90': '55', '91': '55', '92': '55', '93': '55',
    # Autres activités de services
    '94': '8790', '95': '5610', '96': '5610',
    # Ménages employeurs
    '97': '4711', '98': '4711',
    # Organisations extraterritoriales
    '99': '8411',
    # Codes spécifiques fréquents
    '40': '3600',  # Electricité gaz vapeur
    '41': '3600',  # Captage traitement eau
    '44': '4711',  # Commerce detail carburant
    '48': '4711',  # Commerce detail non spécialisé
    '54': '3700',  # Transports par conduites
    '57': '5610',  # Débits de boissons
    '67': '7010',  # Auxiliaires financiers
    '76': '7010',  # Recherche développement
    '83': '6831',  # Agences immobilières
    '89': '8790',  # Autres action sociale
}
def trouver_naf_correspondant(code_naf):
    """
    Trouve le NAF simulé le plus proche pour un code NAF donné.
    """
    if not code_naf:
        return '4711'
    prefix = str(code_naf)[:2]
    return CORRESPONDANCE_NAF.get(prefix, '4711')
def liste_finale_entreprises(latitude, longitude, rayon_km):
    """
    Prend lat, lon et rayon — insère les entreprises dans ACTEUR.
    """
    reponse = requests.get(
        'https://geo.api.gouv.fr/communes',
        params={
            'lat': latitude,
            'lon': longitude,
            'distance': rayon_km * 1000,
            'fields': 'nom,code,centre',
            'format': 'json'
        },
        timeout=10
    )
    communes = reponse.json()
    print(f"✓ {len(communes)} communes trouvées")
    toutes = get_entreprises_rapide(communes)
    dans_rayon = entreprises_rayon(toutes, latitude, longitude, rayon_km)
    inserer_prospects(dans_rayon)
    return dans_rayon
# ============================================================
# CALCUL SCORES AVEC PVGIS
# ============================================================
def calculer_scores_avec_pvgis(lat, lon, rayon_km, puissance_kw, inclinaison, azimut):

    # 1. Trouver les entreprises dans le rayon
    print("\n🔍 Recherche des prospects...")

    # 2. Récupérer la production PVGIS
    print("\n☀️ Récupération de la production solaire...")
    df_prod = obtenir_production_pvgis(lat, lon, puissance_kw, inclinaison, azimut)
    if df_prod.empty:
        print("✗ Pas de données PVGIS")
        return
    df_prod['heure'] = df_prod['Horodate'].dt.strftime('%m-%d %H')
    prod_max = df_prod['Production_kWh'].max()
    if prod_max == 0:
        prod_max = 1.0

    # 3. Charger toutes les courbes simulées
    conn = get_connection()
    df_toutes = pd.read_sql("""
        SELECT Code_NAF, Horodate, Volume_kWh
        FROM COURBE_TEMPORELLE
        WHERE Est_Simule = 1
    """, conn)
    conn.close()

    df_toutes['Horodate'] = pd.to_datetime(df_toutes['Horodate'], utc=True)
    df_toutes['heure'] = df_toutes['Horodate'].dt.strftime('%m-%d %H')

    # 4. Calculer le score pour chaque NAF
    print("\n☀️ calcul de score...")
    scores = {}
    for naf in df_toutes['Code_NAF'].unique():
        df_naf = df_toutes[df_toutes['Code_NAF'] == naf]
        df_merge = df_naf.merge(df_prod[['heure', 'Production_kWh']], on='heure', how='inner')
        if df_merge.empty:
            scores[naf] = 0.0
            continue
        score_t = df_merge['Volume_kWh'] * (df_merge['Production_kWh'] / prod_max)
        scores[naf] = round(score_t.mean(), 3)
        print(f"✓ {naf} → Score : {scores[naf]}")

    # 5. Assigner le score à chaque acteur
    conn = get_connection()
    acteurs = pd.read_sql("SELECT ID_Acteur, Code_NAF FROM ACTEUR", conn)
    conn.close()

    conn = get_connection()
    cursor = conn.cursor()
    for _, acteur in acteurs.iterrows():
        naf_correspondant = trouver_naf_correspondant(acteur['Code_NAF'])
        score = scores.get(naf_correspondant, 0.0)
        cursor.execute("""
            UPDATE ACTEUR SET Score_Coincidence = ? WHERE ID_Acteur = ?
        """, (score, acteur['ID_Acteur']))
    conn.commit()
    conn.close()

    # 6. Retourner la base ACTEUR classée
    conn = get_connection()
    df = pd.read_sql("""
        SELECT ID_Acteur, Raison_Sociale, Code_NAF, Score_Coincidence,SIRET,Latitude,Longitude
        FROM ACTEUR ORDER BY Score_Coincidence DESC
    """, conn)
    conn.close()

    return df
def afficher_classement_acteurs():
    """
    Affiche les acteurs classés par score de coïncidence décroissant.
    """
    conn = get_connection()
    df = pd.read_sql("""
        SELECT ID_Acteur, Raison_Sociale, Code_NAF, Score_Coincidence,
        FROM ACTEUR
        ORDER BY Score_Coincidence DESC
    """, conn)
    conn.close()

    return df
def afficher_prospection_optimale(lat, lon, rayon_km, puissance_kw, inclinaison, azimut):
    """
    Fonction principale — trouve les meilleurs prospects ACC dans un rayon donné,
    calcule leur score de coïncidence solaire et les classe du meilleur au moins bon.
    """

    # Étape 2 — Trouver les entreprises
    print("\n🔍 Étape 2 — Recherche des prospects...")
    liste_finale_entreprises(lat, lon, rayon_km)

    # Étape 3 — Calculer les scores
    print("\n☀️ Étape 3 — Calcul des scores de coïncidence...")
    calculer_scores_avec_pvgis(lat, lon, rayon_km, puissance_kw, inclinaison, azimut)

    # Étape 4 — Affichage final
    conn = get_connection()

    df = pd.read_sql("""
    SELECT ID_Acteur,
       Raison_Sociale,
       SIRET,
       Code_NAF,
       Latitude,
       Longitude,
       Score_Coincidence
    FROM ACTEUR
    ORDER BY Score_Coincidence DESC
    """, conn)

    conn.close()



    return df


def importer_ville(chemin_csv: str):
    df = pd.read_csv(chemin_csv, sep=';', dtype={'Code_INSEE': str}, encoding='utf-8-sig')
    df.columns = df.columns.str.strip()

    liste_json = json.loads(df.to_json(orient='records', force_ascii=False))

    conn = get_connection()
    cursor = conn.cursor()

    inseres = 0
    ignores = 0

    for commune in liste_json:
        try:
            cursor.execute('''
                INSERT INTO VILLE (Code_INSEE, Ville, Niveau_INSEE)
                VALUES (?, ?, ?)
            ''', (commune['Code_INSEE'], commune['Ville'], commune['Niveau_INSEE']))
            inseres += 1
        except sqlite3.IntegrityError:
            ignores += 1

    conn.commit()
    conn.close()
    print(f"✓ {inseres} communes insérées, {ignores} doublons ignorés")
    return inseres

def obtenir_niveau_insee(code_insee: str)->int:
    """
    Récupère le Niveau de densité INSEE depuis la BDD.
    """
    if not code_insee:
        return None
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT Niveau_INSEE FROM VILLE WHERE Code_INSEE = ?", (str(code_insee),))
    result = cursor.fetchone()
    conn.close()
    
    return result[0] if result else None

# ============================================================
# TEST
# ============================================================
if __name__ == "__main__":
    init_database()
    inserer_liste_dictionnaires([
        {'Nom_Complet': 'Anthony Arnal', 'Email': 'anthony@ibc.fr', 'Role': 'Chef de projet'},
        {'Nom_Operation': 'ACC Nîmes Centre', 'ID_Utilisateur': 1, 'Statut_PMO': 'Etude'},
        {'Raison_Sociale': 'Boulangerie Dupont', 'Type_Acteur': 'Consommateur', 'ID_PMO': 1, 'SIRET': '12345678901234'}
    ])
