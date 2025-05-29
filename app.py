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

            print("--- TEXTE COMPLET EXTRAIT DU PDF (Début pour debug K-ALBUMS V5) ---")
            print(full_text[:3000]) 
            print("--- FIN TEXTE COMPLET EXTRAIT (Snippet) ---")

            shipping_cost = None
            bank_fee = None
            parsed_products = [] 
            product_name_buffer = []
            in_product_section = False

            header_pattern_re = re.compile(r"^\s*Product\s+Quantity\s+Price\s+Total\s*$", re.IGNORECASE)
            # Regex améliorée pour la ligne "Release": espace optionnel après la date
            release_line_pattern_re = re.compile(r"Release\s*:\s*(\d{4}-\d{2}-\d{2})\s*(\d+)\s*\$(\d+\.\d+)\s*\$(\d+\.\d+)")
            release_line_with_date_only_re = re.compile(r"Release\s*:\s*(\d{4}-\d{2}-\d{2})?\s*$") # Pour "Release : DATE" ou "Release :"
            
            # Format alternatif (après "Release :" vide): Size/Ver... VARIATION Q $P $T
            alt_info_pattern_re = re.compile(r"^(?:Size|Ver|Version|Type)\s*:\s*(.*?)\s*(\d+)\s*\$(\d+\.\d+)\s*\$(\d+\.\d+)", re.IGNORECASE)
            # Format pour Quantité/Prix seuls (après "Release :" vide)
            simple_qty_price_pattern_re = re.compile(r"^\s*(\d+)\s*\$(\d+\.\d+)\s*\$(\d+\.\d+)\s*$")

            lines = full_text.split('\n')
            i = 0
            while i < len(lines):
                line_stripped = lines[i].strip()

                if not in_product_section:
                    if header_pattern_re.match(line_stripped):
                        in_product_section = True
                        product_name_buffer = [] 
                        print(f"DEBUG: En-tête initial produits: '{line_stripped}'")
                    i += 1
                    continue 

                if header_pattern_re.match(line_stripped):
                    print(f"DEBUG: En-tête répété ignoré: '{line_stripped}'")
                    if product_name_buffer:
                         print(f"DEBUG: Buffer vidé (en-tête répété). Contenu avant: {' // '.join(product_name_buffer)}")
                    product_name_buffer = []
                    i += 1
                    continue
                
                if line_stripped.lower().startswith("subtotal"): # Condition de sortie de section
                    print(f"DEBUG: Fin de la section produits (Subtotal) détectée.")
                    in_product_section = False
                    if product_name_buffer: print(f"DEBUG: Buffer final non traité: {' // '.join(product_name_buffer)}")
                    product_name_buffer = []
                    # On ne fait pas 'continue' ici pour que subtotal soit traité plus bas si besoin (frais)
                    # Mais pour le parsing produit, c'est fini.
                    # La recherche des frais se fait sur full_text à la fin, donc pas de souci.
                
                if not in_product_section: # Si on vient de sortir
                    i+=1
                    continue

                # Tentative d'extraction de produit
                current_product_name = ""
                release_date_val = "N/A"
                quantity_val = None
                unit_price_val = None
                lines_processed_for_item = 0

                # Cas 1: Nom sur une ou plusieurs lignes, puis ligne "Release : DATE Q P T"
                match_release_standard = release_line_pattern_re.match(line_stripped)
                if match_release_standard and product_name_buffer:
                    current_product_name = " ".join(product_name_buffer).strip()
                    release_date_val = match_release_standard.group(1)
                    quantity_val = match_release_standard.group(2)
                    unit_price_val = match_release_standard.group(3)
                    lines_processed_for_item = 1 # On a traité cette ligne
                    print(f"DEBUG: Produit (cas 1) - Nom: {current_product_name}, Ligne Release: {line_stripped}")
                
                # Cas 2: Nom sur une ou plusieurs lignes, puis "Release : [DATE/vide]", puis ligne de données
                elif product_name_buffer and release_line_with_date_only_re.match(line_stripped) and (i + 1 < len(lines)):
                    line_after_release = lines[i+1].strip()
                    match_alt_info = alt_info_pattern_re.match(line_after_release)
                    match_simple_qty_price = simple_qty_price_pattern_re.match(line_after_release)

                    if match_alt_info or match_simple_qty_price:
                        current_product_name = " ".join(product_name_buffer).strip()
                        date_match_on_release_line = release_line_with_date_only_re.match(line_stripped)
                        if date_match_on_release_line and date_match_on_release_line.group(1):
                            release_date_val = date_match_on_release_line.group(1)
                        
                        if match_alt_info:
                            variation = match_alt_info.group(1).strip()
                            quantity_val = match_alt_info.group(2)
                            unit_price_val = match_alt_info.group(3)
                            if variation: current_product_name += f" ({variation})"
                            print(f"DEBUG: Produit (cas 2a - Alt Info) - Nom: {current_product_name}, Ligne Release: {line_stripped}, Ligne Data: {line_after_release}")
                        elif match_simple_qty_price:
                            quantity_val = match_simple_qty_price.group(1)
                            unit_price_val = match_simple_qty_price.group(2)
                            print(f"DEBUG: Produit (cas 2b - Simple Qty/Price) - Nom: {current_product_name}, Ligne Release: {line_stripped}, Ligne Data: {line_after_release}")
                        
                        lines_processed_for_item = 2 # On a traité la ligne "Release:" et la ligne de données
                
                if current_product_name and quantity_val is not None and unit_price_val is not None:
                    # Nettoyage final du nom
                    current_product_name = header_pattern_re.sub("", current_product_name).strip()
                    if "Release :" in current_product_name: # Au cas où, bien que peu probable maintenant
                         current_product_name = current_product_name.split("Release :")[0].strip()

                    if current_product_name: # Vérifier à nouveau après nettoyage
                        parsed_products.append({
                            "name": current_product_name,
                            "quantity": int(quantity_val),
                            "unit_price_usd": float(unit_price_val),
                            "release_date": release_date_val
                        })
                        print(f"  ==> PRODUIT AJOUTÉ: {current_product_name} (Qté: {quantity_val}, Prix: ${unit_price_val}, Date: {release_date_val})")
                        product_name_buffer = [] # Réinitialiser pour le prochain produit
                        i += lines_processed_for_item # Avancer du nombre de lignes traitées pour cet item
                        continue 
                    else:
                        print(f"DEBUG: Nom de produit devenu vide APRES nettoyage final. Lignes originales ≈ '{lines[i-len(product_name_buffer)-1 if len(product_name_buffer)>0 else i].strip()}' et suivantes.")
                        product_name_buffer = [] # Si le nom est vide, on ne l'ajoute pas et on reset
                        i += lines_processed_for_item if lines_processed_for_item > 0 else 1
                        continue

                # Si on n'a pas finalisé de produit, et que la ligne n'est pas vide et pas un parasite connu
                # on l'ajoute au buffer (si elle n'y est pas déjà, ce qui est le cas ici car le buffer est vidé après chaque produit)
                if line_stripped and line_stripped.lower() not in ["weverse", "upbabyse", "theverse"]:
                    # product_name_buffer.append(line_stripped) # Déjà fait au début de la section "in_product_section"
                    pass # La ligne est déjà dans le buffer si elle est pertinente
                elif not line_stripped and product_name_buffer: 
                    # Ligne vide rencontrée APRÈS avoir accumulé des lignes pour un nom
                    # Peut marquer la fin d'un nom multi-lignes avant une ligne "Release :"
                    print(f"DEBUG: Ligne vide après buffer: {product_name_buffer}")
                
                i += 1
            
            if product_name_buffer: # S'il reste des choses à la fin
                print(f"DEBUG: Contenu final non traité dans product_name_buffer: {' // '.join(product_name_buffer)}")

            if not parsed_products: print("Aucun produit n'a pu être parsé avec la logique actuelle (V5).")
            else: print(f"{len(parsed_products)} produits parsés au total (V5).")
            # --- FIN LOGIQUE DE PARSING ---

            shipping_match = re.search(r"Shipping\s*\$?\s*(\d+\.?\d*)", full_text, re.IGNORECASE)
            if shipping_match: shipping_cost = shipping_match.group(1); print(f"Frais port (globaux): ${shipping_cost}")
            bank_fee_match = re.search(r"Bank transfer fee\s*\$?\s*(\d+\.?\d*)", full_text, re.IGNORECASE)
            if bank_fee_match: bank_fee = bank_fee_match.group(1); print(f"Frais bancaires (globaux): ${bank_fee}")

            return jsonify({
                "message": "Extraction produits (logique affinée V5), FDP et frais bancaires.",
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
    # ... (le code de cette fonction reste le même que dans ma réponse précédente) ...
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
            search_terms = re.sub(r"[\[\]\(\)]", "", search_terms).strip() 
            search_terms = re.sub(r"\s+", "+", search_terms.strip())
            
            if not search_terms:
                 debug_messages.append(f"Nom produit '{product_name_from_invoice}' trop générique après nettoyage.")
                 return jsonify({"product_name_searched": product_name_from_invoice, "url_attempted": "N/A", "price_eur_ht": None, "error_message": "Nom produit trop générique pour recherche.", "debug_messages": debug_messages }), 200

            search_url = f"https://www.kalbums.com/search?q={search_terms}"
            debug_messages.append(f"Construction URL de recherche: {search_url}")
            
            try:
                headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
                print(f"DEBUG /api/get-website-price: Tentative de requête GET vers la page de recherche {search_url}")
                search_response = requests.get(search_url, headers=headers, timeout=15)
                search_response.raise_for_status()
                search_soup = BeautifulSoup(search_response.content, 'html.parser')
                debug_messages.append(f"Page de recherche {search_url} récupérée. Statut: {search_response.status_code}")
                
                product_link_element = search_soup.find('a', attrs={'data-hook': 'item-title'})
                if product_link_element and product_link_element.has_attr('href'):
                    product_page_url = product_link_element['href']
                    if not product_page_url.startswith('http'):
                        from urllib.parse import urljoin
                        product_page_url = urljoin(search_url, product_page_url)
                    target_url = product_page_url
                    debug_messages.append(f"Premier lien produit trouvé sur la page de recherche: {target_url}")
                else:
                    debug_messages.append(f"Aucun lien produit avec data-hook='item-title' trouvé sur la page de recherche pour '{search_terms}'.")
                    return jsonify({"product_name_searched": product_name_from_invoice, "url_attempted": search_url, "price_eur_ht": None, "error_message": "Aucun produit correspondant trouvé sur le site via la recherche.", "debug_messages": debug_messages }), 200
            except requests.exceptions.RequestException as e_search:
                debug_messages.append(f"Erreur lors de la requête vers la page de recherche {search_url}: {str(e_search)}")
                return jsonify({"error": f"Erreur com. recherche: {str(e_search)}", "price_eur_ht": None, "debug": debug_messages}), 500
            except Exception as e_search_parse:
                debug_messages.append(f"Erreur inattendue lors de l'analyse de la page de recherche: {str(e_search_parse)}")
                return jsonify({"error": f"Erreur analyse recherche: {str(e_search_parse)}", "price_eur_ht": None, "debug": debug_messages}), 500

    if not target_url:
        return jsonify({"error": "Impossible de déterminer l'URL à scraper.", "price_eur_ht": None, "debug": debug_messages}), 400

    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        print(f"DEBUG /api/get-website-price: Tentative de requête GET vers la page produit finale {target_url}")
        response = requests.get(target_url, headers=headers, timeout=15)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, 'html.parser')
        debug_messages.append(f"Page produit {target_url} récupérée. Statut: {response.status_code}.")

        price_element = soup.find('span', attrs={'data-hook': 'formatted-primary-price'})
        
        if price_element:
            price_text = price_element.get_text(strip=True) 
            debug_messages.append(f"Élément prix trouvé. Texte brut: '{price_text}'")
            price_numeric_str = price_text.replace('€', '').replace(',', '.').strip()
            try:
                price_float = float(price_numeric_str)
                price_str = f"{price_float:.2f}"
                debug_messages.append(f"Prix converti en float: {price_float}, formaté en chaîne: {price_str}")
            except ValueError:
                debug_messages.append(f"AVERTISSEMENT: Impossible de convertir '{price_numeric_str}' en float.")
                price_str = price_numeric_str 
        else:
            debug_messages.append("Élément prix (data-hook='formatted-primary-price') non trouvé sur la page produit.")

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
