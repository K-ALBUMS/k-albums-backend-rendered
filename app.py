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

# On peut commenter ou supprimer cette ancienne route si elle n'est plus utile
# @app.route('/api/receive-filename', methods=['POST'])
# def receive_filename():
#     # ... (code de l'ancienne route)

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
            product_lines_snippet = None # <--- NOUVEAU : Pour l'extrait des lignes produits

            # Recherche des frais (comme avant)
            shipping_match = re.search(r"Shipping\s*\$?\s*(\d+\.?\d*)", full_text, re.IGNORECASE)
            if shipping_match:
                shipping_cost = shipping_match.group(1)
                print(f"Frais de port trouvés: {shipping_cost}")

            bank_fee_match = re.search(r"Bank transfer fee\s*\$?\s*(\d+\.?\d*)", full_text, re.IGNORECASE)
            if bank_fee_match:
                bank_fee = bank_fee_match.group(1)
                print(f"Frais bancaires trouvés: {bank_fee}")

            # --- AJOUT : Tentative d'extraction des premières lignes de produits ---
            # On cherche l'en-tête du tableau des produits. 
            # Il faudra peut-être ajuster cette recherche en fonction de la variabilité du texte.
            # On cherche une ligne qui contient "Product", "Quantity", "Price", "Total" dans cet ordre, 
            # avec potentiellement des espaces variables entre eux.
            # Ceci est une regex simple, elle pourrait avoir besoin d'être affinée.
            product_table_header_match = re.search(r"Product\s+Quantity\s+Price\s+Total", full_text, re.IGNORECASE)
            
            if product_table_header_match:
                print("En-tête du tableau des produits trouvé.")
                # Prend le texte APRÈS l'en-tête trouvé
                text_after_header = full_text[product_table_header_match.end():]
                # Sépare ce texte en lignes et prend les premières (par exemple, 5 lignes)
                lines_after_header = text_after_header.strip().split('\n')
                # On prend jusqu'à 5 lignes pour l'extrait, ou moins s'il y en a moins.
                num_lines_to_extract = min(len(lines_after_header), 10) # Prenons 10 lignes pour voir un peu plus
                product_lines_snippet = "\n".join(lines_after_header[:num_lines_to_extract])
                print(f"Extrait des lignes de produits:\n{product_lines_snippet}")
            else:
                print("En-tête du tableau des produits NON trouvé.")
            # --- FIN AJOUT ---

            return jsonify({
                "message": "Fichier PDF reçu, tentative d'extraction de texte, frais et début de table produits effectuée.",
                "filename": file.filename,
                "extracted_full_text_snippet": full_text[:200], # On peut réduire la taille de ce snippet général
                "shipping_cost_usd": shipping_cost,
                "bank_transfer_fee_usd": bank_fee,
                "product_lines_snippet": product_lines_snippet # <--- NOUVEAU : On renvoie l'extrait
            })

        except Exception as e:
            print(f"Erreur lors du traitement du fichier PDF : {e}")
            return jsonify({"error": f"Erreur lors du traitement du PDF: {str(e)}"}), 500
    
    return jsonify({"error": "Un problème est survenu avec le fichier"}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True)
