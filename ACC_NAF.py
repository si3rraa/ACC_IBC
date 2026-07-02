def code_naf(siret):
    try:
        reponse = requests.get(
            "https://recherche-entreprises.api.gouv.fr/search",
            params={'q': siret, 'per_page': 1},
            timeout=10
        )
        if reponse.status_code == 200:
            resultats = reponse.json().get('results', [])
            if resultats:
                naf = resultats[0].get('activite_principale', None)
                print(f"Code NAF pour {siret} : {naf}")
                return naf
        print(f"Aucun résultat pour {siret}")
        return None
    except:
        print("Erreur lors de la requête")
        return None