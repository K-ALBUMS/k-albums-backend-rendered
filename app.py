from flask import Flask, jsonify, request
from flask_cors import CORS
from PyPDF2 import PdfReader # <--- AJOUT: Pour lire les PDF
import io # <--- AJOUT: Pour manipuler le fichier en mémoire

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

# On garde l'ancienne route pour l'instant, au cas où, mais on va se concentrer sur la nouvelle
@app.route('/api/receive-filename', methods=['POST'])
def receive_filename():
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

# --- NOUVELLE ROUTE POUR UPLOADER ET TRAITER LE PDF ---
@app.route('/api/upload-invoice', methods=['POST'])
def upload_invoice():
    if 'invoice_pdf' not in request.files:
        return jsonify({"error": "Aucun fichier PDF trouvé dans la requête"}), 400

    file = request.files['invoice_pdf']

    if file.filename == '':
        return jsonify({"error": "Aucun fichier sélectionné"}), 400

    if file: # On vérifie si un fichier a bien été envoyé
        try:
            print(f"Fichier PDF reçu : {file.filename}")

            # Lire le contenu du fichier en mémoire
            file_content_in_memory = io.BytesIO(file.read())

            # Essayer d'extraire le texte avec PyPDF2
            reader = PdfReader(file_content_in_memory)
            extracted_text = ""
            if len(reader.pages) > 0:
                # Extrait le texte de la première page uniquement pour ce test
                page = reader.pages[0] 
                extracted_text = page.extract_text()
                if not extracted_text: # Si extract_text() ne retourne rien (par ex. PDF image)
                    extracted_text = "[PyPDF2 n'a pas pu extraire de texte de la première page. Le PDF est peut-être une image.]"
            else:
                extracted_text = "[Le PDF ne contient aucune page.]"

            print(f"Texte extrait de la première page (premiers 500 caractères): {extracted_text[:500]}")

            return jsonify({
                "message": "Fichier PDF reçu et tentative d'extraction de texte effectuée.",
                "filename": file.filename,
                "extracted_text_page_1_snippet": extracted_text[:1000] # Renvoie un extrait plus long
            })

        except Exception as e:
            print(f"Erreur lors du traitement du fichier PDF : {e}")
            return jsonify({"error": f"Erreur lors du traitement du PDF: {str(e)}"}), 500

    return jsonify({"error": "Un problème est survenu avec le fichier"}), 500
# --- FIN DE LA NOUVELLE ROUTE ---

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True)
