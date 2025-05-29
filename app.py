from flask import Flask, jsonify, request
from flask_cors import CORS
from PyPDF2 import PdfReader
import io
import re
import requests # Pour faire des requêtes HTTP
from bs4 import BeautifulSoup # Pour analyser le HTML

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

            print("--- TEXTE COMPLET EXTRAIT DU PDF (Début pour debug) ---")
            print(full_text[:2000]) # Affiche les 2000 premiers caractères pour le log Render
            print("--- FIN TEXTE COMPLET EXTRAIT (Snippet) ---")

            shipping_cost = None
            bank_fee = None
            parsed_products = [] 
            product_name_buffer = []
            in_product_section = False

            header_pattern_re = re.compile(r"^\s*Product\s+Quantity\s+Price\s+Total\s*$", re.IGNORECASE)
            release_line_pattern_re = re.compile(r"Release\s*:\s*(\d{4}-\d{2}-\d{2})\s*(\d+)\s*\$(\d+\.\d+)\s*\$(\d+\.\d+)")
            alt_release_pattern_re = re.compile(r"^(?:Size|Ver|Version|Type)\s*:\s*(.*?)\s*(\d+)\s*\$(\d+\.\d+)\s*\$(\d+\.\d+)", re.IGNORECASE)
            # Pattern pour les lignes Quantité/Prix qui suivent directement une ligne "Release :" vide (comme pour les lightsticks)
            simple_qty_price_pattern_re = re.compile(r"^\s*(\d+)\s*\$(\d+\.\d+)\s*\$(\d+\.\d+)\s*$")


            lines = full_text.split('\n')
            for i in range(len(lines)):
                line_stripped = lines[i].strip()
                
                is_header_line = header_pattern_re.match(line_stripped)

                if not in_product_section:
                    if is_header_line:
                        in_product_section = True
                        product_name_buffer = [] 
                        print(f"DEBUG: En-tête initial du tableau des produits trouvé: '{line_stripped}'")
                    continue 

                if is_header_line:
                    print(f"DEBUG: En-tête de tableau répétée ignorée: '{line_stripped}'")
                    if product_name_buffer:
                         print(f"DEBUG: Buffer vidé à cause d'un en-tête répété. Contenu: {' '.join(product_name_buffer)}")
                    product_name_buffer = []
                    continue
                
                release_match = release_line_pattern_re.match(line_stripped)
                alt_match = None
                simple_qty_price_match = None

                # Cas 1: Ligne "Release : DATE Q P T" standard
                if release_match:
                    print(f"DEBUG: Match 'Release standard' sur: '{line_stripped}'")
                # Cas 2: Ligne précédente était "Release :" (vide) et actuelle est "Size/Ver... Q P T"
                elif i > 0 and lines[i-1].strip().lower() == "release :" and not release_line_pattern_re.match(lines[i-1].strip()): # s'assurer que la ligne Release est bien vide de chiffres
                    alt_match = alt_release_pattern_re.match(line_stripped)
                    if alt_match:
                        print(f"DEBUG: Match 'Release alternatif (Size/Ver...)' sur: '{line_stripped}' (précédé par 'Release :')")
                # Cas 3: Ligne précédente était "Release :" (vide) et actuelle est juste "Q P T" (pour lightsticks par ex.)
                elif i > 0 and lines[i-1].strip().lower() == "release :" and not release_line_pattern_re.match(lines[i-1].strip()):
                    simple_qty_price_match = simple_qty_price_pattern_re.match(line_stripped)
                    if simple_qty_price_match:
                        print(f"DEBUG: Match 'Release Q P T simple' sur: '{line_stripped}' (précédé par 'Release :')")


                if release_match or alt_match or simple_qty_price_match:
                    if product_name_buffer:
                        while product_name_buffer and not product_name_buffer[-1].strip(): product_name_buffer.pop()
                        product_name = " ".join(product_name_buffer).strip()
                        product_name = header_pattern_re.sub("", product_name).strip()
                        if "Release :" in product_name: product_name = product_name.split("Release :")[0].strip()

                        if not product_name:
                            print(f"DEBUG: Nom de produit vide après nettoyage pour ligne chiffres: '{line_stripped}'. Buffer: {' '.join(product_name_buffer)}")
                            product_name_buffer = []
                            continue

                        release_date_val = "N/A"
                        
                        if release_match:
                            release_date_val = release_match.group(1)
                            quantity = release_match.group(2)
                            unit_price = release_match.group(3)
                        elif alt_match:
                            # variation_name = alt_match.group(1) # Ex: H5687(Purple)
                            # product_name += f" ({variation_name})" # Optionnel: ajouter la variation au nom
                            quantity = alt_match.group(2)
                            unit_price = alt_match.group(3)
                        elif simple_qty_price_match:
                            quantity = simple_qty_price_match.group(1)
                            unit_price = simple_qty_price_match.group(2)
                        
                        parsed_products.append({
                            "name": product_name.strip(),
                            "quantity": int(quantity),
                            "unit_price_usd": float(unit_price),
                            "release_date": release_date_val
                        })
                        print(f"Produit trouvé: {product_name.strip()} (Qté: {quantity}, Prix: ${unit_price}, Date: {release_date_val})")
                    else:
                        print(f"DEBUG: Ligne de chiffres '{line_stripped}' SANS nom de produit dans buffer.")
                    product_name_buffer = []
                else:
                    known_parasites = ["weverse", "upbabyse", "theverse"] 
                    if line_stripped and line_stripped.lower() not in known_parasites:
                        product_name_buffer.append(line_stripped)
            
            if not parsed_products: print("Aucun produit n'a pu être parsé.")
            else: print(f"{len(parsed_products)} produits parsés au total.")

            # Recherche des frais globaux
            shipping_match = re.search(r"Shipping\s*\$?\s*(\d+\.?\d*)", full_text, re.IGNORECASE)
            if shipping_match: shipping_cost = shipping_match.group(1); print(f"Frais port (globaux): ${shipping_cost}")
            bank_fee_match = re.search(r"Bank transfer fee\s*\$?\s*(\d+\.?\d*)", full_text, re.IGNORECASE)
            if bank_fee_match: bank_fee = bank_fee_match.group(1); print(f"Frais bancaires (globaux): ${bank_fee}")

            return jsonify({
                "message": "Extraction produits (logique affinée v2), FDP et frais bancaires.",
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

    if not product_url_on_website and not product_name_from_invoice: # Au moins l'un des deux est requis
        return jsonify({"error": "Nom du produit ou URL du produit manquant."}), 400

    price_str = None
    debug_messages = []
    target_url = None # Initialiser target_url

    if product_url_on_website:
        target_url = product_url_on_website
        debug_messages.append(f"Utilisation de l'URL fournie: {target_url}")
    elif product_name_from_invoice:
        # Logique de test pour BLACKPINK - The Album
        if "blackpink" in product_name_from_invoice.lower() and "the album" in product_name_from_invoice.lower():
            target_url = "https://www.kalbums.com/product-page/the-album-1st-full-album"
            debug_messages.append(f"URL de test spécifique utilisée pour '{product_name_from_invoice}': {target_url}")
        else:
            # Ici, il faudrait une vraie logique pour construire une URL de recherche sur kalbums.com
            # Pour l'instant, on retourne "non trouvé" si l'URL exacte n'est pas fournie et que ce n'est pas le cas de test
            debug_messages.append(f"Nom du produit '{product_name_from_invoice}' reçu, mais pas d'URL directe et pas de cas de test correspondant. Recherche auto non implémentée.")
            return jsonify({
                "product_name_searched": product_name_from_invoice, "url_attempted": "N/A",
                "price_eur_ht": None, "error_message": "Recherche automatique par nom non disponible pour ce produit.",
                "debug_messages": debug_messages
            }), 200 # Retourner 200 OK mais avec un message d'erreur dans le JSON

    if not target_url: # Si aucune URL n'a pu être déterminée
        return jsonify({"error": "Impossible de déterminer l'URL à scraper.", "price_eur_ht": None, "debug": debug_messages}), 400


    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        print(f"DEBUG /api/get-website-price: Tentative de requête GET vers {target_url}")
        response = requests.get(target_url, headers=headers, timeout=15) # Timeout augmenté
        response.raise_for_status() 
        
        soup = BeautifulSoup(response.content, 'html.parser')
        debug_messages.append(f"Page {target_url} récupérée. Statut: {response.status_code}. Encodage: {response.encoding}")

        price_element = soup.find('span', attrs={'data-hook': 'formatted-primary-price'})
        
        if price_element:
            price_text = price_element.get_text(strip=True) 
            debug_messages.append(f"Élément prix trouvé. Texte brut: '{price_text}'")
            
            price_numeric_str = price_text.replace('€', '').replace(',', '.').strip()
            
            try:
                price_float = float(price_numeric_str)
                price_str = f"{price_float:.2f}" # Garder deux décimales
                debug_messages.append(f"Prix converti en float: {price_float}, formaté en chaîne: {price_str}")
            except ValueError:
                debug_messages.append(f"AVERTISSEMENT: Impossible de convertir '{price_numeric_str}' en float. Utilisation de la chaîne brute.")
                price_str = price_numeric_str # Fallback si la conversion échoue
        else:
            debug_messages.append("Élément prix avec data-hook='formatted-primary-price' non trouvé sur la page.")

    except requests.exceptions.Timeout:
        debug_messages.append(f"Erreur Timeout lors de la requête vers {target_url}")
    except requests.exceptions.HTTPError as http_err:
        debug_messages.append(f"Erreur HTTP lors de la requête vers {target_url}: {http_err} (Statut: {response.status_code if 'response' in locals() else 'N/A'})")
    except requests.exceptions.RequestException as e:
        debug_messages.append(f"Erreur générale de requête vers {target_url}: {str(e)}")
    except Exception as e:
        debug_messages.append(f"Erreur inattendue lors du scraping: {str(e)}")
        import traceback
        debug_messages.append(traceback.format_exc())


    return jsonify({
        "product_name_searched": product_name_from_invoice,
        "url_attempted": target_url,
        "price_eur_ht": price_str, 
        "debug_messages": debug_messages
    })
# --- FIN NOUVELLE ROUTE API ---

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True)
