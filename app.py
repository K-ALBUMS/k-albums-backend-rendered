from flask import Flask, request, jsonify
from flask_cors import CORS
import pdfplumber # Remplacement de PyPDF2
import tempfile
import re
import os
import requests # Pour /api/get-website-price
from bs4 import BeautifulSoup # Pour /api/get-website-price
from urllib.parse import urljoin # Pour /api/get-website-price

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}}, supports_credentials=True)

@app.route('/')
def home():
    return jsonify({
        "message": "Bienvenue sur le backend K-Albums! (V13-BackendFusion)", 
        "status": "en fonctionnement"
    })

@app.route('/api/test')
def api_test():
    return jsonify({"message": "Réponse de test de l'API du backend!"})

def parse_invoice_products_from_text(full_text):
    """
    Logique de parsing des produits basée sur le script ChatGPT.
    Attend que chaque produit soit sur une ligne: "NomProduit QTE PRIX"
    ou Nom, puis ligne "Release:", puis ligne "Size/Ver... QTE PRIX"
    """
    lines = [l.strip() for l in full_text.split('\n') if l.strip()]
    parsed_products = []
    i = 0
    
    # Pattern principal: Nom sur une ligne, "Release : [date] Q P T" sur la suivante
    # OU Nom ET "Release : [date] Q P T" sur la même ligne
    # OU Nom, puis "Release :", puis "Size/Ver... Q P T"
    
    product_name_buffer = []

    while i < len(lines):
        line_content = lines[i]

        # Ignorer les en-têtes de tableau
        if re.match(r"^\s*Product\s+Quantity\s+Price\s+Total\s*$", line_content, re.IGNORECASE):
            if product_name_buffer:
                print(f"DEBUG_PDF_PARSE (V13): Buffer nom '{' '.join(product_name_buffer)}' vidé par header.")
            product_name_buffer = []
            i += 1
            continue

        if line_content.lower().startswith("subtotal"):
            if product_name_buffer:
                print(f"DEBUG_PDF_PARSE (V13): Buffer nom final non traité: '{' '.join(product_name_buffer)}'")
            break 

        # REGEX pour la ligne de détails: repère "Release :" + date (opt) + quantité + prix + total
        details_pattern = re.compile(
            r'^Release\s*:\s*(?P<date>\d{4}(?:-\d{2})?(?:-\d{2})?)?\s*(?P<quantity>\d+)\s*\$(?P<unit_price>\d+\.\d+)\s*\$(?P<total_price>\d+\.\d+)$'
        )
        # REGEX pour le cas "Size/Ver..." sur une ligne après une ligne "Release :" vide
        size_variation_pattern = re.compile(
            r'^(?:Size|Ver|Version|Type)\s*:\s*(?P<variation>.+?)(?P<quantity>\d+)\s*\$(?P<unit_price>\d+\.\d+)\s*\$(?P<total_price>\d+\.\d+)$',
            re.IGNORECASE
        )

        # Cas 1: Le nom du produit est dans le buffer, la ligne suivante a les détails
        if product_name_buffer and i + 1 < len(lines):
            details_line = lines[i+1]
            match_details = details_pattern.match(details_line)
            if match_details:
                name = " ".join(product_name_buffer).strip()
                date = match_details.group("date") or "N/A"
                quantity = int(match_details.group("quantity"))
                unit_price = float(match_details.group("unit_price"))
                parsed_products.append({"name": name, "quantity": quantity, "unit_price_usd": unit_price, "release_date": date})
                print(f"  ==> PRODUIT (V13 Cas Buffer+Details): {name} (Q:{quantity})")
                product_name_buffer = []
                i += 2 # On a traité le nom (buffer) et la ligne de détails
                continue
        
        # Cas 2: Le nom du produit ET les détails sont sur la ligne actuelle
        # (Cette regex est un peu simpliste, elle suppose que le nom ne contient pas "Release :")
        # On pourrait affiner pour capturer ce qui est AVANT "Release :" comme nom
        name_and_details_match = re.match(
            r'^(?P<name_on_line>.+?)\s*Release\s*:\s*(?P<date>\d{4}(?:-\d{2})?(?:-\d{2})?)?\s*(?P<quantity>\d+)\s*\$(?P<unit_price>\d+\.\d+)\s*\$(?P<total_price>\d+\.\d+)$',
            line_content
        )
        if name_and_details_match:
            name = name_and_details_match.group("name_on_line").strip()
            if product_name_buffer: # Si qqch était dans le buffer, on le préfixe
                name = " ".join(product_name_buffer).strip() + " " + name
            
            date = name_and_details_match.group("date") or "N/A"
            quantity = int(name_and_details_match.group("quantity"))
            unit_price = float(name_and_details_match.group("unit_price"))
            parsed_products.append({"name": name.strip(), "quantity": quantity, "unit_price_usd": unit_price, "release_date": date})
            print(f"  ==> PRODUIT (V13 Cas NomEtDetailsLigne): {name.strip()} (Q:{quantity})")
            product_name_buffer = []
            i += 1
            continue

        # Cas 3: Ligne "Release :" vide ou avec date seule, suivie d'une ligne "Size/Ver..."
        if line_content.lower().startswith("release :") and i + 2 < len(lines): # Besoin de 3 lignes: nom, Release, Size
            potential_size_line = lines[i+1] # Correction ici, on regarde i+1 car i est "Release :"
            
            # Vérifier si la ligne "Release :" est simple (juste date ou vide)
            is_simple_release = bool(re.match(r"Release\s*:\s*(\d{4}-\d{2}-\d{2})?\s*$", line_content))

            if is_simple_release:
                match_size_details = size_variation_pattern.match(potential_size_line)
                if match_size_details and product_name_buffer: # On a besoin d'un nom dans le buffer
                    name = " ".join(product_name_buffer).strip()
                    variation = match_size_details.group("variation").strip()
                    quantity = int(match_size_details.group("quantity"))
                    unit_price = float(match_size_details.group("unit_price"))
                    
                    date_on_release_line_match = re.match(r"Release\s*:\s*(\d{4}-\d{2}-\d{2})?", line_content)
                    date = date_on_release_line_match.group(1) if date_on_release_line_match and date_on_release_line_match.group(1) else "N/A"

                    parsed_products.append({"name": f"{name} ({variation})", "quantity": quantity, "unit_price_usd": unit_price, "release_date": date})
                    print(f"  ==> PRODUIT (V13 Cas Size/Ver): {name} ({variation}) (Q:{quantity})")
                    product_name_buffer = []
                    i += 2 # On a traité la ligne "Release :" et la ligne "Size..."
                    continue
        
        # Si aucun cas n'a matché et finalisé un produit, on ajoute la ligne au buffer si elle semble être un nom
        if line_content:
            product_name_buffer.append(line_content)
        
        i += 1
        
    return parsed_products

@app.route("/api/upload-invoice", methods=["POST"])
def upload_invoice():
    if "invoice_pdf" not in request.files:
        return jsonify({"error": "No PDF uploaded"}), 400
    pdf_file = request.files["invoice_pdf"]
    
    full_text_for_debug = "" # Pour renvoyer au frontend
    parsed_products = []
    shipping_cost_str = None
    bank_fee_str = None

    try:
        with pdfplumber.open(pdf_file) as pdf:
            for page in pdf.pages:
                text_from_page = page.extract_text()
                if text_from_page:
                    full_text_for_debug += text_from_page + "\n"
        
        if not full_text_for_debug.strip():
             print("Avertissement: pdfplumber n'a pas extrait de texte.")
             full_text_for_debug = "[pdfplumber n'a pas extrait de texte]"
        
        print(f"DEBUG_PDF_PARSE (V13): Texte extrait par pdfplumber, longueur: {len(full_text_for_debug)}")
        parsed_products = parse_invoice_products_from_text(full_text_for_debug)
        
        # Extraire les frais globaux (réutilisation de notre logique précédente)
        shipping_match = re.search(r"Shipping\s*\$?\s*(\d+\.?\d*)", full_text_for_debug, re.IGNORECASE)
        if shipping_match: shipping_cost_str = shipping_match.group(1)
        bank_fee_match = re.search(r"Bank transfer fee\s*\$?\s*(\d+\.?\d*)", full_text_for_debug, re.IGNORECASE)
        if bank_fee_match: bank_fee_str = bank_fee_match.group(1)

        print(f"DEBUG_PDF_PARSE (V13): {len(parsed_products)} produits trouvés.")
        print(f"DEBUG_PDF_PARSE (V13): Frais port: {shipping_cost_str}, Frais banque: {bank_fee_str}")

        return jsonify({
            "message": "Extraction produits (V13 avec pdfplumber), FDP et frais bancaires.",
            "filename": pdf_file.filename,
            "shipping_cost_usd": shipping_cost_str,
            "bank_transfer_fee_usd": bank_fee_str,
            "parsed_products": parsed_products,
            "DEVELOPMENT_full_text_for_debug": full_text_for_debug
        })

    except Exception as e:
        import traceback
        print("--- ERREUR BACKEND PDF PARSING ---")
        traceback.print_exc()
        return jsonify({"error": f"Erreur interne majeure PDF: {str(e)}"}), 500

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
        if "blackpink" in product_name_from_invoice.lower() and "the album" in product_name_from_invoice.lower():
            target_url = "https://www.kalbums.com/product-page/the-album-1st-full-album"
            debug_messages.append(f"URL de test spécifique utilisée pour '{product_name_from_invoice}': {target_url}")
        else:
            search_terms = product_name_from_invoice
            search_terms = re.sub(r"\[.*?POB.*?\]", "", search_terms, flags=re.IGNORECASE).strip()
            search_terms = re.sub(r"\(.*Ver\.\)", "", search_terms, flags=re.IGNORECASE).strip()
            # ... (autres re.sub pour nettoyer search_terms comme avant) ...
            search_terms = re.sub(r"\s+", "+", search_terms.strip())
            
            if not search_terms:
                 debug_messages.append(f"Nom produit '{product_name_from_invoice}' trop générique.")
                 return _make_json_response({"product_name_searched": product_name_from_invoice, "url_attempted": "N/A", "price_eur_ht": None, "error_message": "Nom produit trop générique pour recherche.", "debug_messages": debug_messages })
            
            search_url = f"https://www.kalbums.com/search?q={search_terms}"
            debug_messages.append(f"Construction URL de recherche: {search_url}")
            try:
                headers = {'User-Agent': 'Mozilla/5.0'}
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
        headers = {'User-Agent': 'Mozilla/5.0'}
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
    # Attention: pdfplumber peut ne pas bien fonctionner avec le reloader de Flask en mode debug
    # pour les fichiers temporaires si delete=False n'est pas géré correctement.
    # Pour la production avec Gunicorn, cela ne devrait pas poser de problème.
    app.run(host='0.0.0.0', port=8080, debug=True)
