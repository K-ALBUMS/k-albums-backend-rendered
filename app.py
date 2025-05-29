from flask import Flask, jsonify, request
from flask_cors import CORS
from PyPDF2 import PdfReader # Make sure PyPDF2 is in your requirements.txt
import io
import re # For regular expressions

app = Flask(__name__)
CORS(app) # Enable CORS for all routes

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
                    full_text += page_text + "\n"  # Add a newline between pages for clarity
            
            if not full_text.strip():
                full_text = "[PyPDF2 n'a pas pu extraire de texte. Le PDF est peut-être une image ou vide.]"
                print("Avertissement: Texte du PDF vide ou non extractible.")

            # For debugging the full text extraction by the backend:
            print("--- TEXTE COMPLET EXTRAIT DU PDF (pour débogage K-ALBUMS) ---")
            # print(full_text) # Uncomment this line if you want to see the ENTIRE PDF text in Render logs (can be very long)
            print(full_text[:2000]) # Print a larger snippet to Render logs for better context
            print("--- FIN TEXTE COMPLET EXTRAIT (Snippet de 2000 caractères) ---")

            shipping_cost = None
            bank_fee = None
            parsed_products = [] 
            product_name_buffer = []
            in_product_section = False # Flag to know if we are past the first product table header

            # Regex for product table header
            header_pattern_str = r"Product\s+Quantity\s+Price\s+Total"
            header_pattern_re = re.compile(header_pattern_str, re.IGNORECASE)

            # Regex for the line containing Release Date, Quantity, Price, Total
            # Example: Release : 2024-12-093 $14.41 $43.23
            # Groups:      (Date)        (Qty) (UnitPrice) (LineTotal)
            release_line_pattern_re = re.compile(r"Release\s*:\s*(\d{4}-\d{2}-\d{2})\s*(\d+)\s*\$(\d+\.\d+)\s*\$(\d+\.\d+)")

            lines = full_text.split('\n')

            for line_text in lines:
                line_stripped = line_text.strip()
                
                is_header_line = header_pattern_re.match(line_stripped)

                if not in_product_section and is_header_line:
                    in_product_section = True
                    product_name_buffer = [] 
                    print("DEBUG: En-tête initial du tableau des produits trouvé et passé.")
                    continue 

                if not in_product_section:
                    continue # Skip lines until we are in the product section

                if is_header_line: # If we find another header while in product section
                    print(f"DEBUG: En-tête de tableau répétée ignorée: {line_stripped}")
                    # If buffer has content, it might be a product name for a line that lacked a "Release..."
                    # This part is tricky and depends on invoice structure. For now, we clear it
                    # to avoid it prepending to the *next* product after this repeated header.
                    if product_name_buffer:
                         print(f"DEBUG: Buffer vidé à cause d'un en-tête répété. Contenu: {' '.join(product_name_buffer)}")
                         product_name_buffer = []
                    continue

                release_line_match = release_line_pattern_re.match(line_stripped)

                if release_line_match:
                    if product_name_buffer: 
                        product_name = " ".join(product_name_buffer).strip()
                        
                        # Clean any residual header pattern from the assembled name (just in case)
                        product_name = header_pattern_re.sub("", product_name).strip()
                        
                        # Further clean "Release : ..." if it somehow got into the name buffer
                        # This happens if "Release..." is on the same line as the name
                        # or if the buffer wasn't cleared properly.
                        # We only want what's BEFORE "Release :" if "Release :" is in the product_name string.
                        if "Release :" in product_name:
                             product_name = product_name.split("Release :")[0].strip()

                        if not product_name: # If name became empty after cleaning
                            print(f"DEBUG: Nom de produit vide après nettoyage pour la ligne 'Release': {line_stripped}. Buffer était: {' '.join(product_name_buffer)}")
                            product_name_buffer = [] 
                            continue # Skip this entry

                        release_date = release_line_match.group(1)
                        quantity = release_line_match.group(2)
                        unit_price = release_line_match.group(3)
                        # line_total = release_line_match.group(4) # Available if needed
                        
                        parsed_products.append({
                            "name": product_name,
                            "quantity": int(quantity),
                            "unit_price_usd": float(unit_price),
                            "release_date": release_date
                        })
                        print(f"Produit trouvé: {product_name} (Qté: {quantity}, Prix: ${unit_price})")
                    else:
                        # This case means a "Release..." line was found but no preceding lines were buffered for its name.
                        # This could happen if the product name is on the SAME line as "Release...",
                        # or if the PDF structure is very unusual.
                        print(f"DEBUG: Ligne 'Release' trouvée SANS nom de produit dans le buffer: {line_stripped}. Peut indiquer un nom de produit manquant ou sur la même ligne.")
                    product_name_buffer = [] # Always reset buffer after processing a "Release" line
                else:
                    # If it's not a "Release" line, and not an ignored header, and not empty, add to name buffer
                    known_parasites = ["weverse", "upbabyse", "theverse"] # Can be expanded
                    if line_stripped and line_stripped.lower() not in known_parasites:
                        product_name_buffer.append(line_stripped)
            
            if not parsed_products:
                print("Aucun produit n'a pu être parsé avec la logique actuelle.")
            else:
                print(f"{len(parsed_products)} produits parsés au total.")

            # Recherche des frais globaux (après le parsing des produits)
            shipping_match = re.search(r"Shipping\s*\$?\s*(\d+\.?\d*)", full_text, re.IGNORECASE)
            if shipping_match:
                shipping_cost = shipping_match.group(1)
                print(f"Frais de port (globaux) trouvés: ${shipping_cost}")

            bank_fee_match = re.search(r"Bank transfer fee\s*\$?\s*(\d+\.?\d*)", full_text, re.IGNORECASE)
            if bank_fee_match:
                bank_fee = bank_fee_match.group(1)
                print(f"Frais bancaires (globaux) trouvés: ${bank_fee}")

            return jsonify({
                "message": "Extraction produits (noms multi-lignes affinés), FDP et frais bancaires.",
                "filename": file.filename,
                "shipping_cost_usd": shipping_cost,
                "bank_transfer_fee_usd": bank_fee,
                "parsed_products": parsed_products,
                "DEVELOPMENT_full_text_for_debug": full_text # On renvoie toujours le texte complet pour le moment
            })

        except Exception as e:
            print(f"Erreur critique lors du traitement du fichier PDF : {e}")
            import traceback
            traceback.print_exc() 
            return jsonify({"error": f"Erreur interne majeure lors du traitement du PDF: {str(e)}"}), 500
    
    return jsonify({"error": "Un problème est survenu avec le fichier ou le fichier n'a pas été traité."}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True)
