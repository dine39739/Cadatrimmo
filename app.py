
import streamlit as st
import pandas as pd
import pdfplumber
from bs4 import BeautifulSoup
import re
import io

# ==============================================================================
# FONCTIONS DE PARSING (MOTEUR BACKEND)
# ==============================================================================

def parse_pdf(file_stream, sections_filtre, plans_filtre):
    """
    Analyse un fichier PDF pour extraire les données cadastrales.
    La logique est basée sur la lecture séquentielle du texte et la détection
    de mots-clés et de motifs (Regex) pour identifier les propriétaires,
    adresses et lots.

    Args:
        file_stream: Le flux binaire du fichier PDF uploadé.
        sections_filtre (list): Liste des sections à traiter.
        plans_filtre (list): Liste des numéros de plan à traiter.

    Returns:
        pd.DataFrame: Un DataFrame contenant les données extraites.
    """
    data = []
    
    with pdfplumber.open(file_stream) as pdf:
        current_section = None
        current_plan = None
        current_proprietaire = []
        current_adresse = ""
        is_in_relevant_parcel = False

        for page in pdf.pages:
            text = page.extract_text()
            if not text:
                continue
            
            lines = text.split('\n')
            
            for line in lines:
                # Regex pour détecter l'en-tête de section/plan.
                # Exemple de ligne : "Section : AC  Plan : 124"
                header_match = re.search(r"Section\s*:\s*(\w+)\s*Plan\s*:\s*(\d+)", line, re.IGNORECASE)
                if header_match:
                    current_section = header_match.group(1).strip().upper()
                    current_plan = header_match.group(2).strip()
                    
                    # Vérifie si la parcelle correspond aux filtres de l'utilisateur
                    is_in_relevant_parcel = (current_section in sections_filtre and current_plan in plans_filtre)
                    
                    # Réinitialise les informations du propriétaire pour la nouvelle parcelle
                    current_proprietaire = []
                    current_adresse = ""
                    continue

                if is_in_relevant_parcel:
                    # Regex pour les lots et tantièmes.
                    # Cherche une ligne contenant "Lot" et une fraction (ex: 123 / 10000)
                    lot_match = re.search(r"Lot\s+(\d+)", line, re.IGNORECASE)
                    tantiemes_match = re.search(r"(\d+\s*/\s*\d+)", line)
                    
                    if lot_match and tantiemes_match:
                        lot_num = lot_match.group(1)
                        tantiemes = tantiemes_match.group(1).replace(" ", "")
                        
                        # Si un lot est trouvé, on l'associe au dernier propriétaire identifié
                        if current_proprietaire:
                            data.append({
                                "Section": current_section,
                                "Plan": current_plan,
                                "N° Lot": lot_num,
                                "Tantièmes": tantiemes,
                                "Propriétaires": "\n".join(current_proprietaire),
                                "Adresse Postale Propriétaire": current_adresse.strip()
                            })
                    # Heuristique pour identifier un nom de propriétaire :
                    # - Ligne en majuscules
                    # - Contient au moins une lettre
                    # - Ne ressemble pas à une ligne de lot/tantième
                    elif re.match(r"^[A-Z\s/.'-]{5,}$", line.strip()) and not lot_match and not tantiemes_match and "LOT" not in line.upper():
                        # Si on trouve un nouveau nom, c'est un nouveau bloc propriétaire.
                        # On réinitialise l'adresse.
                        if current_adresse:
                            current_proprietaire = []
                            current_adresse = ""
                        current_proprietaire.append(line.strip())
                    
                    # Heuristique pour l'adresse :
                    # - Suit immédiatement un nom de propriétaire
                    # - Contient souvent un code postal (5 chiffres) ou un nom de rue.
                    elif current_proprietaire and not current_adresse:
                        # On suppose que les lignes suivant le nom sont l'adresse,
                        # jusqu'à ce qu'on trouve une ligne vide ou un nouveau motif (lot/propriétaire).
                        # Une ligne d'adresse est souvent alphanumérique.
                        if re.search(r"\d", line) and re.search(r"[a-zA-Z]", line):
                             current_adresse += line.strip() + "\n"

    return pd.DataFrame(data)


def parse_html(file_stream, sections_filtre, plans_filtre):
    """
    Analyse un fichier HTML. Cette fonction est un squelette et doit être
    adaptée à la structure EXACTE de votre fichier HTML. Les commentaires
    ci-dessous expliquent comment procéder.

    Args:
        file_stream: Le flux du fichier HTML uploadé.
        sections_filtre (list): Liste des sections à traiter.
        plans_filtre (list): Liste des numéros de plan à traiter.

    Returns:
        pd.DataFrame: Un DataFrame contenant les données extraites.
    """
    # NOTE POUR L'UTILISATEUR : Le parsing HTML dépend énormément de la structure
    # des balises (div, span, table, etc.). Vous devrez inspecter votre fichier HTML
    # (clic droit -> "Inspecter l'élément" dans votre navigateur) pour trouver
    # les bons sélecteurs.
    
    # Exemple de structure supposée :
    # <div class="parcelle">
    #   <h2>Section AC Plan 124</h2>
    #   <div class="proprietaire">
    #     <span class="nom">DUPONT Jean</span>
    #     <span class="adresse">1 RUE DE LA PAIX 75001 PARIS</span>
    #   </div>
    #   <table>
    #     <tr><td>Lot 1</td><td>123 / 10000</td></tr>
    #   </table>
    # </div>

    data = []
    soup = BeautifulSoup(file_stream, 'html.parser')

    # Remplacez 'div.parcelle' par le sélecteur CSS qui englobe une parcelle complète.
    parcelles = soup.select('div.parcelle')
    if not parcelles:
        # Si le sélecteur ci-dessus ne marche pas, on peut essayer une recherche plus générique.
        # Ici, on cherche tous les `<b>` qui pourraient contenir les infos de parcelle.
        parcelles_headers = soup.find_all('b', string=re.compile(r'Section', re.IGNORECASE))
        # Cette partie est à développer en fonction de la structure réelle du fichier.
        # Pour cet exemple, nous retournons un DataFrame vide pour le HTML.
        st.warning("Le parsing HTML n'est pas encore implémenté pour ce format de fichier. Veuillez adapter le code dans `app.py`.")
        return pd.DataFrame()

    for parcelle in parcelles:
        header = parcelle.select_one('h2').text # Adaptez ce sélecteur
        header_match = re.search(r"Section\s*(\w+)\s*Plan\s*(\d+)", header, re.IGNORECASE)
        
        if header_match:
            section, plan = header_match.group(1).upper(), header_match.group(2)
            if section in sections_filtre and plan in plans_filtre:
                # Adaptez les sélecteurs suivants pour extraire les données.
                nom = parcelle.select_one('.nom').text
                adresse = parcelle.select_one('.adresse').text
                
                lignes_lots = parcelle.select('tr') # Supposons que les lots sont dans un tableau
                for ligne in lignes_lots:
                    colonnes = ligne.select('td')
                    if len(colonnes) == 2:
                        lot_text = colonnes[0].text
                        tantiemes = colonnes[1].text
                        lot_num = re.search(r"Lot\s*(\d+)", lot_text).group(1)
                        
                        data.append({
                            "Section": section,
                            "Plan": plan,
                            "N° Lot": lot_num,
                            "Tantièmes": tantiemes.strip(),
                            "Propriétaires": nom,
                            "Adresse Postale Propriétaire": adresse
                        })
                        
    return pd.DataFrame(data)

def to_excel(df):
    """Convertit un DataFrame en un fichier Excel en mémoire."""
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Extraction Cadastrale')
    processed_data = output.getvalue()
    return processed_data

# ==============================================================================
# INTERFACE UTILISATEUR (STREAMLIT)
# ==============================================================================

st.set_page_config(page_title="Extracteur Cadastral", layout="wide")

st.title("Extracteur de Données Cadastrales")
st.write("Transformez vos relevés cadastraux PDF ou HTML en fichier Excel exploitable.")

# --- BARRE LATERALE POUR LES PARAMETRES ---
with st.sidebar:
    st.header("1. Paramètres d'Analyse")
    
    sections_input = st.text_input("Section(s) (ex: AC, BD)", "AC")
    plans_input = st.text_input("Numéro(s) de Plan (ex: 124, 125)", "124")
    
    st.info("Séparez plusieurs valeurs par une virgule.")

# --- ZONE PRINCIPALE POUR L'UPLOAD ET LES RESULTATS ---
st.header("2. Chargez votre relevé cadastral")
uploaded_file = st.file_uploader(
    "Glissez-déposez un fichier (.pdf ou .html)",
    type=['pdf', 'html']
)

st.header("3. Lancez l'analyse")
start_analysis = st.button("Lancer l'analyse", disabled=(uploaded_file is None))

if start_analysis:
    if not sections_input or not plans_input:
        st.error("Veuillez renseigner les sections et les numéros de plan dans la barre latérale.")
    else:
        # Nettoyage des inputs utilisateur
        sections_filtre = [s.strip().upper() for s in sections_input.split(',')]
        plans_filtre = [p.strip() for p in plans_input.split(',')]
        
        with st.spinner("Analyse du document en cours..."):
            try:
                file_extension = uploaded_file.name.split('.')[-1].lower()
                
                if file_extension == 'pdf':
                    df_results = parse_pdf(uploaded_file, sections_filtre, plans_filtre)
                elif file_extension == 'html':
                    df_results = parse_html(uploaded_file, sections_filtre, plans_filtre)
                else:
                    st.error("Format de fichier non supporté.")
                    df_results = pd.DataFrame()

                if not df_results.empty:
                    st.success(f"{len(df_results)} lot(s) trouvé(s) !")
                    st.dataframe(df_results)
                    
                    # Bouton de téléchargement
                    excel_data = to_excel(df_results)
                    st.download_button(
                        label="📥 Télécharger le fichier Excel",
                        data=excel_data,
                        file_name=f"extraction_cadastrale_{sections_input}_{plans_input}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    )
                else:
                    st.warning("Aucune donnée correspondante n'a été trouvée avec les filtres fournis. Vérifiez vos entrées ou le contenu du fichier.")

            except Exception as e:
                st.error(f"Une erreur est survenue lors de l'analyse : {e}")
                st.error("Le format du document n'est peut-être pas compatible avec le parseur actuel. Le code peut nécessiter un ajustement pour ce fichier spécifique.")

else:
    st.info("Veuillez charger un fichier et cliquer sur 'Lancer l'analyse'.")
