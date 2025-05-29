from flask import Flask, jsonify, request
from flask_cors import CORS
from PyPDF2 import PdfReader
import io
import re
import requests 
from bs4 import BeautifulSoup 

app = Flask(__name__)
CORS(app)

@app.route('/')
def home():
    return jsonify({
        "message": "Bienvenue sur le backend K-Albums!", 
        "status": "en fonctionnement",
        "info": "Ceci est un service hébergé sur Render."
    })

@app.route('/api/test')
def api_test():
    return jsonify({"message": "Réponse de test de l'API du backend!"})

@app.route('/api/upload-invoice', methods=['POST'])
def upload_invoice():
    if 'invoice_pdf' not in request.files:
        return jsonify({"error": "Aucun fichier PDF trouvé dans la requête"}), 400
    
    file = request.files['invoice_pdf']
    if file.filename == '':
        return jsonify({"error": "Aucun fichier sélectionné"}), 400
    
    if file:
        try:
            print(f"--- Nouveau traitement de PDF : {file.filename} ---")
            file_content_in_memory = io.BytesIO(file.read())
            reader = PdfReader(file_content_in_memory)
            
            full_text = ""
            for page_num in range(len(reader.pages)):
                page = reader.pages[page_num]
                page_text = page.extract_text()
                if page_text:
                    full_text += page_text + "\n"
            
            if not full_text.strip():
                full_text = "[PyPDF2 n'a pas pu extraire de texte. Le PDF est peut-être une image ou vide.]"
                print("Avertissement: Texte du PDF vide ou non extractible.")

            print("--- TEXTE COMPLET EXTRAIT DU PDF (Début pour debug K-ALBUMS V6) ---")
            print(full_text[:3000]) 
            print("--- FIN TEXTE COMPLET EXTRAIT (Snippet) ---")

            shipping_cost = None
            bank_fee = None
            parsed_products = [] 
            
            lines = full_text.split('\n')
            product_name_buffer = []
            in_product_section = False

            header_pattern_re = re.compile(r"^\s*Product\s+Quantity\s+Price\s+Total\s*$", re.IGNORECASE)
            # Format standard: Release : YYYY-MM-DD Q $P $T (espace après date optionnel)
            release_line_pattern_re = re.compile(r"Release\s*:\s*(\d{4}-\d{2}-\d{2})\s*(\d+)\s*\$(\d+\.\d+)\s*\$(\d+\.\d+)")
            # Pour les cas où la date est seule sur la ligne "Release :" ou si la ligne est juste "Release :"
            release_line_date_only_or_empty_re = re.compile(r"Release\s*:\s*(\d{4}-\d{2}-\d{2})?\s*$")
            # Format alternatif pour la ligne de données (après un "Release :" vide) : Size/Ver... VARIATION Q $P $T
            alt_data_line_pattern_re = re.compile(r"^(?:Size|Ver|Version|Type)\s*:\s*(.*?)\s*(\d+)\s*\$(\d+\.\d+)\s*\$(\d+\.\d+)", re.IGNORECASE)
            # Format pour Quantité/Prix seuls (après "Release :" vide), ex: "2 $39.85 $79.70"
            simple_data_line_pattern_re = re.compile(r"^\s*(\d+)\s*\$(\d+\.\d+)\s*\$(\d+\.\d+)\s*$")

            i = 0
            while i < len(lines):
                line_stripped = lines[i].strip()

                if not in_product_section:
                    if header_pattern_re.match(line_stripped):
                        in_product_section = True
                        product_name_buffer = [] 
                        print(f"DEBUG_PARSING: En-tête initial produits: '{line_stripped}'")
                    i += 1
                    continue 

                if header_pattern_re.match(line_stripped):
                    print(f"DEBUG_PARSING: En-tête répété ignoré: '{line_stripped}'")
                    if product_name_buffer:
                         print(f"DEBUG_PARSING: Buffer vidé (en-tête répété). Contenu avant: {' // '.join(product_name_buffer)}")
                    product_name_buffer = []
                    i += 1
                    continue
                
                # Condition de sortie de la section des produits (peut être affinée)
                if line_stripped.lower().startswith("subtotal"):
                    print(f"DEBUG_PARSING: Fin de section produits (Subtotal): '{line_stripped}'")
                    if product_name_buffer: print(f"DEBUG_PARSING: Buffer final non traité: {' // '.join(product_name_buffer)}")
                    product_name_buffer = []
                    in_product_section = False 
                    # Les frais seront extraits globalement après la boucle
                    break # Sortir de la boucle de parsing des produits

                # Tentative d'extraction
                product_name_candidate = ""
                release_date_val = "N/A"
                quantity_val = None
                unit_price_val = None
                
                # CAS 1: Ligne "Release : YYYY-MM-DD Q $P $T"
                # Le nom du produit est dans le buffer accumulé juste avant cette ligne.
                release_match_standard = release_line_pattern_re.match(line_stripped)
                if release_match_standard and product_name_buffer:
                    product_name_candidate = " ".join(product_name_buffer).strip()
                    release_date_val = release_match_standard.group(1)
                    quantity_val = release_match_standard.group(2)
                    unit_price_val = release_match_standard.group(3)
                    print(f"DEBUG_PARSING: Cas 1 - Nom: '{product_name_candidate}', Ligne Release: '{line_stripped}'")
                    product_name_buffer = [] # Prêt pour le prochain produit
                    i += 1 # On a traité cette ligne

                # CAS 2: Ligne "Release : [DATE/vide]" suivie d'une ligne de données
                elif release_line_date_only_or_empty_re.match(line_stripped) and (i + 1 < len(lines)):
                    # La ligne actuelle (i) est la ligne "Release : [DATE/vide]"
                    # La ligne suivante (i+1) devrait contenir Q, P, T
                    potential_data_line = lines[i+1].strip()
                    
                    # Essayer le format "Size/Ver... Q P T"
                    match_alt_data = alt_data_line_pattern_re.match(potential_data_line)
                    # Essayer le format "Q P T" simple
                    match_simple_data = simple_qty_price_pattern_re.match(potential_data_line)

                    if match_alt_data or match_simple_data:
                        product_name_candidate = " ".join(product_name_buffer).strip() # Nom est ce qui a été accumulé AVANT la ligne "Release :"
                        
                        # Récupérer la date de la ligne "Release :" si elle existe
                        date_on_release_line = release_line_date_only_or_empty_re.match(line_stripped)
                        if date_on_release_line and date_on_release_line.group(1):
                            release_date_val = date_on_release_line.group(1)

                        if match_alt_data:
                            variation = match_alt_data.group(1).strip()
                            quantity_val = match_alt_data.group(2)
                            unit_price_val = match_alt_data.group(3)
                            if variation: product_name_candidate += f" ({variation})" # Ajoute la variation au nom
                            print(f"DEBUG_PARSING: Cas 2a (Alt Data) - Nom: '{product_name_candidate}', Ligne Release: '{line_stripped}', Ligne Data: '{potential_data_line}'")
                        elif match_simple_data:
                            quantity_val = match_simple_data.group(1)
                            unit_price_val = match_simple_data.group(2)
                            print(f"DEBUG_PARSING: Cas 2b (Simple Data) - Nom: '{product_name_candidate}', Ligne Release: '{line_stripped}', Ligne Data: '{potential_data_line}'")
                        
                        product_name_buffer = [] # Prêt pour le prochain produit
                        i += 2 # On a traité la ligne "Release :" et la ligne de données
                    else:
                        # La ligne actuelle était "Release : [DATE/vide]" mais la suivante n'est pas une ligne de données reconnue
                        # On ajoute la ligne "Release :" au buffer et on continue
                        if line_stripped: product_name_buffer.append(line_stripped)
                        i += 1
                
                # Si aucun des cas ci-dessus n'a extrait un produit, on ajoute la ligne au buffer (si non vide et non parasite)
                else:
                    if line_stripped and line_stripped.lower() not in ["weverse", "upbabyse", "theverse"]:
                        product_name_buffer.append(line_stripped)
                    elif not line_stripped and product_name_buffer: # Ligne vide après avoir accumulé un nom
                        print(f"DEBUG_PARSING: Ligne vide après buffer: {' // '.join(product_name_buffer)}. Buffer conservé pour prochaine ligne.")
                    i += 1

                # Si un produit a été identifié (quantity_val et unit_price_val sont remplis)
                if product_name_candidate and quantity_val is not None and unit_price_val is not None:
                    # Nettoyage final du nom
                    final_name = header_pattern_re.sub("", product_name_candidate).strip()
                    if "Release :" in final_name: # Retirer "Release :" si accidentellement inclus
                         final_name = final_name.split("Release :")[0].strip()
                    
                    if final_name: # S'assurer qu'on a toujours un nom après nettoyage
                        parsed_products.append({
                            "name": final_name,
                            "quantity": int(quantity_val),
                            "unit_price_usd": float(unit_price_val),
                            "release_date": release_date_val
                        })
                        print(f"  ==> PRODUIT AJOUTÉ: {final_name} (Qté: {quantity_val}, Prix: ${unit_price_val}, Date: {release_date_val})")
                    else:
                         print(f"DEBUG_PARSING: Nom de produit devenu vide APRES nettoyage final.")
            
            if product_name_buffer: # S'il reste des choses à la fin
                print(f"DEBUG_PARSING: Contenu final non traité dans product_name_buffer: {' // '.join(product_name_buffer)}")

            if not parsed_products: print("Aucun produit n'a pu être parsé avec la logique actuelle (V6).")
            else: print(f"{len(parsed_products)} produits parsés au total (V6).")
            # --- FIN LOGIQUE DE PARSING ---

            shipping_match = re.search(r"Shipping\s*\$?\s*(\d+\.?\d*)", full_text, re.IGNORECASE)
            if shipping_match: shipping_cost = shipping_match.group(1); print(f"Frais port (globaux): ${shipping_cost}")
            bank_fee_match = re.search(r"Bank transfer fee\s*\$?\s*(\d+\.?\d*)", full_text, re.IGNORECASE)
            if bank_fee_match: bank_fee = bank_fee_match.group(1); print(f"Frais bancaires (globaux): ${bank_fee}")

            return jsonify({
                "message": "Extraction produits (logique affinée V6), FDP et frais bancaires.",
                "filename": file.filename,
                "shipping_cost_usd": shipping_cost,
                "bank_transfer_fee_usd": bank_fee,
                "parsed_products": parsed_products,
                "DEVELOPMENT_full_text_for_debug": full_text 
            })

        except Exception as e:
            print(f"Erreur critique lors du traitement du PDF : {e}")
            import traceback
            traceback.print_exc() 
            return jsonify({"error": f"Erreur interne majeure lors du traitement du PDF: {str(e)}"}), 500
    
    return jsonify({"error": "Un problème est survenu avec le fichier ou fichier non traité."}), 500


@app.route('/api/get-website-price', methods=['POST'])
def get_website_price():
    # ... (Code de cette fonction reste identique à la version précédente) ...
    data = request.get_json()
    product_name_from_invoice = data.get('productName')
    product_url_on_website = data.get('productUrl') 

    print(f"DEBUG /api/get-website-price: Reçu productName='{product_name_from_invoice}', productUrl='{product_url_on_website}'")

    if not product_url_on_website and not product_name_from_invoice: 
        return jsonify({"error": "Nom du produit ou URL du produit manquant."}), 400

    price_str = None
    debug_messages = []
    target_url = None 

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
            search_terms = re.sub(r"\(Random\)", "", search_terms, flags=re.IGNORECASE).strip()
            search_terms = re.sub(r"\(Set\)", "", search_terms, flags=re.IGNORECASE).strip()
            search_terms = re.sub(r"Mini Album", "", search_terms, flags=re.IGNORECASE).strip()
            search_terms = re.sub(r"Full Album", "", search_terms, flags=re.IGNORECASE).strip()
            search_terms = re.sub(r"EP ALBUM", "", search_terms, flags=re.IGNORECASE).strip()
            search_terms = re.sub(r"[\[\]()]", "", search_terms).strip() # Enlever crochets et parenthèses
            search_terms = re.sub(r"['‘’]", "", search_terms).strip() # Enlever apostrophes
            search_terms = re.sub(r"[^\w\s-]", "", search_terms).strip() # Garder lettres, chiffres, espaces, tirets
            search_terms = re.sub(r"\s+", "+", search_terms.strip())
            
            if not search_terms:
                 debug_messages.append(f"Nom produit '{product_name_from_invoice}' trop générique après nettoyage.")
                 return jsonify({"product_name_searched": product_name_from_invoice, "url_attempted": "N/A", "price_eur_ht": None, "error_message": "Nom produit trop générique pour recherche.", "debug_messages": debug_messages }), 200

            search_url = f"https://www.kalbums.com/search?q={search_terms}"
            debug_messages.append(f"Construction URL de recherche: {search_url}")
            
            try:
                headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
                print(f"DEBUG /api/get-website-price: Requête GET vers page de recherche {search_url}")
                search_response = requests.get(search_url, headers=headers, timeout=15)
                search_response.raise_for_status()
                search_soup = BeautifulSoup(search_response.content, 'html.parser')
                debug_messages.append(f"Page recherche {search_url} OK. Statut: {search_response.status_code}")
                
                product_link_element = search_soup.find('a', attrs={'data-hook': 'item-title'})
                if product_link_element and product_link_element.has_attr('href'):
                    product_page_url = product_link_element['href']
                    if not product_page_url.startswith('http'):
                        from urllib.parse import urljoin
                        product_page_url = urljoin(search_url, product_page_url)
                    target_url = product_page_url
                    debug_messages.append(f"Premier lien produit trouvé sur page recherche: {target_url}")
                else:
                    debug_messages.append(f"Aucun lien produit (data-hook='item-title') sur page recherche pour '{search_terms}'.")
                    return jsonify({"product_name_searched": product_name_from_invoice, "url_attempted": search_url, "price_eur_ht": None, "error_message": "Aucun produit correspondant trouvé via recherche.", "debug_messages": debug_messages }), 200
            except requests.exceptions.RequestException as e_search:
                debug_messages.append(f"Erreur requête vers page recherche {search_url}: {str(e_search)}")
                return jsonify({"error": f"Erreur com. recherche: {str(e_search)}", "price_eur_ht": None, "debug": debug_messages}), 500
            except Exception as e_search_parse:
                debug_messages.append(f"Erreur analyse page recherche: {str(e_search_parse)}")
                return jsonify({"error": f"Erreur analyse recherche: {str(e_search_parse)}", "price_eur_ht": None, "debug": debug_messages}), 500

    if not target_url:
        return jsonify({"error": "Impossible de déterminer l'URL produit à scraper.", "price_eur_ht": None, "debug": debug_messages}), 400

    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        print(f"DEBUG /api/get-website-price: Requête GET vers page produit finale {target_url}")
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

    except requests.exceptions.Timeout: debug_messages.append(f"Erreur Timeout vers {target_url}")
    except requests.exceptions.HTTPError as http_err: debug_messages.append(f"Erreur HTTP vers {target_url}: {http_err}")
    except requests.exceptions.RequestException as e: debug_messages.append(f"Erreur requête vers {target_url}: {str(e)}")
    except Exception as e:
        debug_messages.append(f"Erreur inattendue scraping page produit: {str(e)}")
        import traceback
        debug_messages.append(traceback.format_exc())

    return jsonify({
        "product_name_searched": product_name_from_invoice,
        "url_attempted": target_url,
        "price_eur_ht": price_str, 
        "debug_messages": debug_messages
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True)
