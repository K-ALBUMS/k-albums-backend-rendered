from flask import Flask, jsonify, request
from flask_cors import CORS # <--- AJOUTEZ CET IMPORT

app = Flask(__name__)
CORS(app) # <--- AJOUTEZ CETTE LIGNE POUR ACTIVER CORS POUR TOUTES LES ROUTES

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

@app.route('/api/receive-filename', methods=['POST'])
def receive_filename():
    try:
        data = request.get_json() 
        if not data or 'filename' not in data:
            return jsonify({"error": "Nom de fichier manquant dans la requête"}), 400

        filename = data['filename']
        print(f"Nom de fichier reçu sur le backend : {filename}") 

        return jsonify({
            "message": "Nom de fichier bien reçu par le backend!",
            "filename_received": filename
        })
    except Exception as e:
        print(f"Erreur lors du traitement de receive_filename: {e}")
        return jsonify({"error": "Erreur interne du serveur lors de la réception du nom de fichier"}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True)
