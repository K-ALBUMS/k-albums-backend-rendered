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
            parsed_products = [] 

            shipping_match = re.search(r"Shipping\s*\$?\s*(\d+\.?\d*)", full_text, re.IGNORECASE)
            if shipping_match:
                shipping_cost = shipping_match.group(1)
                print(f"Frais de port trouvés: {shipping_cost}")

            bank_fee_match = re.search(r"Bank transfer fee\s*\$?\s*(\d+\.?\d*)", full_text, re.IGNORECASE)
            if bank_fee_match:
                bank_fee = bank_fee_match.group(1)
                print(f"Frais bancaires trouvés: {bank_fee}")

            # --- MODIFICATION : Logique améliorée pour les noms de produits multi-lignes ---
            lines = full_text.split('\n')
            product_name_buffer = [] # Un buffer pour accumuler les lignes du nom d'un produit

            for line_text in lines:
                line_stripped = line_text.strip()
                
                # Regex pour trouver la ligne avec Release Date, Quantité, Prix, Total
                release_line_match = re.match(r"Release\s*:\s*(\d{4}-\d{2}-\d{2})\s*(\d+)\s*\$(\d+\.\d+)\s*\$(\d+\.\d+)", line_stripped)

                if release_line_match:
                    # Si on trouve une ligne "Release...", alors ce qui est dans product_name_buffer est le nom du produit
                    if product_name_buffer: # S'assurer qu'on a collecté quelque chose pour le nom
                        product_name = " ".join(product_name_buffer).strip() # Joindre les lignes du nom
                        
                        release_date = release_line_match.group(1)
                        quantity = release_line_match.group(2)
                        unit_price = release_line_match.group(3)
                        
                        parsed_products.append({
                            "name": product_name,
                            "quantity": int(quantity),
                            "unit_price_usd": float(unit_price),
                            "release_date": release_date
                        })
                        print(f"Produit trouvé: {product_name}, Qté: {quantity}, Prix: {unit_price}")
                        product_name_buffer = [] # Réinitialiser le buffer pour le prochain produit
                    else:
                        # Cela pourrait arriver si une ligne "Release..." apparaît sans nom de produit collecté avant
                        print(f"Ligne 'Release' trouvée sans nom de produit précédent dans le buffer: {line_stripped}")
                else:
                    # Si la ligne ne ressemble pas à une ligne "Release...", 
                    # et qu'elle n'est pas vide, on l'ajoute au buffer du nom du produit actuel.
                    # On peut aussi ajouter des conditions pour ignorer des lignes parasites (ex: "weverse", "UPBABYSE")
                    # ou des lignes d'en-tête de tableau si elles ne sont pas déjà filtrées.
                    if line_stripped and not line_stripped.lower() in ["weverse", "upbabyse", "theverse"] and not re.match(r"Product\s+Quantity\s+Price\s+Total", line_stripped, re.IGNORECASE):
                        product_name_buffer.append(line_stripped)
            
            if not parsed_products:
                print("Aucun produit n'a pu être parsé avec la logique actuelle.")
            # --- FIN MODIFICATION ---

            return jsonify({
                "message": "Tentative d'extraction des produits (noms multi-lignes), frais de port et frais bancaires.",
                "filename": file.filename,
                "shipping_cost_usd": shipping_cost,
                "bank_transfer_fee_usd": bank_fee,
                "parsed_products": parsed_products,
                "extracted_full_text_snippet": full_text[:200] 
            })

        except Exception as e:
            print(f"Erreur lors du traitement du fichier PDF : {e}")
            # Tenter de renvoyer plus de détails sur l'erreur e si possible, mais str(e) est un bon début
            return jsonify({"error": f"Erreur lors du traitement du PDF: {str(e)}"}), 500
    
    return jsonify({"error": "Un problème est survenu avec le fichier"}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True)
