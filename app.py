from flask import Flask, request, jsonify
from flask_cors import CORS
import pdfplumber # Utilisé par la logique ChatGPT
import tempfile # Utilisé par la logique ChatGPT
import re
import os # Utilisé par la logique ChatGPT
import requests # Pour /api/get-website-price
from bs4 import BeautifulSoup # Pour /api/get-website-price
from urllib.parse import urljoin # Pour /api/get-website-price

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}}, supports_credentials=True)

@app.route('/')
def home():
    return jsonify({
        "message": "Bienvenue sur le backend K-Albums! (V14-ChatGPT-Parsing)", 
        "status": "en fonctionnement"
    })

@app.route('/api/test')
def api_test():
    return jsonify({"message": "Réponse de test de l'API du backend!"})

# Fonction de parsing basée EXACTEMENT sur ce que tu as fourni de ChatGPT
def parse_invoice_pdf_chatgpt_logic(file_path):
    produits = []
    texte_complet_pour_frais = "" # Pour extraire les frais plus tard
    with pdfplumber.open(file_path) as pdf:
        texte_pour_parsing_produits = ""
        for page in pdf.pages:
            t = page.extract_text()
            if t:
                texte_pour_parsing_produits += t + "\n"
                texte_complet_pour_frais += t + "\n" # Garder aussi le texte complet

    lines = [l.strip() for l in texte_pour_parsing_produits.split('\n') if l.strip()]
    
    i = 0
    # Buffer pour accumuler les lignes de nom de produit qui pourraient s'étendre sur plusieurs lignes
    current_product_name_parts = [] 

    while i < len(lines):
        name_line_candidate = lines[i]

        # Si la ligne ressemble à une ligne de détail "Release...", on essaie de finaliser le produit précédent
        details_match = None
        if name_line_candidate.lower().startswith("release"):
             details_match = re.match(
                r'^Release\s*:\s*(?P<date>\d{4}(?:-\d{2})?(?:-\d{2})?)?\s*(?P<quantity>\d+)\s*\$(?P<unit_price>\d+\.\d+)\s*\$(?P<total_price>\d+\.\d+)$',
                name_line_candidate
            )
        
        if details_match and current_product_name_parts: # On a un nom dans le buffer et des détails sur cette ligne
            name = " ".join(current_product_name_parts).strip()
            # Vérifier si le nom n'est pas un en-tête de tableau
            if re.match(r"^\s*Product\s+Quantity\s+Price\s+Total\s*$", name, re.IGNORECASE):
                print(f"DEBUG (V14): Nom '{name}' ignoré (header) avant Release ligne '{name_line_candidate}'")
                current_product_name_parts = [] # Vider le buffer
                i += 1
                continue

            date = details_match.group("date") or "N/A"
            quantity = int(details_match.group("quantity"))
            unit_price = float(details_match.group("unit_price"))
            produits.append({"name": name, "quantity": quantity, "unit_price_usd": unit_price, "release_date": date})
            print(f"  ==> PRODUIT (V14 ChatGPT-Style Cas A): {name} (Q:{quantity})")
            current_product_name_parts = [] # Vider le buffer après avoir trouvé un produit
            i += 1
            continue

        # Cas accessoire sur 2 lignes (Nom, puis "Release :", puis "Size: ... Q P T")
        # On regarde si la ligne actuelle est "Release :", et la suivante est "Size/Ver..."
        if name_line_candidate.lower().startswith("release :") and product_name_buffer and i + 1 < len(lines):
            size_line_candidate = lines[i+1]
            size_match_re = re.compile(r'^(?:Size|Ver|Version|Type)\s*:\s*(?P<variation>.+?)(?P<quantity>\d+)\s*\$(?P<unit_price>\d+\.\d+)\s*\$(?P<total_price>\d+\.\d+)$', re.IGNORECASE)
            size_details_match = size_match_re.match(size_line_candidate)

            if size_details_match:
                name = " ".join(product_name_buffer).strip() # Nom était dans le buffer
                # Vérifier si le nom n'est pas un en-tête
                if re.match(r"^\s*Product\s+Quantity\s+Price\s+Total\s*$", name, re.IGNORECASE):
                    print(f"DEBUG (V14): Nom '{name}' ignoré (header) avant Release+Size")
                    product_name_buffer = []
                    # La ligne "Release :" est consommée, on avance pour la ligne Size
                    i += 1 
                    continue 

                variation = size_details_match.group("variation").strip()
                quantity = int(size_details_match.group("quantity"))
                unit_price = float(size_details_match.group("unit_price"))
                
                date_on_release_line_match = re.match(r"Release\s*:\s*(\d{4}-\d{2}-\d{2})?", name_line_candidate)
                date = date_on_release_line_match.group(1) if date_on_release_line_match and date_on_release_line_match.group(1) else "N/A"

                produits.append({"name": f"{name} ({variation})", "quantity": quantity, "unit_price_usd": unit_price, "release_date": date})
                print(f"  ==> PRODUIT (V14 ChatGPT-Style Cas B - Size/Ver): {name} ({variation}) (Q:{quantity})")
                product_name_buffer = []
                i += 2 # On a traité la ligne "Release :" et la ligne "Size..."
                continue
        
        # Si la ligne n'est pas un en-tête et ne commence pas par "Release :" (car ces cas sont gérés),
        # ou si c'est une ligne "Release :" qui n'a pas abouti à un produit, on l'ajoute au buffer de nom.
        # On évite de bufferiser les lignes qui sont clairement des en-têtes.
        if not re.match(r"^\s*Product\s+Quantity\s+Price\s+Total\s*$", line_content, re.IGNORECASE) and \
           not line_content.lower().startswith("subtotal") and \
           not line_content.lower().startswith("shipping") and \
           not line_content.lower().startswith("bank transfer fee") and \
           not line_content.lower().startswith("total"):
            current_product_name_parts.append(line_content)
        
        i += 1
        
    return produits, texte_complet_pour_frais


@app.route("/api/upload-invoice", methods=["POST"])
def upload_invoice():
    if "invoice_pdf" not in request.files:
        return jsonify({"error": "No PDF uploaded"}), 400
    pdf_file = request.files["invoice_pdf"]
    
    # Utiliser un fichier temporaire pour pdfplumber
    temp_file_descriptor, temp_file_path = tempfile.mkstemp(suffix=".pdf")
    try:
        pdf_file.save(temp_file_path)
        # Appeler la fonction de parsing qui retourne aussi le full_text
        produits, full_text_for_fees = parse_invoice_pdf_chatgpt_logic(temp_file_path)
    finally:
        os.close(temp_file_descriptor) # Important de fermer le descripteur
        os.remove(temp_file_path) # Supprimer le fichier temporaire

    # Extraire les frais d'envoi et bancaires du texte complet
    shipping_cost = None
    bank_fee = None
    if full_text_for_fees: # S'assurer que le texte n'est pas vide
        shipping_match = re.search(r"Shipping\s*\$?\s*(\d+\.?\d*)", full_text_for_fees, re.IGNORECASE)
        if shipping_match:
            shipping_cost = shipping_match.group(1)
        bank_fee_match = re.search(r"Bank transfer fee\s*\$?\s*(\d+\.?\d*)", full_text_for_fees, re.IGNORECASE)
        if bank_fee_match:
            bank_fee = bank_fee_match.group(1)
    
    print(f"DEBUG_PDF_PARSE (V14): {len(produits)} produits trouvés par la logique ChatGPT modifiée.")
    print(f"DEBUG_PDF_PARSE (V14): Frais port: {shipping_cost}, Frais banque: {bank_fee}")

    return jsonify({
        "message": "Extraction produits (V14 avec logique ChatGPT modifiée), FDP et frais bancaires.",
        "filename": pdf_file.filename,
        "shipping_cost_usd": shipping_cost,
        "bank_transfer_fee_usd": bank_fee,
        "parsed_products": produits,
        "DEVELOPMENT_full_text_for_debug": full_text_for_fees 
    })

# ... (Le reste du code, y compris /api/get-website-price, _build_cors_preflight_response, 
#      _make_json_response, et if __name__ == '__main__': reste identique à la V13-BackendFusion)

@app.route('/api/get-website-price', methods=['POST', 'OPTIONS'])
def get_website_price():
    if request.method == 'OPTIONS':
        return _build_cors_preflight_response()

    data = request.get_json()
    product_name_from_invoice = data.get('productName')
    product_url_on_website = data.get('productUrl') 

    print(f"DEBUG /api/get-website-price: Reçu productName='{product_name_from_invoice}', productUrl='{product_url_on_website}'")

    if not product_url_on_website and not product_name_from_invoice: 
        return _make_json_response({"error": "Nom du produit ou URL du produit manquant."}, 400)

    price_str = None; debug_messages = []; target_url = None 
    if product_url_on_website:
        target_url = product_url_on_website
        debug_messages.append(f"Utilisation de l'URL fournie: {target_url}")
    elif product_name_from_invoice:
        if "blackpink" in product_name_from_invoice.lower() and "the album" in product_name_from_invoice.lower(): # Cas test
            target_url = "https://www.kalbums.com/product-page/the-album-1st-full-album"
            debug_messages.append(f"URL de test spécifique utilisée pour '{product_name_from_invoice}': {target_url}")
        else: 
            search_terms = product_name_from_invoice
            search_terms = re.sub(r"\[.*?POB.*?\]", "", search_terms, flags=re.IGNORECASE).strip()
            search_terms = re.sub(r"\(.*Ver\.\)", "", search_terms, flags=re.IGNORECASE).strip()
            search_terms = re.sub(r"\(Random\)", "", search_terms, flags=re.IGNORECASE).strip()
            search_terms = re.sub(r"\(Set\)", "", search_terms, flags=re.IGNORECASE).strip()
            search_terms = re.sub(r"Mini Album", "", search_terms, flags=re.IGNORECASE).strip()
            search_terms = re.sub(r"Full Album", "", search_terms, flags=re.IGNORECASE).strip()
            search_terms = re.sub(r"EP ALBUM", "", search_terms, flags=re.IGNORECASE).strip()
            search_terms = re.sub(r"[\[\]()]", "", search_terms).strip()
            search_terms = re.sub(r"['‘’]", "", search_terms).strip() 
            search_terms = re.sub(r"[^\w\s\-\樂\-\合]", "", search_terms, flags=re.UNICODE).strip()
            search_terms = re.sub(r"\s+", "+", search_terms.strip())
            
            if not search_terms:
                 debug_messages.append(f"Nom produit '{product_name_from_invoice}' trop générique après nettoyage.")
                 return _make_json_response({"product_name_searched": product_name_from_invoice, "url_attempted": "N/A", "price_eur_ht": None, "error_message": "Nom produit trop générique pour recherche.", "debug_messages": debug_messages })
            
            search_url = f"https://www.kalbums.com/search?q={search_terms}"
            debug_messages.append(f"Construction URL de recherche: {search_url}")
            try:
                headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
                search_response = requests.get(search_url, headers=headers, timeout=15)
                search_response.raise_for_status()
                search_soup = BeautifulSoup(search_response.content, 'html.parser')
                debug_messages.append(f"Page recherche {search_url} OK. Statut: {search_response.status_code}")
                
                product_link_element = search_soup.find('a', attrs={'data-hook': 'item-title'})
                if product_link_element and product_link_element.has_attr('href'):
                    product_page_url = product_link_element['href']
                    if not product_page_url.startswith('http'):
                        product_page_url = urljoin(search_url, product_page_url)
                    target_url = product_page_url
                    debug_messages.append(f"Premier lien produit trouvé: {target_url}")
                else:
                    debug_messages.append(f"Aucun lien (data-hook='item-title') sur page recherche.")
                    return _make_json_response({"product_name_searched": product_name_from_invoice, "url_attempted": search_url, "price_eur_ht": None, "error_message": "Aucun produit trouvé via recherche.", "debug_messages": debug_messages })
            except Exception as e_search:
                debug_messages.append(f"Erreur requête/analyse recherche {search_url}: {str(e_search)}")
                return _make_json_response({"error": f"Erreur com/analyse recherche: {str(e_search)}", "price_eur_ht": None, "debug_messages": debug_messages}, 500)

    if not target_url:
        return _make_json_response({"error": "Impossible de déterminer l'URL à scraper.", "price_eur_ht": None, "debug_messages": debug_messages}, 400)

    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        response = requests.get(target_url, headers=headers, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        debug_messages.append(f"Page produit {target_url} OK. Statut: {response.status_code}.")
        price_element = soup.find('span', attrs={'data-hook': 'formatted-primary-price'})
        
        if price_element:
            price_text = price_element.get_text(strip=True) 
            debug_messages.append(f"Élément prix trouvé: '{price_text}'")
            price_numeric_str = price_text.replace('€', '').replace(',', '.').strip()
            try:
                price_float = float(price_numeric_str)
                price_str = f"{price_float:.2f}"
            except ValueError: price_str = price_numeric_str 
        else:
            debug_messages.append("Élément prix (data-hook='formatted-primary-price') non trouvé.")
    except Exception as e:
        debug_messages.append(f"Erreur scraping page produit {target_url}: {str(e)}")
    
    return _make_json_response({
        "product_name_searched": product_name_from_invoice,
        "url_attempted": target_url,
        "price_eur_ht": price_str, 
        "debug_messages": debug_messages
    })

def _build_cors_preflight_response():
    response = jsonify({}) 
    response.headers.add("Access-Control-Allow-Origin", "*")
    response.headers.add("Access-Control-Allow-Headers", "Content-Type,Authorization")
    response.headers.add("Access-Control-Allow-Methods", "GET,PUT,POST,DELETE,OPTIONS")
    return response

def _make_json_response(data, status_code=200):
    response = jsonify(data)
    return response, status_code

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=8080, debug=True)
