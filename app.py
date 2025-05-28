from flask import Flask, jsonify, request
from flask_cors import CORS
from PyPDF2 import PdfReader
import io
import re # <--- AJOUT: Pour les expressions régulières (recherche de texte)

app = Flask(__name__)
CORS(app)

@app.route('/')
def home():
    # ... (code inchangé ici) ...
    return jsonify({
        "message": "Bienvenue sur le backend K-Albums!", 
        "status": "en fonctionnement",
        "info": "Ceci est un service hébergé sur Render."
    })

@app.route('/api/test')
def api_test():
    # ... (code inchangé ici) ...
    return jsonify({"message": "Réponse de test de l'API du backend!"})

@app.route('/api/receive-filename', methods=['POST'])
def receive_filename():
    # ... (code inchangé ici, on le garde pour l'instant) ...
    try:
        data = request.get_json() 
        if not data or 'filename' not in data:
            return jsonify({"error": "Nom de fichier manquant dans la requête"}), 400
        filename = data['filename']
        print(f"Nom de fichier reçu (ancienne route) : {filename}") 
        return jsonify({
            "message": "Nom de fichier bien reçu par le backend (ancienne route)!",
            "filename_received": filename
        })
    except Exception as e:
        print(f"Erreur lors du traitement de receive_filename: {e}")
        return jsonify({"error": "Erreur interne du serveur"}), 500

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
            # --- MODIFICATION : Extraire le texte de toutes les pages ---
            for page_num in range(len(reader.pages)):
                page = reader.pages[page_num]
                page_text = page.extract_text()
                if page_text:
                    full_text += page_text + "\n" # Ajoute le texte de la page et un saut de ligne
            
            if not full_text.strip():
                full_text = "[PyPDF2 n'a pas pu extraire de texte. Le PDF est peut-être une image ou vide.]"

            # --- AJOUT : Recherche des frais de port et frais bancaires ---
            shipping_cost = None
            bank_fee = None

            # Expression régulière pour trouver "Shipping" suivi d'un montant en dollars
            # Ex: "Shipping $123.45" ou "Shipping                   $  123.45"
            # \s* signifie "zéro ou plusieurs espaces"
            # \$? signifie "un dollar optionnel" (pour être flexible)
            # (\d+\.?\d*) signifie "un ou plusieurs chiffres, suivis optionnellement d'un point et d'autres chiffres"
            shipping_match = re.search(r"Shipping\s*\$?\s*(\d+\.?\d*)", full_text, re.IGNORECASE)
            if shipping_match:
                shipping_cost = shipping_match.group(1) # Le groupe 1 est la valeur capturée (le montant)
                print(f"Frais de port trouvés: {shipping_cost}")

            # Expression régulière pour "Bank transfer fee"
            bank_fee_match = re.search(r"Bank transfer fee\s*\$?\s*(\d+\.?\d*)", full_text, re.IGNORECASE)
            if bank_fee_match:
                bank_fee = bank_fee_match.group(1)
                print(f"Frais bancaires trouvés: {bank_fee}")
            # --- FIN AJOUT ---

            print(f"Texte complet extrait (premiers 500 caractères): {full_text[:500]}")

            return jsonify({
                "message": "Fichier PDF reçu et tentative d'extraction de texte et de frais effectuée.",
                "filename": file.filename,
                "extracted_full_text_snippet": full_text[:1000], # On renvoie un extrait du texte complet
                "shipping_cost_usd": shipping_cost, # Peut être None s'il n'est pas trouvé
                "bank_transfer_fee_usd": bank_fee # Peut être None s'il n'est pas trouvé
            })

        except Exception as e:
            print(f"Erreur lors du traitement du fichier PDF : {e}")
            return jsonify({"error": f"Erreur lors du traitement du PDF: {str(e)}"}), 500
    
    return jsonify({"error": "Un problème est survenu avec le fichier"}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True)
