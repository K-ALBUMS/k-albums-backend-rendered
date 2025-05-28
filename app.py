from flask import Flask, jsonify, request # Ajoutez 'request' ici

app = Flask(__name__)

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

# --- NOUVELLE ROUTE CI-DESSOUS ---
@app.route('/api/receive-filename', methods=['POST']) # Accepte les requêtes POST
def receive_filename():
    try:
        data = request.get_json() # Récupère les données JSON envoyées
        if not data or 'filename' not in data:
            # Si 'filename' n'est pas dans les données ou si pas de données
            return jsonify({"error": "Nom de fichier manquant dans la requête"}), 400 # 400 = Bad Request

        filename = data['filename']
        print(f"Nom de fichier reçu sur le backend : {filename}") # Affiche dans les logs de Render

        # Renvoyer une confirmation
        return jsonify({
            "message": "Nom de fichier bien reçu par le backend!",
            "filename_received": filename
        })
    except Exception as e:
        print(f"Erreur lors du traitement de receive_filename: {e}")
        return jsonify({"error": "Erreur interne du serveur lors de la réception du nom de fichier"}), 500
# --- FIN DE LA NOUVELLE ROUTE ---

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True)
