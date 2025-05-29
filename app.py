from flask import Flask, jsonify, request
from flask_cors import CORS
from PyPDF2 import PdfReader
import io
import re

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
            print(f"--- Nouveau traitement de PDF : {file.filename} ---") # Log de début
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


            shipping_cost = None
            bank_fee = None
            parsed_products = [] 
            product_name_buffer = []
            in_product_section = False # Nouveau drapeau pour savoir si on est dans la section des produits

            # Recherche des frais (comme avant)
            shipping_match = re.search(r"Shipping\s*\$?\s*(\d+\.?\d*)", full_text, re.IGNORECASE)
            if shipping_match:
                shipping_cost = shipping_match.group(1)
                print(f"Frais de port trouvés: ${shipping_cost}")

            bank_fee_match = re.search(r"Bank transfer fee\s*\$?\s*(\d+\.?\d*)", full_text, re.IGNORECASE)
            if bank_fee_match:
                bank_fee = bank_fee_match.group(1)
                print(f"Frais bancaires trouvés: ${bank_fee}")

            # --- LOGIQUE DE PARSING DES LIGNES PRODUITS AMÉLIORÉE ---
            lines = full_text.split('\n')

            for line_text in lines:
                line_stripped = line_text.strip()

                # 1. Chercher l'en-tête du tableau pour commencer à traiter les produits
                if not in_product_section and re.match(r"Product\s+Quantity\s+Price\s+Total", line_stripped, re.IGNORECASE):
                    in_product_section = True
                    product_name_buffer = [] # On vide le buffer au cas où
                    print("DEBUG: En-tête du tableau des produits trouvé. Début de la section produits.")
                    continue # On passe à la ligne suivante, l'en-tête n'est pas un nom de produit

                # Si on n'est pas encore dans la section produit, on ignore la ligne
                if not in_product_section:
                    continue

                # 2. Maintenant on est dans la section produit, on cherche les lignes "Release..."
                release_line_match = re.match(r"Release\s*:\s*(\d{4}-\d{2}-\d{2})\s*(\d+)\s*\$(\d+\.\d+)\s*\$(\d+\.\d+)", line_stripped)

                if release_line_match:
                    if product_name_buffer: 
                        product_name = " ".join(product_name_buffer).strip()
                        
                        release_date = release_line_match.group(1)
                        quantity = release_line_match.group(2)
                        unit_price = release_line_match.group(3)
                        
                        parsed_products.append({
                            "name": product_name,
                            "quantity": int(quantity),
                            "unit_price_usd": float(unit_price),
                            "release_date": release_date
                        })
                        print(f"Produit trouvé: {product_name} (Qté: {quantity}, Prix: ${unit_price})")
                        product_name_buffer = [] 
                    else:
                        print(f"DEBUG: Ligne 'Release' trouvée sans nom de produit dans le buffer: {line_stripped} (Peut arriver si le nom est sur la même ligne ou si le PDF est mal formaté pour cette logique)")
                else:
                    # Si ce n'est pas une ligne "Release", et qu'on est dans la section produit,
                    # et que la ligne n'est pas vide ou un parasite connu : on l'ajoute au nom.
                    # J'ai simplifié la condition d'exclusion ici, on pourra l'affiner.
                    # Principalement, on veut éviter d'ajouter des lignes vides au nom.
                    if line_stripped and not line_stripped.lower() in ["weverse", "upbabyse", "theverse"]:
                        product_name_buffer.append(line_stripped)
                        # print(f"DEBUG: Ajouté au buffer nom: '{line_stripped}'") # Décommentez pour beaucoup de logs
            
            if not parsed_products:
                print("Aucun produit n'a pu être parsé avec la logique actuelle.")
            else:
                print(f"{len(parsed_products)} produits parsés au total.")
            # --- FIN LOGIQUE DE PARSING ---

            return jsonify({
                "message": "Extraction (multi-lignes noms) des produits, frais de port et frais bancaires.",
                "filename": file.filename,
                "shipping_cost_usd": shipping_cost,
                "bank_transfer_fee_usd": bank_fee,
                "parsed_products": parsed_products,
                "extracted_full_text_snippet": full_text[:150] # Réduit pour ne pas surcharger inutilement
            })

        except Exception as e:
            print(f"Erreur critique lors du traitement du fichier PDF : {e}")
            import traceback
            traceback.print_exc() # Imprime plus de détails sur l'erreur dans les logs Render
            return jsonify({"error": f"Erreur interne majeure lors du traitement du PDF: {str(e)}"}), 500
    
    return jsonify({"error": "Un problème est survenu avec le fichier ou le fichier n'a pas été traité."}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True)
