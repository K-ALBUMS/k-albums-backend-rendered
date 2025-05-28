from flask import Flask, jsonify, request
from flask_cors import CORS
from PyPDF2 import PdfReader
import io
import re

app = Flask(__name__)
CORS(app)

# ... (les routes '/' et '/api/test' restent inchangées) ...
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
            print(f"Fichier PDF reçu : {file.filename}")
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

            shipping_cost = None
            bank_fee = None
            # --- MODIFICATION : On va stocker les produits dans une liste ---
            parsed_products = [] 

            shipping_match = re.search(r"Shipping\s*\$?\s*(\d+\.?\d*)", full_text, re.IGNORECASE)
            if shipping_match:
                shipping_cost = shipping_match.group(1)
                print(f"Frais de port trouvés: {shipping_cost}")

            bank_fee_match = re.search(r"Bank transfer fee\s*\$?\s*(\d+\.?\d*)", full_text, re.IGNORECASE)
            if bank_fee_match:
                bank_fee = bank_fee_match.group(1)
                print(f"Frais bancaires trouvés: {bank_fee}")

            # --- DÉBUT DE LA NOUVELLE LOGIQUE DE PARSING DES LIGNES PRODUITS ---
            # On divise le texte complet en lignes pour l'analyser ligne par ligne
            lines = full_text.split('\n')
            product_name_buffer = [] # Pour gérer les noms de produits sur plusieurs lignes (amélioration future)

            for i, line in enumerate(lines):
                # Regex pour trouver la ligne avec Release Date, Quantité, Prix, Total
                # Ex: Release : 2024-12-093 $14.41 $43.23
                # Groupes : (Date) (Quantité) (PrixUnitaire) (PrixTotalLigne)
                match = re.match(r"Release\s*:\s*(\d{4}-\d{2}-\d{2})\s*(\d+)\s*\$(\d+\.\d+)\s*\$(\d+\.\d+)", line.strip())

                if match:
                    # Si on trouve une ligne de "Release...", la ligne précédente (ou les précédentes) est le nom du produit
                    if i > 0: # S'assurer qu'il y a une ligne précédente
                        # Pour cette première version simple, on prend juste la ligne d'avant comme nom
                        # Amélioration future: gérer les noms sur plusieurs lignes en utilisant product_name_buffer
                        product_name = lines[i-1].strip() 
                        
                        release_date = match.group(1)
                        quantity = match.group(2)
                        unit_price = match.group(3)
                        # line_total = match.group(4) # On a aussi le total de la ligne si besoin

                        parsed_products.append({
                            "name": product_name,
                            "quantity": int(quantity),
                            "unit_price_usd": float(unit_price),
                            "release_date": release_date
                            # "line_total_usd": float(line_total) # Optionnel
                        })
                        print(f"Produit trouvé: {product_name}, Qté: {quantity}, Prix: {unit_price}")
                        product_name_buffer = [] # Réinitialiser le buffer pour le prochain produit
                    else:
                        print(f"Ligne 'Release' trouvée sans nom de produit précédent: {line}")
                # else:
                    # Si la ligne ne correspond pas à "Release...", elle pourrait faire partie d'un nom de produit.
                    # On pourrait l'ajouter à product_name_buffer ici pour une gestion plus avancée
                    # des noms multi-lignes. Pour l'instant, on garde simple.
                    # if line.strip(): # Si la ligne n'est pas vide
                    #    product_name_buffer.append(line.strip())
            
            if not parsed_products:
                print("Aucun produit n'a pu être parsé avec la logique actuelle.")
            # --- FIN DE LA NOUVELLE LOGIQUE DE PARSING ---

            return jsonify({
                "message": "Tentative d'extraction des produits, frais de port et frais bancaires.",
                "filename": file.filename,
                "shipping_cost_usd": shipping_cost,
                "bank_transfer_fee_usd": bank_fee,
                "parsed_products": parsed_products, # <--- NOUVEAU : On renvoie la liste des produits
                "extracted_full_text_snippet": full_text[:200] # Gardons un petit extrait pour débogage
            })

        except Exception as e:
            print(f"Erreur lors du traitement du fichier PDF : {e}")
            return jsonify({"error": f"Erreur lors du traitement du PDF: {str(e)}"}), 500
    
    return jsonify({"error": "Un problème est survenu avec le fichier"}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True)
