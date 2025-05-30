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
            print("--- TEXTE COMPLET EXTRAIT DU PDF (Backend V11) ---"); print(full_text[:3000]); print("--- FIN TEXTE COMPLET (Snippet) ---")

            shipping_cost = None; bank_fee = None; parsed_products = [] 
            lines = full_text.split('\n'); product_name_buffer = []; in_product_section = False

            header_re = re.compile(r"^\s*Product\s+Quantity\s+Price\s+Total\s*$", re.IGNORECASE)
            # Cas 1: Nom sur la ligne + "Release : [DATE] Q P T" OU juste "Release : [DATE] Q P T"
            name_and_release_data_re = re.compile(
                r"^(?P<name_on_line>.*?)(?:Release\s*:\s*(?P<date>\d{4}-\d{2}-\d{2})?\s*(?P<quantity>\d+)\s*\$(?P<unit_price>\d+\.\d+)\s*\$(?P<total_price>\d+\.\d+))$"
            )
            # Cas 2: Ligne "Release : [DATE]" ou "Release :" (vide)
            release_only_re = re.compile(r"Release\s*:\s*(?P<date>\d{4}-\d{2}-\d{2})?\s*$")
            # Cas 3: Ligne de données Q P T (avec ou sans variation) APRES une ligne "Release :" vide/avec date seule
            data_after_release_re = re.compile(
                r"^(?:(?:Size|Ver|Version|Type)\s*:\s*(?P<variation>.*?)\s*)?(?P<quantity>\d+)\s*\$(?P<unit_price>\d+\.\d+)\s*\$(?P<total_price>\d+\.\d+)\s*$", 
                re.IGNORECASE
            )

            i = 0
            while i < len(lines):
                line = lines[i].strip()
                product_finalized = False

                if not in_product_section:
                    if header_re.match(line): in_product_section = True; product_name_buffer = []; print(f"DEBUG (V11): Entrée section produits: '{line}'")
                    i += 1; continue
                if header_re.match(line):
                    if product_name_buffer: print(f"DEBUG (V11): Buffer '{'//'.join(product_name_buffer)}' vidé par header.")
                    product_name_buffer = []; print(f"DEBUG (V11): Header répété ignoré: '{line}'")
                    i += 1; continue
                if line.lower().startswith("subtotal"):
                    if product_name_buffer: print(f"DEBUG (V11): Buffer final non traité: {'//'.join(product_name_buffer)}")
                    product_name_buffer = []; in_product_section = False; print(f"DEBUG (V11): Sortie section (Subtotal): '{line}'"); break
                
                # Essayer CAS 1: Nom et Release Data sur la même ligne, OU juste Release Data si buffer a un nom
                match_name_release = name_and_release_data_re.match(line)
                if match_name_release:
                    name_on_line = match_name_release.group("name_on_line").strip()
                    name_from_buffer = " ".join(product_name_buffer).strip()
                    
                    current_name = name_from_buffer if name_from_buffer else name_on_line
                    if not current_name and name_on_line : current_name = name_on_line # Si buffer vide mais nom sur ligne release

                    if current_name: # Si on a un nom (soit du buffer, soit de la ligne)
                        date = match_name_release.group("date") or "N/A"
                        qty = match_name_release.group("quantity")
                        price = match_name_release.group("unit_price")
                        parsed_products.append({"name": current_name, "quantity": int(qty), "unit_price_usd": float(price), "release_date": date})
                        print(f"  ==> PRODUIT (V11 Cas 1): {current_name} (Q:{qty} P:${price} D:{date})")
                        product_name_buffer = []
                        product_finalized = True
                    else: # Ligne Release avec data mais pas de nom avant
                        print(f"DEBUG (V11): Ligne Release data SANS NOM: '{line}'")
                        # On ne l'ajoute pas comme produit, et on ne la met pas dans le buffer nom.
                        # On va juste l'ignorer et passer à la suivante. product_name_buffer reste tel quel.
                        # product_name_buffer = [] # Vider au cas où? Non, on veut garder ce qu'il y avait avant.
                
                # Essayer CAS 2: Ligne "Release : [DATE/vide]" (si CAS 1 n'a pas marché)
                elif release_line_only_re.match(line):
                    if (i + 1) < len(lines):
                        next_line = lines[i+1].strip()
                        match_data_next = data_after_release_re.match(next_line)
                        if match_data_next: # La ligne suivante a les données QPT
                            current_name = " ".join(product_name_buffer).strip()
                            if current_name:
                                date_on_rl = release_line_only_re.match(line).group("date") or "N/A"
                                variation = match_data_next.group("variation")
                                qty = match_data_next.group("quantity")
                                price = match_data_next.group("unit_price")
                                if variation: current_name += f" ({variation.strip()})"
                                
                                parsed_products.append({"name": current_name, "quantity": int(qty), "unit_price_usd": float(price), "release_date": date_on_rl})
                                print(f"  ==> PRODUIT (V11 Cas 2): {current_name} (Q:{qty} P:${price} D:{date_on_rl})")
                                product_name_buffer = []
                                i += 1 # On a consommé la ligne suivante aussi
                                product_finalized = True
                            else: # Release vide mais pas de nom dans buffer
                                print(f"DEBUG (V11): Release vide SANS NOM: '{line}', Data: '{next_line}'")
                                # On ne fait rien, on ne bufferise pas la ligne "Release :" vide
                        else: # Ligne "Release :" mais la suivante n'est pas une ligne de données
                            if line: product_name_buffer.append(line) # On ajoute "Release..." au nom potentiel
                    else: # Fin de fichier après une ligne "Release :"
                        if line: product_name_buffer.append(line)
                
                # Si on n'a pas finalisé de produit, et que la ligne n'est pas une ligne "Release"
                # (car les cas Release ont été traités), on l'ajoute au buffer si elle n'est pas vide.
                if not product_finalized and line and not release_line_only_re.match(line) and not name_and_release_data_re.match(line):
                    product_name_buffer.append(line)
                elif not product_finalized and not line and product_name_buffer: # Ligne vide après avoir accumulé un nom
                     print(f"DEBUG_PARSING (V11): Ligne vide après buffer (non finalisé): {' // '.join(product_name_buffer)}")
                
                i += 1
            
            if product_name_buffer: print(f"DEBUG_PARSING (V11): Buffer final non traité: {'//'.join(product_name_buffer)}")
            
            # Nettoyage final des noms (enlever les en-têtes qui auraient pu s'y glisser)
            final_cleaned_products = []
            for product in parsed_products:
                cleaned_name = header_pattern_re.sub("", product["name"]).strip()
                if cleaned_name: 
                    product["name"] = cleaned_name
                    final_cleaned_products.append(product)
                else: print(f"DEBUG_PARSING (V11): Produit supprimé (nom vide post-nettoyage). Orig: {product['name']}")
            parsed_products = final_cleaned_products

            if not parsed_products: print("Aucun produit n'a pu être parsé (V11).")
            else: print(f"{len(parsed_products)} produits parsés au total (V11).")
            
            shipping_match = re.search(r"Shipping\s*\$?\s*(\d+\.?\d*)", full_text, re.IGNORECASE)
            if shipping_match: shipping_cost = shipping_match.group(1); print(f"Frais port (globaux): ${shipping_cost}")
            bank_fee_match = re.search(r"Bank transfer fee\s*\$?\s*(\d+\.?\d*)", full_text, re.IGNORECASE)
            if bank_fee_match: bank_fee = bank_fee_match.group(1); print(f"Frais bancaires (globaux): ${bank_fee}")

            return jsonify({
                "message": "Extraction produits (logique affinée V11), FDP et frais bancaires.",
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
