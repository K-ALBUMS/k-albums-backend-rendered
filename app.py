from flask import Flask, jsonify, request
from flask_cors import CORS
from PyPDF2 import PdfReader
import io
import re
import requests 
from bs4 import BeautifulSoup 
from urllib.parse import urljoin

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

            print("--- TEXTE COMPLET EXTRAIT DU PDF (Backend V10.1 - Vérification NameError) ---")
            print(full_text[:3000]) 
            print("--- FIN TEXTE COMPLET EXTRAIT (Snippet) ---")

            shipping_cost = None
            bank_fee = None
            parsed_products = [] 
            
            lines = full_text.split('\n')
            product_name_buffer = []
            in_product_section = False

            # Regex - Définitions vérifiées
            header_pattern_re = re.compile(r"^\s*Product\s+Quantity\s+Price\s+Total\s*$", re.IGNORECASE)
            release_data_pattern_re = re.compile(
                r"Release\s*:\s*(?P<date>\d{4}-\d{2}-\d{2})?\s*(?P<quantity>\d+)\s*\$(?P<unit_price>\d+\.\d+)\s*\$(?P<total_price>\d+\.\d+)"
            )
            # Assurez-vous que cette ligne est bien là et correcte
            release_line_only_re = re.compile(r"Release\s*:\s*(?P<date>\d{4}-\d{2}-\d{2})?\s*$")
            
            data_line_after_release_re = re.compile(
                r"^(?:(?:Size|Ver|Version|Type)\s*:\s*(?P<variation>.*?)\s*)?(?P<quantity>\d+)\s*\$(?P<unit_price>\d+\.\d+)\s*\$(?P<total_price>\d+\.\d+)\s*$", 
                re.IGNORECASE
            )

            i = 0
            while i < len(lines):
                line_stripped = lines[i].strip()
                product_extracted_this_iteration = False # Flag pour cette itération

                if not in_product_section:
                    if header_pattern_re.match(line_stripped):
                        in_product_section = True; product_name_buffer = []
                        print(f"DEBUG_PARSING (V10.1): En-tête initial: '{line_stripped}'")
                    i += 1; continue

                if header_pattern_re.match(line_stripped):
                    print(f"DEBUG_PARSING (V10.1): En-tête répété ignoré: '{line_stripped}'")
                    if product_name_buffer: print(f"DEBUG_PARSING (V10.1): Buffer nom '{'//'.join(product_name_buffer)}' perdu (en-tête).")
                    product_name_buffer = []
                    i += 1; continue
                
                if line_stripped.lower().startswith("subtotal"):
                    print(f"DEBUG_PARSING (V10.1): Fin section (Subtotal): '{line_stripped}'")
                    if product_name_buffer: print(f"DEBUG_PARSING (V10.1): Buffer final non traité: {'//'.join(product_name_buffer)}")
                    product_name_buffer = []; in_product_section = False; break 
                
                if not in_product_section: i += 1; continue

                current_name_str = ""
                release_date_val = "N/A"
                quantity_val = None
                unit_price_val = None
                lines_consumed_this_turn = 1 # Par défaut on avance d'une ligne
                
                match_release_data = release_data_pattern_re.match(line_stripped)
                # Utilisation de release_line_only_re ici
                match_release_line_only = release_line_only_re.match(line_stripped)

                if match_release_data:
                    name_part_on_release_line = line_stripped.split("Release :")[0].strip()
                    temp_name_from_buffer = " ".join(product_name_buffer).strip()
                    
                    current_name_str = temp_name_from_buffer
                    if not current_name_str and name_part_on_release_line and not header_pattern_re.match(name_part_on_release_line):
                        current_name_str = name_part_on_release_line
                    
                    if current_name_str:
                        release_date_val = match_release_data.group("date") if match_release_data.group("date") else "N/A"
                        quantity_val = match_release_data.group("quantity")
                        unit_price_val = match_release_data.group("unit_price")
                        print(f"DEBUG_PARSING (V10.1): Cas 1 - Nom: '{current_name_str}', Ligne: '{line_stripped}'")
                    else:
                        print(f"DEBUG_PARSING (V10.1): Cas 1 (QPT sur ligne Release) mais nom manquant. Ligne: '{line_stripped}' Buffer: {'//'.join(product_name_buffer)}")
                        if line_stripped: product_name_buffer = [line_stripped] 
                        else: product_name_buffer = []
                
                elif match_release_line_only: # Utilisation de la variable correctement définie
                    date_on_this_line = match_release_line_only.group("date") if match_release_line_only.group("date") else "N/A"
                    if (i + 1) < len(lines):
                        next_line_stripped = lines[i+1].strip()
                        match_data_next_line = data_line_after_release_re.match(next_line_stripped)
                        
                        if match_data_next_line:
                            current_name_str = " ".join(product_name_buffer).strip()
                            if current_name_str:
                                release_date_val = date_on_this_line
                                variation = match_data_next_line.group("variation")
                                quantity_val = match_data_next_line.group("quantity")
                                unit_price_val = match_data_next_line.group("unit_price")
                                if variation: current_name_str += f" ({variation.strip()})"
                                print(f"DEBUG_PARSING (V10.1): Cas 2 - Nom: '{current_name_str}', Release: '{line_stripped}', Data: '{next_line_stripped}'")
                                lines_consumed_this_turn = 2
                            else:
                                print(f"DEBUG_PARSING (V10.1): Cas 2 ignoré (nom vide). Release: '{line_stripped}'")
                                if line_stripped: product_name_buffer = [line_stripped] 
                                else: product_name_buffer = []
                        else: 
                            if line_stripped: product_name_buffer.append(line_stripped)
                    else: 
                         if line_stripped: product_name_buffer.append(line_stripped)
                else: 
                    if line_stripped: product_name_buffer.append(line_stripped)

                if quantity_val is not None and unit_price_val is not None:
                    final_name = current_name_str 
                    final_name = header_pattern_re.sub("", final_name).strip()
                    if "Release :" in final_name: final_name = final_name.split("Release :")[0].strip()
                    
                    if final_name:
                        parsed_products.append({
                            "name": final_name, "quantity": int(quantity_val),
                            "unit_price_usd": float(unit_price_val), "release_date": release_date_val
                        })
                        print(f"  ==> PRODUIT AJOUTÉ (V10.1): {final_name} (Qté: {quantity_val}, Prix: ${unit_price_val}, Date: {release_date_val})")
                        product_extracted_this_iteration = True # Marquer qu'on a extrait
                    else:
                         print(f"DEBUG_PARSING (V10.1): Nom produit vide APRES nettoyage. Ligne approx: '{lines[i if i < len(lines) else i-1].strip()}'")
                    
                    product_name_buffer = [] # TOUJOURS vider le buffer après avoir traité un produit
                
                i += lines_consumed_this_turn
            
            if product_name_buffer:
                print(f"DEBUG_PARSING (V10.1): Buffer final non traité: {' // '.join(product_name_buffer)}")

            if not parsed_products: print("Aucun produit n'a pu être parsé (V10.1).")
            else: print(f"{len(parsed_products)} produits parsés au total (V10.1).")
            
            shipping_match = re.search(r"Shipping\s*\$?\s*(\d+\.?\d*)", full_text, re.IGNORECASE)
            if shipping_match: shipping_cost = shipping_match.group(1); print(f"Frais port (globaux): ${shipping_cost}")
            bank_fee_match = re.search(r"Bank transfer fee\s*\$?\s*(\d+\.?\d*)", full_text, re.IGNORECASE)
            if bank_fee_match: bank_fee = bank_fee_match.group(1); print(f"Frais bancaires (globaux): ${bank_fee}")

            return jsonify({
                "message": "Extraction produits (logique affinée V10.1), FDP et frais bancaires.",
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
            search_terms = re.sub(r"\(Random\)", "", search_terms, flags=re.IGNORECASE).strip()
            search_terms = re.sub(r"\(Set\)", "", search_terms, flags=re.IGNORECASE).strip()
            search_terms = re.sub(r"Mini Album", "", search_terms, flags=re.IGNORECASE).strip()
            search_terms = re.sub(r"Full Album", "", search_terms, flags=re.IGNORECASE).strip()
            search_terms = re.sub(r"EP ALBUM", "", search_terms, flags=re.IGNORECASE).strip()
            search_terms = re.sub(r"[\[\]()]", "", search_terms).strip() 
            search_terms = re.sub(r"['‘’]", "", search_terms).strip() 
            search_terms = re.sub(r"[^\w\s-]", "", search_terms).strip() 
            search_terms = re.sub(r"\s+", "+", search_terms.strip())
            if not search_terms:
                 debug_messages.append(f"Nom produit '{product_name_from_invoice}' trop générique après nettoyage.")
                 return jsonify({"product_name_searched": product_name_from_invoice, "url_attempted": "N/A", "price_eur_ht": None, "error_message": "Nom produit trop générique pour recherche.", "debug_messages": debug_messages }), 200
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
        return jsonify({"error": "Impossible de déterminer l'URL à scraper.", "price_eur_ht": None, "debug": debug_messages}), 400
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
    except requests.exceptions.Timeout: debug_messages.append(f"Erreur Timeout vers {target_url}")
    except requests.exceptions.HTTPError as http_err: debug_messages.append(f"Erreur HTTP vers {target_url}: {http_err}")
    except requests.exceptions.RequestException as e: debug_messages.append(f"Erreur requête vers {target_url}: {str(e)}")
    except Exception as e:
        debug_messages.append(f"Erreur inattendue scraping page produit: {str(e)}")
        import traceback
        debug_messages.append(traceback.format_exc())
    return jsonify({ "product_name_searched": product_name_from_invoice, "url_attempted": target_url, "price_eur_ht": price_str, "debug_messages": debug_messages })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True)
