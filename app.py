from flask import Flask, jsonify, request
from flask_cors import CORS
from PyPDF2 import PdfReader
import io
import re
import requests # Pour /api/get-website-price
from bs4 import BeautifulSoup # Pour /api/get-website-price
from urllib.parse import urljoin # Pour /api/get-website-price

app = Flask(__name__)
# Configuration CORS plus robuste pour gérer les preflight OPTIONS
CORS(app, resources={r"/api/*": {"origins": "*"}}, supports_credentials=True)

@app.route('/')
def home():
    return jsonify({
        "message": "Bienvenue sur le backend K-Albums! (V12-BackendComplet)", 
        "status": "en fonctionnement",
        "info": "Ceci est un service hébergé sur Render."
    })

@app.route('/api/test')
def api_test():
    return jsonify({"message": "Réponse de test de l'API du backend!"})

@app.route('/api/upload-invoice', methods=['POST'])
def upload_invoice():
    if 'invoice_pdf' not in request.files:
        return jsonify({"error": "Aucun fichier PDF trouvé"}), 400
    file = request.files['invoice_pdf']
    if file.filename == '':
        return jsonify({"error": "Aucun fichier sélectionné"}), 400

    try:
        print(f"--- Traitement PDF : {file.filename} (Backend V12 avec parsing ChatGPT) ---")
        file_content_in_memory = io.BytesIO(file.read())
        reader = PdfReader(file_content_in_memory)
        full_text = "".join([page.extract_text() + "\n" for page in reader.pages if page.extract_text()])
        
        if not full_text.strip():
            print("Avertissement: Texte PDF vide ou non extractible.")
            full_text = "[Extraction texte PDF échouée]"
        print("--- TEXTE PDF (V12 début) ---"); print(full_text[:2000]); print("--- FIN TEXTE (Snippet) ---")

        lines = [l.strip() for l in full_text.split('\n') if l.strip()]
        parsed_products = []
        shipping_cost = None
        bank_fee = None

        # Logique de parsing PDF (basée sur celle que tu as fournie de ChatGPT)
        i = 0
        product_name_buffer = [] # Ajout d'un buffer pour les noms sur plusieurs lignes

        while i < len(lines):
            line_content = lines[i]

            # Ignorer les en-têtes de tableau
            if re.match(r"^\s*Product\s+Quantity\s+Price\s+Total\s*$", line_content, re.IGNORECASE):
                if product_name_buffer: # Si un nom était en cours, il est perdu
                    print(f"DEBUG_PDF_PARSE (V12): Buffer nom '{' '.join(product_name_buffer)}' vidé par header.")
                product_name_buffer = []
                i += 1
                continue

            # Détection de la fin de la section des produits (peut être affinée)
            if line_content.lower().startswith("subtotal"):
                if product_name_buffer:
                    print(f"DEBUG_PDF_PARSE (V12): Buffer nom final non traité: '{' '.join(product_name_buffer)}'")
                break # Sortir de la boucle principale

            # REGEX principale pour la ligne de détails (Release + Q P T)
            details_match = None
            if i + 1 < len(lines): # S'il y a une ligne suivante pour les détails
                details_line_candidate = lines[i+1]
                details_match = re.match(
                    r'^Release\s*:\s*(?P<date>\d{4}(?:-\d{2})?(?:-\d{2})?)?\s*(?P<quantity>\d+)\s*\$(?P<unit_price>\d+\.\d+)\s*\$(?P<total_price>\d+\.\d+)$',
                    details_line_candidate
                )
            
            # REGEX pour la ligne de nom qui contient AUSSI les détails (tout sur une ligne)
            name_and_details_match = re.match(
                 r'^(?P<name_on_line>.+?)\s*Release\s*:\s*(?P<date>\d{4}(?:-\d{2})?(?:-\d{2})?)?\s*(?P<quantity>\d+)\s*\$(?P<unit_price>\d+\.\d+)\s*\$(?P<total_price>\d+\.\d+)$',
                 line_content
            )

            # Cas 1: Nom sur ligne(s) précédente(s), détails sur la ligne suivante
            if details_match and product_name_buffer:
                name = " ".join(product_name_buffer).strip()
                date = details_match.group("date") or "N/A"
                quantity = int(details_match.group("quantity"))
                unit_price = float(details_match.group("unit_price"))
                parsed_products.append({"name": name, "quantity": quantity, "unit_price_usd": unit_price, "release_date": date})
                print(f"  ==> PRODUIT (V12 Cas 1): {name} (Q:{quantity} P:${unit_price} D:{date})")
                product_name_buffer = [] # Vider le buffer
                i += 2 # On a consommé la ligne de nom et la ligne de détails
                continue
            
            # Cas 1b: Nom et détails sur la MÊME ligne
            elif name_and_details_match:
                name = name_and_details_match.group("name_on_line").strip()
                 # Si le buffer n'est pas vide, cela signifie que ce "nom sur ligne" est en fait une continuation.
                if product_name_buffer:
                    name = " ".join(product_name_buffer).strip() + " " + name
                
                date = name_and_details_match.group("date") or "N/A"
                quantity = int(name_and_details_match.group("quantity"))
                unit_price = float(name_and_details_match.group("unit_price"))
                parsed_products.append({"name": name.strip(), "quantity": quantity, "unit_price_usd": unit_price, "release_date": date})
                print(f"  ==> PRODUIT (V12 Cas 1b): {name.strip()} (Q:{quantity} P:${unit_price} D:{date})")
                product_name_buffer = [] # Vider le buffer
                i += 1 # On a consommé cette ligne
                continue

            # Cas 2: Nom, puis ligne "Release :", puis ligne "Size: ... Q P T" (POPCONE, etc.)
            elif line_content.lower().startswith("release :") and i + 1 < len(lines):
                # line_content est "Release : [date/vide]"
                # lines[i+1] est la ligne suivante qui pourrait être "Size:..."
                size_line_candidate = lines[i+1] # C'est lines[i+1] du point de vue de la ligne "Release :"
                
                size_match_re = re.compile(r'^(?:Size|Ver|Version|Type)\s*:\s*(?P<variation>.+?)(?P<quantity>\d+)\s*\$(?P<unit_price>\d+\.\d+)\s*\$(?P<total_price>\d+\.\d+)$', re.IGNORECASE)
                size_details_match = size_match_re.match(size_line_candidate)

                if size_details_match and product_name_buffer:
                    name = " ".join(product_name_buffer).strip()
                    variation = size_details_match.group("variation").strip()
                    quantity = int(size_details_match.group("quantity"))
                    unit_price = float(size_details_match.group("unit_price"))
                    
                    # Essayer de prendre la date de la ligne "Release :"
                    date_on_release_line_match = re.match(r"Release\s*:\s*(\d{4}-\d{2}-\d{2})?", line_content)
                    date = date_on_release_line_match.group(1) if date_on_release_line_match and date_on_release_line_match.group(1) else "N/A"

                    parsed_products.append({"name": f"{name} ({variation})", "quantity": quantity, "unit_price_usd": unit_price, "release_date": date})
                    print(f"  ==> PRODUIT (V12 Cas 2): {name} ({variation}) (Q:{quantity} P:${unit_price} D:{date})")
                    product_name_buffer = []
                    i += 2 # On a consommé la ligne "Release :" et la ligne "Size:..."
                    continue
                else: # La ligne "Release :" n'est pas suivie d'une ligne "Size..." valide
                    if line_content: product_name_buffer.append(line_content) # On la garde dans le buffer nom
                    i += 1
                    continue
            
            # Si aucun des cas ci-dessus, c'est une ligne de nom de produit
            if line_content:
                product_name_buffer.append(line_content)
            
            i += 1

        # Frais d'envoi et bancaires
        shipping_match = re.search(r"Shipping\s*\$?\s*(\d+\.?\d*)", full_text, re.IGNORECASE)
        if shipping_match: shipping_cost = shipping_match.group(1)
        bank_fee_match = re.search(r"Bank transfer fee\s*\$?\s*(\d+\.?\d*)", full_text, re.IGNORECASE)
        if bank_fee_match: bank_fee = bank_fee_match.group(1)

        print(f"{len(parsed_products)} produits parsés au total (V12).")
        return jsonify({
            "message": "Extraction produits (V12 avec logique ChatGPT modifiée), FDP et frais bancaires.",
            "filename": file.filename,
            "shipping_cost_usd": shipping_cost,
            "bank_transfer_fee_usd": bank_fee,
            "parsed_products": parsed_products,
            "DEVELOPMENT_full_text_for_debug": full_text
        })

    except Exception as e:
        import traceback
        print("--- ERREUR BACKEND PDF PARSING ---")
        traceback.print_exc()
        print("--- FIN ERREUR BACKEND ---")
        return jsonify({"error": f"Erreur interne majeure PDF: {str(e)}"}), 500

    return jsonify({"error": "Problème fichier non traité."}), 500

@app.route('/api/get-website-price', methods=['POST', 'OPTIONS']) # Ajout de OPTIONS
def get_website_price():
    if request.method == 'OPTIONS': # Gérer la requête preflight CORS
        return _build_cors_preflight_response()

    data = request.get_json()
    product_name_from_invoice = data.get('productName')
    product_url_on_website = data.get('productUrl') 

    print(f"DEBUG /api/get-website-price: Reçu productName='{product_name_from_invoice}', productUrl='{product_url_on_website}'")

    if not product_url_on_website and not product_name_from_invoice: 
        return jsonify({"error": "Nom du produit ou URL du produit manquant."}), 400

    price_str = None; debug_messages = []; target_url = None 
    if product_url_on_website:
        target_url = product_url_on_website
        debug_messages.append(f"Utilisation de l'URL fournie: {target_url}")
    elif product_name_from_invoice:
        if "blackpink" in product_name_from_invoice.lower() and "the album" in product_name_from_invoice.lower(): # Cas test
            target_url = "https://www.kalbums.com/product-page/the-album-1st-full-album"
            debug_messages.append(f"URL de test spécifique utilisée pour '{product_name_from_invoice}': {target_url}")
        else: # Tentative de recherche générique
            search_terms = product_name_from_invoice
            # Nettoyage des termes de recherche
            search_terms = re.sub(r"\[.*?POB.*?\]", "", search_terms, flags=re.IGNORECASE).strip()
            search_terms = re.sub(r"\(PHOTOCARD\)", "", search_terms, flags=re.IGNORECASE).strip()
            search_terms = re.sub(r"\(LIMITED\s*VER\.?\)", "", search_terms, flags=re.IGNORECASE).strip()
            search_terms = re.sub(r"\((?:(?:[A-Z0-9\s]+)?VER\.?|RANDOM|SET|JEWEL\s*CASE|DIGIPACK|PHOTOBOOK|ACCORDION|POSTCARD|PLATFORM ALBUM_NEMO|YG TAG ALBUMS|WEVERSE ALBUMS)\)", "", search_terms, flags=re.IGNORECASE).strip()
            search_terms = re.sub(r"MINI ALBUM|FULL ALBUM|THE ALBUM|ALBUM|EP ALBUM|SINGLE ALBUM|SPECIAL SINGLE", "", search_terms, flags=re.IGNORECASE).strip()
            search_terms = re.sub(r"[\[\]()']", "", search_terms).strip()
            search_terms = re.sub(r"[^\w\s\-\樂\-\合]", "", search_terms, flags=re.UNICODE).strip() # Garder certains caractères spéciaux si besoin
            search_terms = re.sub(r"\s+", "+", search_terms.strip())
            
            if not search_terms:
                 debug_messages.append(f"Nom produit '{product_name_from_invoice}' trop générique après nettoyage.")
                 return _make_json_response({"product_name_searched": product_name_from_invoice, "url_attempted": "N/A", "price_eur_ht": None, "error_message": "Nom produit trop générique pour recherche.", "debug_messages": debug_messages }), 200
            
            search_url = f"https://www.kalbums.com/search?q={search_terms}"
            debug_messages.append(f"Construction URL de recherche: {search_url}")
            try:
                headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
                search_response = requests.get(search_url, headers=headers, timeout=15)
                search_response.raise_for_status()
                search_soup = BeautifulSoup(search_response.content, 'html.parser')
                debug_messages.append(f"Page recherche {search_url} OK. Statut: {search_response.status_code}")
                
                product_link_elements = search_soup.find_all('a', attrs={'data-hook': 'item-title'}) # Trouver tous les liens
                if not product_link_elements:
                    debug_messages.append(f"Aucun lien produit (data-hook='item-title') sur page recherche pour '{search_terms}'.")
                    return _make_json_response({"product_name_searched": product_name_from_invoice, "url_attempted": search_url, "price_eur_ht": None, "error_message": "Aucun produit correspondant trouvé via recherche.", "debug_messages": debug_messages }), 200

                # Logique de sélection du meilleur lien (pour l'instant, on prend le premier, à affiner)
                # Idéalement, ici on comparerait les titres des liens avec product_name_from_invoice
                product_page_url = product_link_elements[0]['href']
                if not product_page_url.startswith('http'):
                    product_page_url = urljoin(search_url, product_page_url)
                target_url = product_page_url
                debug_messages.append(f"Premier lien produit trouvé sur page recherche: {target_url}")
            
            except requests.exceptions.RequestException as e_search:
                debug_messages.append(f"Erreur requête vers page recherche {search_url}: {str(e_search)}")
                return _make_json_response({"error": f"Erreur com. recherche: {str(e_search)}", "price_eur_ht": None, "debug_messages": debug_messages}), 500
            except Exception as e_search_parse:
                debug_messages.append(f"Erreur analyse page recherche: {str(e_search_parse)}")
                return _make_json_response({"error": f"Erreur analyse recherche: {str(e_search_parse)}", "price_eur_ht": None, "debug_messages": debug_messages}), 500

    if not target_url:
        return _make_json_response({"error": "Impossible de déterminer l'URL à scraper.", "price_eur_ht": None, "debug_messages": debug_messages}), 400

    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        response = requests.get(target_url, headers=headers, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        debug_messages.append(f"Page produit {target_url} OK. Statut: {response.status_code}.")
        price_element = soup.find('span', attrs={'data-hook': 'formatted-primary-price'})
        
        if price_element:
            price_text = price_element.get_text(strip=True) 
            debug_messages.append(f"Élément prix trouvé. Texte brut: '{price_text}'")
            price_numeric_str = price_text.replace('€', '').replace(',', '.').strip()
            try:
                price_float = float(price_numeric_str)
                price_str = f"{price_float:.2f}"
                debug_messages.append(f"Prix converti en float: {price_float}, formaté: {price_str}")
            except ValueError:
                debug_messages.append(f"AVERTISSEMENT: Impossible de convertir '{price_numeric_str}' en float.")
                price_str = price_numeric_str 
        else:
            debug_messages.append("Élément prix (data-hook='formatted-primary-price') non trouvé sur page produit.")
    except Exception as e:
        debug_messages.append(f"Erreur scraping page produit {target_url}: {str(e)}")
    
    return _make_json_response({
        "product_name_searched": product_name_from_invoice,
        "url_attempted": target_url,
        "price_eur_ht": price_str, 
        "debug_messages": debug_messages
    })

def _build_cors_preflight_response():
    response = jsonify({"status": "success"}) # Ou make_response()
    response.headers.add("Access-Control-Allow-Origin", "*")
    response.headers.add("Access-Control-Allow-Headers", "Content-Type,Authorization")
    response.headers.add("Access-Control-Allow-Methods", "GET,PUT,POST,DELETE,OPTIONS")
    response.headers.add("Access-Control-Allow-Credentials", "true")
    return response

def _make_json_response(data, status_code=200):
    response = jsonify(data)
    # Les en-têtes CORS sont gérés globalement par CORS(app) ou par la réponse preflight
    return response, status_code


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True)
