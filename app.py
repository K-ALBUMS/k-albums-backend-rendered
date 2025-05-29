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

            print("--- TEXTE COMPLET EXTRAIT DU PDF (Début pour debug K-ALBUMS) ---")
            # print(full_text) # Pourrait être trop long pour les logs Render standards
            print(full_text[:3000]) # Afficher un plus grand extrait
            print("--- FIN TEXTE COMPLET EXTRAIT (Snippet) ---")

            shipping_cost = None
            bank_fee = None
            parsed_products = [] 
            
            # --- LOGIQUE DE PARSING DES LIGNES PRODUITS (Affinement V4) ---
            lines = full_text.split('\n')
            product_name_buffer = []
            in_product_section = False

            header_pattern_re = re.compile(r"^\s*Product\s+Quantity\s+Price\s+Total\s*$", re.IGNORECASE)
            # Format standard: Release : YYYY-MM-DD Q $P $T
            release_line_pattern_re = re.compile(r"Release\s*:\s*(\d{4}-\d{2}-\d{2})\s*(\d+)\s*\$(\d+\.\d+)\s*\$(\d+\.\d+)")
            # Format alternatif (après "Release :" vide): Size/Ver... VARIATION Q $P $T
            alt_info_pattern_re = re.compile(r"^(?:Size|Ver|Version|Type)\s*:\s*(.*?)\s*(\d+)\s*\$(\d+\.\d+)\s*\$(\d+\.\d+)", re.IGNORECASE)
            # Format pour Quantité/Prix seuls (après "Release :" vide)
            simple_qty_price_pattern_re = re.compile(r"^\s*(\d+)\s*\$(\d+\.\d+)\s*\$(\d+\.\d+)\s*$")


            i = 0
            while i < len(lines):
                line_stripped = lines[i].strip()

                # 1. Gestion de l'entrée et de la sortie de la section des produits
                is_header = header_pattern_re.match(line_stripped)
                if not in_product_section:
                    if is_header:
                        in_product_section = True
                        product_name_buffer = []
                        print(f"DEBUG: En-tête initial produits: '{line_stripped}'")
                    i += 1
                    continue
                
                # Si on est dans la section produit et on tombe sur un autre en-tête,
                # on le note et on réinitialise le buffer pour le prochain produit.
                if is_header:
                    print(f"DEBUG: En-tête répété ignoré: '{line_stripped}'")
                    if product_name_buffer: # Ce qui était dans le buffer était un nom incomplet
                        print(f"DEBUG: Buffer vidé (en-tête répété). Contenu avant: {' // '.join(product_name_buffer)}")
                    product_name_buffer = []
                    i += 1
                    continue

                # Si la ligne ressemble à la fin de la liste des produits (ex: "Subtotal")
                if line_stripped.lower().startswith("subtotal") or \
                   line_stripped.lower().startswith("shipping") or \
                   line_stripped.lower().startswith("bank transfer fee") or \
                   line_stripped.lower().startswith("total"):
                    print(f"DEBUG: Fin de la section produits détectée à la ligne: '{line_stripped}'")
                    if product_name_buffer: # S'il restait quelque chose
                        print(f"DEBUG: Buffer final non traité: {' // '.join(product_name_buffer)}")
                    in_product_section = False # On sort de la section produit
                    product_name_buffer = []
                    # Ne pas faire continue ici, car cette ligne peut contenir "Shipping" ou "Bank transfer fee"
                    # qu'on veut traiter plus bas. On avance juste 'i'.
                
                # Si on est sorti de la section produit, on n'essaie plus de parser les produits
                if not in_product_section:
                    i += 1
                    continue

                # Accumuler les lignes pour le nom du produit
                # Mais seulement si la ligne n'est pas vide et ne commence pas par "Release" (pour éviter de la bufferiser)
                if line_stripped and not line_stripped.lower().startswith("release"):
                    product_name_buffer.append(line_stripped)
                
                # Tentative de détection de la fin d'un item produit
                # Cas 1: La ligne actuelle est "Release : DATE Q P T"
                release_match = release_line_pattern_re.match(line_stripped)
                
                # Cas 2: La ligne actuelle est "Release :" (vide), et la SUIVANTE contient les données
                is_empty_release_line = line_stripped.lower() == "release :"
                data_after_empty_release_match = None
                if is_empty_release_line and (i + 1 < len(lines)):
                    next_line_for_data = lines[i+1].strip()
                    data_after_empty_release_match = alt_info_pattern_re.match(next_line_for_data) or \
                                                 simple_qty_price_pattern_re.match(next_line_for_data)
                    if data_after_empty_release_match:
                         print(f"DEBUG: Ligne de données trouvée '{next_line_for_data}' après 'Release :' vide.")


                if release_match or data_after_empty_release_match:
                    final_product_name = ""
                    if data_after_empty_release_match: # Cas "Release :" vide
                        # Le nom est dans le buffer, SANS la ligne "Release :" elle-même
                        final_product_name = " ".join(product_name_buffer).strip()
                    elif release_match and product_name_buffer:
                        # Le nom est dans le buffer, qui INCLUT la ligne "Release...", donc on l'enlève
                        temp_name_buffer = [l for l in product_name_buffer if not release_line_pattern_re.match(l.strip())]
                        final_product_name = " ".join(temp_name_buffer).strip()
                    
                    # Nettoyage final du nom
                    final_product_name = header_pattern_re.sub("", final_product_name).strip()
                    if "Release :" in final_product_name: # Au cas où
                         final_product_name = final_product_name.split("Release :")[0].strip()
                    
                    if not final_product_name:
                        print(f"DEBUG: Nom de produit vide après nettoyage pour ligne(s) se terminant par chiffres: '{line_stripped}'" + (f" et '{lines[i+1].strip()}'" if data_after_empty_release_match else ""))
                        product_name_buffer = []
                        i += (2 if data_after_empty_release_match else 1)
                        continue

                    release_date_val = "N/A"
                    
                    if release_match:
                        release_date_val = release_match.group(1)
                        quantity = release_match.group(2)
                        unit_price = release_match.group(3)
                    elif data_after_empty_release_match: # alt_match ou simple_qty_price_match
                        # Essayer de récupérer une date si la ligne "Release :" en avait une avant d'être vide
                        date_on_release_line_match = re.match(r"Release\s*:\s*(\d{4}-\d{2}-\d{2})?", lines[i].strip()) # Ligne 'i' est "Release :"
                        if date_on_release_line_match and date_on_release_line_match.group(1):
                            release_date_val = date_on_release_line_match.group(1)
                        
                        # data_after_empty_release_match est soit alt_info_pattern_re soit simple_qty_price_pattern_re
                        if alt_info_pattern_re.match(lines[i+1].strip()): # Si c'est le format Size/Ver...
                            variation_name = data_after_empty_release_match.group(1).strip()
                            quantity = data_after_empty_release_match.group(2)
                            unit_price = data_after_empty_release_match.group(3)
                            if variation_name: final_product_name += f" ({variation_name})"
                        else: # C'est le format simple Q P T
                            quantity = data_after_empty_release_match.group(1)
                            unit_price = data_after_empty_release_match.group(2)
                            
                    parsed_products.append({
                        "name": final_product_name.strip(),
                        "quantity": int(quantity),
                        "unit_price_usd": float(unit_price),
                        "release_date": release_date_val
                    })
                    print(f"Produit trouvé: {final_product_name.strip()} (Qté: {quantity}, Prix: ${unit_price}, Date: {release_date_val})")
                    
                    product_name_buffer = [] # Vider le buffer
                    i += (2 if data_after_empty_release_match else 1) # Avancer de 2 si on a lu la ligne suivante, sinon 1
                    continue
                
                # Si ce n'est pas une ligne de fin de produit et qu'elle est vide, on peut la skipper 
                # si le buffer est déjà vide (pour éviter de commencer un nom par une ligne vide)
                if not line_stripped and not product_name_buffer:
                    i += 1
                    continue
                
                # Si ce n'est pas une ligne de fin de produit, et qu'elle n'est pas vide, 
                # et qu'elle n'a pas déjà été ajoutée au buffer (ce qui est le cas ici),
                # alors on la laisse dans le buffer pour le prochain tour de boucle.
                # Si la ligne EST la ligne "Release : " vide, elle sera dans le buffer,
                # et au prochain tour, i+1 sera la ligne de data.
                i += 1
            
            if product_name_buffer: # S'il reste des choses à la fin
                print(f"DEBUG: Contenu final non traité dans product_name_buffer: {' // '.join(product_name_buffer)}")

            if not parsed_products: print("Aucun produit n'a pu être parsé avec la logique actuelle.")
            else: print(f"{len(parsed_products)} produits parsés au total.")
            # --- FIN LOGIQUE DE PARSING ---

            # Recherche des frais globaux
            shipping_match = re.search(r"Shipping\s*\$?\s*(\d+\.?\d*)", full_text, re.IGNORECASE)
            if shipping_match: shipping_cost = shipping_match.group(1); print(f"Frais port (globaux): ${shipping_cost}")
            bank_fee_match = re.search(r"Bank transfer fee\s*\$?\s*(\d+\.?\d*)", full_text, re.IGNORECASE)
            if bank_fee_match: bank_fee = bank_fee_match.group(1); print(f"Frais bancaires (globaux): ${bank_fee}")

            return jsonify({
                "message": "Extraction produits (logique affinée V4), FDP et frais bancaires.",
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


# --- NOUVELLE ROUTE API POUR RÉCUPÉRER LE PRIX DU SITE WEB ---
@app.route('/api/get-website-price', methods=['POST'])
def get_website_price():
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
            # Tentative de recherche générique
            # 1. Nettoyer le nom du produit pour la recherche
            search_terms = product_name_from_invoice
            # Enlever les mentions POB, versions spécifiques etc. pour une recherche plus large
            search_terms = re.sub(r"\[.*?POB.*?\]", "", search_terms, flags=re.IGNORECASE).strip()
            search_terms = re.sub(r"\(.*Ver\.\)", "", search_terms, flags=re.IGNORECASE).strip()
            search_terms = re.sub(r"\(Random\)", "", search_terms, flags=re.IGNORECASE).strip()
            search_terms = re.sub(r"\(Set\)", "", search_terms, flags=re.IGNORECASE).strip()
            search_terms = re.sub(r"Mini Album", "", search_terms, flags=re.IGNORECASE).strip()
            search_terms = re.sub(r"Full Album", "", search_terms, flags=re.IGNORECASE).strip()
            search_terms = re.sub(r"EP ALBUM", "", search_terms, flags=re.IGNORECASE).strip()
            search_terms = re.sub(r"[\[\]\(\)]", "", search_terms).strip() # Enlever crochets et parenthèses restants
            search_terms = re.sub(r"\s+", "+", search_terms.strip()) # Remplacer espaces par + pour l'URL
            
            if not search_terms: # Si après nettoyage, il ne reste rien
                 debug_messages.append(f"Nom produit '{product_name_from_invoice}' trop générique après nettoyage.")
                 return jsonify({"product_name_searched": product_name_from_invoice, "url_attempted": "N/A", "price_eur_ht": None, "error_message": "Nom produit trop générique pour recherche.", "debug_messages": debug_messages }), 200

            search_url = f"https://www.kalbums.com/search?q={search_terms}"
            debug_messages.append(f"Construction URL de recherche: {search_url}")
            target_url = search_url # On va scraper la page de recherche

            try:
                headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
                print(f"DEBUG /api/get-website-price: Tentative de requête GET vers la page de recherche {search_url}")
                search_response = requests.get(search_url, headers=headers, timeout=15)
                search_response.raise_for_status()
                search_soup = BeautifulSoup(search_response.content, 'html.parser')
                debug_messages.append(f"Page de recherche {search_url} récupérée. Statut: {search_response.status_code}")

                # Essayer de trouver le premier lien produit pertinent sur la page de résultats
                # On cherche un lien avec data-hook="item-title"
                product_link_element = search_soup.find('a', attrs={'data-hook': 'item-title'})
                if product_link_element and product_link_element.has_attr('href'):
                    product_page_url = product_link_element['href']
                    # Vérifier si l'URL est relative ou absolue (Wix utilise souvent des URL absolues)
                    if not product_page_url.startswith('http'):
                        from urllib.parse import urljoin
                        product_page_url = urljoin(search_url, product_page_url)
                    
                    target_url = product_page_url # Mettre à jour target_url avec la page produit trouvée
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

    # Maintenant, scraper la page produit (target_url)
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

    except requests.exceptions.Timeout:
        debug_messages.append(f"Erreur Timeout lors de la requête vers {target_url}")
    except requests.exceptions.HTTPError as http_err:
        debug_messages.append(f"Erreur HTTP lors de la requête vers {target_url}: {http_err}")
    except requests.exceptions.RequestException as e:
        debug_messages.append(f"Erreur générale de requête vers {target_url}: {str(e)}")
    except Exception as e:
        debug_messages.append(f"Erreur inattendue lors du scraping de la page produit: {str(e)}")
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
